"""
Autonomous monitoring worker using APScheduler.
Polls database metrics, detects slow queries, creates incidents.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.database.engine import get_db_context, get_monitored_engine
from app.models import (
    MonitoringMetricModel, IncidentModel,
    IncidentSeverity, IncidentStatus,
)

logger = logging.getLogger(__name__)
settings = get_settings()

_monitoring_active = False
_scheduler = None


def is_monitoring_active() -> bool:
    return _monitoring_active


def collect_sqlite_metrics(engine) -> dict[str, Any]:
    """Collect basic metrics from SQLite (for dev mode)."""
    with engine.connect() as conn:
        result = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
        tables = [r[0] for r in result.fetchall()]
        table_stats = {}
        for tname in tables:
            try:
                cnt = conn.execute(text(f'SELECT COUNT(*) FROM "{tname}"')).scalar()
                table_stats[tname] = cnt
            except Exception:
                pass
    return {
        "type": "sqlite",
        "tables": tables,
        "table_row_counts": table_stats,
        "collected_at": datetime.now(timezone.utc).isoformat(),
    }


def collect_postgres_metrics(engine) -> dict[str, Any]:
    """Collect pg_stat_statements metrics from PostgreSQL."""
    metrics = {"type": "postgresql", "collected_at": datetime.now(timezone.utc).isoformat()}
    with engine.connect() as conn:
        # Check if pg_stat_statements is available
        try:
            result = conn.execute(text("""
                SELECT query, calls, total_exec_time, mean_exec_time, max_exec_time
                FROM pg_stat_statements
                ORDER BY total_exec_time DESC
                LIMIT 20
            """))
            rows = result.fetchall()
            metrics["slow_queries"] = [
                {
                    "query": r[0][:200],
                    "calls": r[1],
                    "total_exec_time_ms": round(r[2], 2),
                    "mean_exec_time_ms": round(r[3], 2),
                    "max_exec_time_ms": round(r[4], 2),
                }
                for r in rows
            ]
        except Exception as e:
            metrics["pg_stat_statements"] = f"not available: {e}"
            metrics["slow_queries"] = []

        # Database size
        try:
            db_size = conn.execute(text("SELECT pg_size_pretty(pg_database_size(current_database()))")).scalar()
            metrics["database_size"] = db_size
        except Exception:
            pass

        # Active connections
        try:
            active = conn.execute(text("SELECT count(*) FROM pg_stat_activity WHERE state = 'active'")).scalar()
            metrics["active_connections"] = active
        except Exception:
            pass

    return metrics


def detect_slow_queries(metrics: dict) -> list[dict]:
    """Extract queries exceeding the slow query threshold."""
    threshold = settings.slow_query_threshold_ms
    slow = []
    for q in metrics.get("slow_queries", []):
        if q.get("mean_exec_time_ms", 0) > threshold or q.get("max_exec_time_ms", 0) > threshold * 2:
            slow.append(q)
    return slow


def _get_or_create_incident(db: Session, fingerprint: str, title: str, evidence: dict) -> bool:
    """Create an incident if no open incident exists for this fingerprint."""
    existing = (
        db.query(IncidentModel)
        .filter_by(query_fingerprint=fingerprint)
        .filter(IncidentModel.status.in_([IncidentStatus.open, IncidentStatus.investigating]))
        .first()
    )
    if existing:
        return False  # Already tracked

    severity = IncidentSeverity.medium
    if evidence.get("max_exec_time_ms", 0) > settings.slow_query_threshold_ms * 5:
        severity = IncidentSeverity.high

    incident = IncidentModel(
        title=title,
        description=f"Automatically detected by monitoring agent at {datetime.now(timezone.utc).isoformat()}",
        severity=severity,
        status=IncidentStatus.open,
        evidence=evidence,
        query_fingerprint=fingerprint,
        agent_log=[{
            "step": "monitoring_agent",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": "incident_created",
            "detail": title,
        }],
    )
    db.add(incident)
    db.commit()
    logger.warning("Incident created: %s [severity=%s]", title, severity.value)
    return True


def run_monitoring_cycle() -> dict[str, Any]:
    """
    Single monitoring cycle: collect metrics, detect issues, record incidents.
    """
    result = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "incidents_created": 0,
        "metrics_collected": False,
        "errors": [],
    }

    try:
        mon_engine = get_monitored_engine()
        if settings.is_postgres:
            metrics = collect_postgres_metrics(mon_engine)
        else:
            metrics = collect_sqlite_metrics(mon_engine)

        result["metrics_collected"] = True

        with get_db_context() as db:
            # Save metric snapshot
            db.add(MonitoringMetricModel(
                metric_name="monitoring_cycle",
                metric_json=metrics,
            ))

            # Check for slow queries
            slow = detect_slow_queries(metrics)
            for q in slow:
                fingerprint = str(hash(q.get("query", "")[:100]))
                title = f"Slow query detected: mean={q['mean_exec_time_ms']:.0f}ms, max={q['max_exec_time_ms']:.0f}ms"
                created = _get_or_create_incident(db, fingerprint, title, q)
                if created:
                    result["incidents_created"] += 1

        logger.info("Monitoring cycle complete. %d incident(s) created.", result["incidents_created"])

    except Exception as exc:
        logger.error("Monitoring cycle error: %s", exc)
        result["errors"].append(str(exc))

    return result


def start_monitoring():
    """Start the APScheduler background monitoring job."""
    global _monitoring_active, _scheduler
    if _monitoring_active:
        return {"status": "already_running"}

    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.interval import IntervalTrigger

        _scheduler = BackgroundScheduler()
        _scheduler.add_job(
            run_monitoring_cycle,
            trigger=IntervalTrigger(seconds=settings.monitor_interval_seconds),
            id="monitoring_cycle",
            max_instances=1,
            coalesce=True,
        )
        _scheduler.start()
        _monitoring_active = True
        logger.info("Monitoring started. Interval: %ds", settings.monitor_interval_seconds)
        return {"status": "started", "interval_seconds": settings.monitor_interval_seconds}
    except Exception as exc:
        logger.error("Failed to start monitoring: %s", exc)
        return {"status": "error", "error": str(exc)}


def stop_monitoring():
    """Stop the APScheduler background monitoring job."""
    global _monitoring_active, _scheduler
    if not _monitoring_active or _scheduler is None:
        return {"status": "not_running"}
    try:
        _scheduler.shutdown(wait=False)
        _monitoring_active = False
        _scheduler = None
        return {"status": "stopped"}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}
