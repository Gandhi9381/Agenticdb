"""
Optimization Execution Service for AgenticDB.

Responsible for:
- Idempotent index recommendation creation (deduplication by identity key)
- Index existence verification against the actual SQLite database
- Authorized execution of approved index operations
- Benchmarking with proper warm-up, repeated runs, and validity checks
- Reliable result persistence

This module is the ONLY place that creates indexes on the database.
The SQL Query Assistant (execute_read_only_sql) must NOT be used for this.
"""
from __future__ import annotations

import logging
import re
import statistics
import time
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.database.engine import app_engine
from app.models import (
    OptimizationModel, OptimizationStatus, ExecutionStatus,
    ApprovalModel, ApprovalStatus,
)

logger = logging.getLogger(__name__)
settings = get_settings()

# ─────────────────────────────────────────────────────────────
# Identity helpers
# ─────────────────────────────────────────────────────────────

def _parse_index_sql(proposed_sql: str) -> dict[str, Optional[str]]:
    """Extract table, sorted columns, and index name from a CREATE INDEX statement."""
    result: dict[str, Optional[str]] = {
        "table_name": None,
        "columns": None,
        "index_name": None,
    }
    if not proposed_sql:
        return result
    m = re.search(
        r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)\s+ON\s+(\w+)\s*\(\s*([^)]+)\s*\)",
        proposed_sql,
        re.IGNORECASE,
    )
    if m:
        result["index_name"] = m.group(1).strip()
        result["table_name"] = m.group(2).strip()
        result["columns"] = ",".join(
            sorted(c.strip() for c in m.group(3).split(","))
        )
    return result


def build_identity_key(db_target: str, table_name: str, columns: str) -> str:
    """Stable identity key for deduplication: <db_target>::<table>::<columns_sorted>"""
    return f"{db_target}::{table_name}::{columns}"


def _safe_identifier(name: str) -> str:
    """Return a quoted SQLite identifier. Raises if name contains disallowed characters."""
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name):
        raise ValueError(f"Identifier '{name}' contains disallowed characters.")
    return f'"{name}"'


# ─────────────────────────────────────────────────────────────
# Index existence check
# ─────────────────────────────────────────────────────────────

def check_index_exists(index_name: str, table_name: str) -> bool:
    """
    Query the actual SQLite database to check whether an index exists.
    Does NOT infer existence from recommendation records.
    """
    try:
        with app_engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='index' AND name=:idx AND tbl_name=:tbl"
                ),
                {"idx": index_name, "tbl": table_name},
            ).fetchone()
            return row is not None
    except Exception as exc:
        logger.error("Index existence check failed: %s", exc)
        return False


def check_equivalent_index_exists(table_name: str, columns_sorted: str) -> Optional[str]:
    """
    Check whether any index on the given table covers the given (sorted) columns.
    Returns the found index name, or None.
    """
    try:
        with app_engine.connect() as conn:
            # Get all indexes on this table
            rows = conn.execute(
                text(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='index' AND tbl_name=:tbl"
                ),
                {"tbl": table_name},
            ).fetchall()
            for (idx_name,) in rows:
                if idx_name.startswith("sqlite_"):
                    continue
                # Get index info
                info = conn.execute(
                    text(f"PRAGMA index_info({_safe_identifier(idx_name)})")
                ).fetchall()
                idx_cols = ",".join(sorted(r[2] for r in info))
                if idx_cols == columns_sorted:
                    return idx_name
        return None
    except Exception as exc:
        logger.error("Equivalent index check failed: %s", exc)
        return None


def table_column_exists(table_name: str, column_name: str) -> bool:
    """Verify that a table and column exist in the database before index creation."""
    try:
        with app_engine.connect() as conn:
            tbl_exists = conn.execute(
                text(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name=:tbl"
                ),
                {"tbl": table_name},
            ).fetchone()
            if not tbl_exists:
                return False
            cols = conn.execute(
                text(f"PRAGMA table_info({_safe_identifier(table_name)})")
            ).fetchall()
            col_names = [r[1] for r in cols]
            return column_name in col_names
    except Exception as exc:
        logger.error("table_column_exists check failed: %s", exc)
        return False


# ─────────────────────────────────────────────────────────────
# Idempotent recommendation creation
# ─────────────────────────────────────────────────────────────

def find_active_equivalent_recommendation(
    db: Session,
    identity_key: str,
) -> Optional[OptimizationModel]:
    """
    Return an existing active (pending/validated/approved) recommendation
    with the same identity key. Prevents duplicate recommendations.
    """
    return (
        db.query(OptimizationModel)
        .filter(
            OptimizationModel.index_identity_key == identity_key,
            OptimizationModel.status.in_([
                OptimizationStatus.pending,
                OptimizationStatus.validated,
                OptimizationStatus.approved,
            ]),
        )
        .first()
    )


def create_index_recommendation_idempotent(
    db: Session,
    *,
    title: str,
    proposed_sql: str,
    reasoning: str = "",
    expected_benefit: str = "",
    risks: str = "",
    original_sql: Optional[str] = None,
    incident_id: Optional[int] = None,
    db_target: str = "agenticdb_local",
) -> dict[str, Any]:
    """
    Create a new index optimization recommendation, only if:
    1. No equivalent active recommendation already exists (idempotency).
    2. The index does not already exist in the database (pre-check).

    Returns a dict with 'created', 'optimization_id', and 'reason'.
    """
    parsed = _parse_index_sql(proposed_sql)
    table_name = parsed["table_name"]
    columns = parsed["columns"]
    index_name = parsed["index_name"]

    if not table_name or not columns:
        return {
            "created": False,
            "optimization_id": None,
            "reason": f"Could not parse table/columns from proposed SQL: {proposed_sql!r}",
        }

    first_col = columns.split(",")[0].strip()
    if not table_column_exists(table_name, first_col):
        return {
            "created": False,
            "optimization_id": None,
            "reason": f"Target table '{table_name}' or column '{first_col}' does not exist in the database.",
        }

    identity_key = build_identity_key(db_target, table_name, columns)

    # 1. Check for existing equivalent active recommendation
    existing = find_active_equivalent_recommendation(db, identity_key)
    if existing:
        return {
            "created": False,
            "optimization_id": existing.id,
            "reason": (
                f"Active recommendation #{existing.id} already exists "
                f"for index on {table_name}({columns}) [status={existing.status.value}]."
            ),
        }

    # 2. Check if equivalent index already exists in DB
    existing_idx = check_equivalent_index_exists(table_name, columns)
    if existing_idx:
        # Check if we already have an existing record for this index identity key
        existing_any = (
            db.query(OptimizationModel)
            .filter(OptimizationModel.index_identity_key == identity_key)
            .first()
        )
        if existing_any:
            return {
                "created": False,
                "optimization_id": existing_any.id,
                "reason": (
                    f"Index '{existing_idx}' already exists on {table_name}({columns}) "
                    f"and is already tracked in recommendation #{existing_any.id}."
                ),
            }

        # Record as already-satisfied so it's visible in history
        opt = OptimizationModel(
            incident_id=incident_id,
            title=title,
            original_sql=original_sql,
            proposed_sql=proposed_sql,
            optimization_type="index",
            reasoning=reasoning,
            expected_benefit=expected_benefit,
            risks=risks,
            status=OptimizationStatus.applied,
            index_identity_key=identity_key,
            target_table=table_name,
            target_columns=columns,
            index_name=index_name or existing_idx,
            db_target=db_target,
            execution_status=ExecutionStatus.already_exists.value,
            execution_result=f"Index '{existing_idx}' already exists on {table_name}({columns}). Operation is already satisfied.",
            index_verified_exists=True,
        )
        db.add(opt)
        db.commit()
        db.refresh(opt)
        return {
            "created": True,
            "optimization_id": opt.id,
            "reason": f"Index already satisfied by '{existing_idx}'. Recorded as already_satisfied.",
        }

    # 3. Create new recommendation
    opt = OptimizationModel(
        incident_id=incident_id,
        title=title,
        original_sql=original_sql,
        proposed_sql=proposed_sql,
        optimization_type="index",
        reasoning=reasoning,
        expected_benefit=expected_benefit,
        risks=risks,
        status=OptimizationStatus.pending,
        index_identity_key=identity_key,
        target_table=table_name,
        target_columns=columns,
        index_name=index_name,
        db_target=db_target,
        execution_status=ExecutionStatus.not_executed.value,
    )
    db.add(opt)
    db.commit()
    db.refresh(opt)
    return {
        "created": True,
        "optimization_id": opt.id,
        "reason": "New recommendation created.",
    }


# ─────────────────────────────────────────────────────────────
# Approved execution
# ─────────────────────────────────────────────────────────────

def execute_approved_index(
    db: Session,
    optimization_id: int,
    approval_id: int,
) -> dict[str, Any]:
    """
    Execute an approved index creation operation.

    Safety gates enforced here:
    - Verify the specific approval record is in 'approved' state.
    - Verify the approval references exactly this optimization.
    - Verify table and column exist in the actual database.
    - Check if an equivalent index already exists (idempotent).
    - Use validated, quoted identifiers — never raw string injection.
    - Record execution attempt and real outcome regardless of success.
    - Never infer success from approval status alone.
    """
    result: dict[str, Any] = {
        "executed": False,
        "optimization_id": optimization_id,
        "approval_id": approval_id,
        "status": None,
        "detail": None,
        "error": None,
    }

    # Fetch optimization
    opt = db.query(OptimizationModel).filter_by(id=optimization_id).first()
    if not opt:
        result["error"] = f"Optimization #{optimization_id} not found."
        return result

    # Fetch approval
    approval = db.query(ApprovalModel).filter_by(id=approval_id).first()
    if not approval:
        result["error"] = f"Approval #{approval_id} not found."
        return result

    # Verify approval applies to this optimization
    if approval.optimization_id != optimization_id:
        result["error"] = (
            f"Approval #{approval_id} belongs to optimization "
            f"#{approval.optimization_id}, not #{optimization_id}."
        )
        return result

    # Verify approval is actually approved
    if approval.status != ApprovalStatus.approved:
        result["error"] = (
            f"Approval #{approval_id} is '{approval.status.value}', not 'approved'. "
            "Cannot execute without a valid approval."
        )
        return result

    # Only index operations are executable here
    if opt.optimization_type != "index":
        result["error"] = f"Only index operations can be executed here. Got type='{opt.optimization_type}'."
        return result

    # Parse and validate identifiers from structured fields (preferred)
    # or fall back to parsing from proposed_sql
    table_name = opt.target_table
    columns_sorted = opt.target_columns
    index_name = opt.index_name

    if not table_name or not columns_sorted or not index_name:
        parsed = _parse_index_sql(opt.proposed_sql or "")
        table_name = parsed["table_name"]
        columns_sorted = parsed["columns"]
        index_name = parsed["index_name"]

    if not table_name or not columns_sorted or not index_name:
        result["error"] = (
            "Cannot parse table/columns/index name from the optimization record. "
            "proposed_sql may be missing or malformed."
        )
        return result

    # Validate identifiers against actual DB schema
    first_col = columns_sorted.split(",")[0].strip()
    if not table_column_exists(table_name, first_col):
        result["error"] = (
            f"Table '{table_name}' or column '{first_col}' does not exist in the database. "
            "Cannot create index."
        )
        opt.execution_status = ExecutionStatus.failed.value
        opt.execution_error = result["error"]
        db.commit()
        return result

    # Mark as executing
    opt.execution_status = ExecutionStatus.executing.value
    db.commit()

    start_time = datetime.now(timezone.utc)

    # Check if equivalent index already exists
    existing_idx = check_equivalent_index_exists(table_name, columns_sorted)
    if existing_idx:
        opt.execution_status = ExecutionStatus.already_exists.value
        opt.executed_at = start_time
        opt.execution_result = (
            f"Index '{existing_idx}' already exists on {table_name}({columns_sorted}). "
            "Operation is already satisfied — no new index was created."
        )
        opt.index_verified_exists = True
        opt.status = OptimizationStatus.applied
        db.commit()
        result["executed"] = True
        result["status"] = "already_exists"
        result["detail"] = opt.execution_result
        return result

    # Build safe CREATE INDEX SQL using validated, quoted identifiers
    try:
        quoted_table = _safe_identifier(table_name)
        quoted_idx = _safe_identifier(index_name)
        # Quote each column individually
        quoted_cols = ", ".join(
            _safe_identifier(c.strip()) for c in columns_sorted.split(",")
        )
        safe_sql = (
            f"CREATE INDEX IF NOT EXISTS {quoted_idx} ON {quoted_table}({quoted_cols})"
        )
    except ValueError as ve:
        result["error"] = f"Identifier validation failed: {ve}"
        opt.execution_status = ExecutionStatus.failed.value
        opt.execution_error = result["error"]
        db.commit()
        return result

    # Execute
    try:
        with app_engine.begin() as conn:
            conn.execute(text(safe_sql))
        end_time = datetime.now(timezone.utc)

        # Verify the index was actually created
        index_now_exists = check_index_exists(index_name, table_name)

        opt.execution_status = ExecutionStatus.success.value if index_now_exists else ExecutionStatus.failed.value
        opt.executed_at = start_time
        opt.status = OptimizationStatus.applied if index_now_exists else OptimizationStatus.failed
        opt.index_verified_exists = index_now_exists
        opt.execution_result = (
            f"Index '{index_name}' created successfully on {table_name}({columns_sorted}). "
            f"Verified in database: {index_now_exists}. "
            f"Duration: {(end_time - start_time).total_seconds() * 1000:.1f}ms"
        ) if index_now_exists else (
            f"CREATE INDEX command succeeded but post-execution verification failed for '{index_name}'."
        )
        db.commit()

        result["executed"] = True
        result["status"] = "success" if index_now_exists else "verification_failed"
        result["detail"] = opt.execution_result

    except Exception as exc:
        end_time = datetime.now(timezone.utc)
        logger.error("Index creation failed for opt #%d: %s", optimization_id, exc)

        opt.execution_status = ExecutionStatus.failed.value
        opt.executed_at = start_time
        opt.execution_error = str(exc)
        opt.status = OptimizationStatus.failed
        # Approval decision is preserved — only execution failed
        db.commit()

        result["error"] = str(exc)
        result["status"] = "failed"

    return result


# ─────────────────────────────────────────────────────────────
# Reliable benchmarking
# ─────────────────────────────────────────────────────────────

def run_benchmark(
    db: Session,
    baseline_sql: str,
    candidate_sql: str,
    optimization_id: Optional[int] = None,
    name: str = "Benchmark",
    description: str = "",
    runs: int = 5,
    warmup_runs: int = 1,
) -> dict[str, Any]:
    """
    Run a before/after benchmark with warm-up, repeated runs, and validity checks.

    Requirements:
    - Both queries must execute successfully against the same database.
    - Results must be equivalent (same row count) before comparing timings.
    - Reports median, average, and individual run timings.
    - Accounts for limitations on very small datasets.
    - Does NOT fabricate improvement percentages.
    - Records which indexes existed during the run.
    """
    from app.safety.sql_validator import validate_read_only_sql, add_row_limit
    from app.models import ExperimentModel

    result: dict[str, Any] = {
        "name": name,
        "baseline_avg_ms": None,
        "candidate_avg_ms": None,
        "baseline_median_ms": None,
        "candidate_median_ms": None,
        "improvement_pct": None,
        "baseline_runs": [],
        "candidate_runs": [],
        "correctness_check": None,
        "correctness_detail": None,
        "valid": False,
        "validity_notes": [],
        "index_state_during_run": {},
        "error": None,
    }

    # Validate both queries are read-only
    try:
        clean_baseline = validate_read_only_sql(baseline_sql)
        limited_baseline = add_row_limit(clean_baseline, settings.max_query_rows)
    except Exception as exc:
        result["error"] = f"Baseline SQL validation failed: {exc}"
        return result

    try:
        clean_candidate = validate_read_only_sql(candidate_sql)
        limited_candidate = add_row_limit(clean_candidate, settings.max_query_rows)
    except Exception as exc:
        result["error"] = f"Candidate SQL validation failed: {exc}"
        return result

    # Snapshot which custom indexes exist right now
    try:
        with app_engine.connect() as conn:
            idx_rows = conn.execute(
                text("SELECT name, tbl_name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'")
            ).fetchall()
            result["index_state_during_run"] = {r[0]: r[1] for r in idx_rows}
    except Exception:
        pass

    def run_timed(sql: str, n: int, label: str) -> tuple[list[float], Optional[list]]:
        """Run SQL n times and collect timings. Returns (times, last_rows)."""
        times = []
        last_rows = None
        for i in range(n):
            t0 = time.perf_counter()
            try:
                with app_engine.connect() as conn:
                    r = conn.execute(text(sql))
                    rows = r.fetchall()
                    last_rows = rows
                elapsed = (time.perf_counter() - t0) * 1000
                times.append(round(elapsed, 3))
            except Exception as exc:
                result["validity_notes"].append(f"{label} run {i+1} failed: {exc}")
        return times, last_rows

    # Warm-up
    if warmup_runs > 0:
        run_timed(limited_baseline, warmup_runs, "baseline_warmup")
        run_timed(limited_candidate, warmup_runs, "candidate_warmup")

    # Timed runs
    baseline_times, baseline_rows = run_timed(limited_baseline, runs, "baseline")
    candidate_times, candidate_rows = run_timed(limited_candidate, runs, "candidate")

    result["baseline_runs"] = baseline_times
    result["candidate_runs"] = candidate_times

    if not baseline_times:
        result["error"] = "Baseline query produced no successful timing results."
        return result
    if not candidate_times:
        result["error"] = "Candidate query produced no successful timing results."
        return result

    # Statistics
    result["baseline_avg_ms"] = round(sum(baseline_times) / len(baseline_times), 3)
    result["candidate_avg_ms"] = round(sum(candidate_times) / len(candidate_times), 3)
    if len(baseline_times) >= 2:
        result["baseline_median_ms"] = round(statistics.median(baseline_times), 3)
    if len(candidate_times) >= 2:
        result["candidate_median_ms"] = round(statistics.median(candidate_times), 3)

    # Correctness check
    baseline_count = len(baseline_rows) if baseline_rows is not None else None
    candidate_count = len(candidate_rows) if candidate_rows is not None else None
    if baseline_count is not None and candidate_count is not None:
        result["correctness_check"] = (baseline_count == candidate_count)
        result["correctness_detail"] = (
            f"Baseline returned {baseline_count} rows; candidate returned {candidate_count} rows."
        )
        if not result["correctness_check"]:
            result["validity_notes"].append(
                "Row counts differ — queries may not be semantically equivalent. "
                "Improvement percentage is not reported for non-equivalent queries."
            )

    # Improvement calculation (only when queries are equivalent)
    baseline_avg = result["baseline_avg_ms"]
    candidate_avg = result["candidate_avg_ms"]

    if baseline_avg and baseline_avg > 0 and result["correctness_check"] is not False:
        improvement = ((baseline_avg - candidate_avg) / baseline_avg) * 100
        result["improvement_pct"] = round(improvement, 2)

        # Dataset size / timing noise warning
        if baseline_avg < 5.0:
            result["validity_notes"].append(
                f"Baseline avg {baseline_avg:.2f}ms is very small — "
                "timing noise dominates. This result is not a reliable indicator of "
                "real-world index benefit on larger datasets."
            )
        result["valid"] = True
    else:
        result["improvement_pct"] = None
        result["validity_notes"].append(
            "Improvement percentage not reported: "
            "queries are non-equivalent or baseline is zero."
        )

    # Persist experiment
    from app.models import ExperimentModel
    exp = ExperimentModel(
        optimization_id=optimization_id,
        name=name,
        description=description,
        baseline_sql=limited_baseline,
        candidate_sql=limited_candidate,
        baseline_runs=baseline_times,
        candidate_runs=candidate_times,
        baseline_avg_ms=result["baseline_avg_ms"],
        candidate_avg_ms=result["candidate_avg_ms"],
        baseline_median_ms=result.get("baseline_median_ms"),
        candidate_median_ms=result.get("candidate_median_ms"),
        improvement_pct=result["improvement_pct"],
        correctness_check=result["correctness_check"],
        correctness_detail=result["correctness_detail"],
        index_state_during_run=result["index_state_during_run"],
        verified=result["valid"],
        unverified_reason=(
            "; ".join(result["validity_notes"]) if result["validity_notes"] else None
        ),
        status="completed",
        run_at=datetime.now(timezone.utc),
    )
    db.add(exp)
    db.commit()
    db.refresh(exp)
    result["experiment_id"] = exp.id

    return result
