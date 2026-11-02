"""
Query execution service with safety controls, explain plan support, and history tracking.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.database.engine import app_engine
from app.models import QueryHistoryModel
from app.safety.sql_validator import validate_read_only_sql, add_row_limit

logger = logging.getLogger(__name__)
settings = get_settings()


def build_schema_context(tables: Optional[list[str]] = None) -> str:
    """Build a compact schema description for the LLM prompt."""
    from sqlalchemy import inspect
    insp = inspect(app_engine)
    available = insp.get_table_names()
    target = tables if tables else available

    lines = []
    for tname in target:
        if tname not in available:
            continue
        cols = insp.get_columns(tname)
        col_desc = ", ".join(f"{c['name']} ({c['type']})" for c in cols)
        lines.append(f"Table {tname}: {col_desc}")

    if not lines:
        return "No tables available."
    return "\n".join(lines)


def execute_read_only_sql(
    sql: str,
    db: Session,
    source: str = "user",
    natural_language: Optional[str] = None,
) -> dict[str, Any]:
    """
    Validate, limit, and execute a read-only SQL query.
    Records to query_history. Returns result dict.
    """
    history_entry = QueryHistoryModel(
        natural_language=natural_language,
        generated_sql=sql,
        source=source,
        status="pending",
    )

    try:
        # Safety validation
        clean_sql = validate_read_only_sql(sql)
        limited_sql = add_row_limit(clean_sql, settings.max_query_rows)
    except Exception as exc:
        history_entry.status = "rejected"
        history_entry.error_message = str(exc)
        db.add(history_entry)
        db.commit()
        return {"success": False, "error": str(exc), "sql": sql}

    # Execute
    t0 = time.perf_counter()
    try:
        with app_engine.connect() as conn:
            conn.execute(text(f"SET statement_timeout = '{settings.query_timeout_seconds * 1000}'")) if settings.is_postgres else None
            result = conn.execute(text(limited_sql))
            rows = result.fetchall()
            columns = list(result.keys())
        elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)

        # Convert to dicts
        data = [dict(zip(columns, row)) for row in rows]

        history_entry.status = "success"
        history_entry.execution_time_ms = elapsed_ms
        history_entry.row_count = len(data)
        db.add(history_entry)
        db.commit()

        return {
            "success": True,
            "sql": limited_sql,
            "columns": columns,
            "rows": data,
            "row_count": len(data),
            "execution_time_ms": elapsed_ms,
        }

    except Exception as exc:
        elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
        history_entry.status = "error"
        history_entry.error_message = str(exc)
        history_entry.execution_time_ms = elapsed_ms
        db.add(history_entry)
        db.commit()
        logger.error("Query execution error: %s", exc)
        return {
            "success": False,
            "error": str(exc),
            "sql": limited_sql,
            "execution_time_ms": elapsed_ms,
        }


def explain_sql(sql: str) -> dict[str, Any]:
    """
    Run EXPLAIN (not EXPLAIN ANALYZE) on a query and return the plan.
    Safe: does not execute the query body.
    """
    try:
        clean_sql = validate_read_only_sql(sql)
    except Exception as exc:
        return {"success": False, "error": str(exc)}

    if settings.is_postgres:
        explain_stmt = f"EXPLAIN (FORMAT JSON) {clean_sql}"
    else:
        explain_stmt = f"EXPLAIN QUERY PLAN {clean_sql}"

    try:
        with app_engine.connect() as conn:
            result = conn.execute(text(explain_stmt))
            plan_rows = result.fetchall()

        if settings.is_postgres:
            import json
            plan = json.loads(plan_rows[0][0]) if plan_rows else []
        else:
            plan = [dict(zip(result.keys(), r)) for r in plan_rows]

        return {"success": True, "plan": plan, "dialect": "postgresql" if settings.is_postgres else "sqlite"}
    except Exception as exc:
        logger.error("EXPLAIN error: %s", exc)
        return {"success": False, "error": str(exc)}


def analyze_query_performance(sql: str) -> dict[str, Any]:
    """
    Deterministic rule-based query performance analysis without executing the query body.
    Supplements LLM-based suggestions.
    """
    sql_upper = sql.upper()
    issues = []
    suggestions = []

    if "SELECT *" in sql_upper:
        issues.append("SELECT * fetches all columns - specify only needed columns to reduce I/O.")
        suggestions.append({
            "type": "rewrite",
            "title": "Replace SELECT *",
            "description": "Specify exact columns needed instead of SELECT *",
            "impact": "medium",
        })

    if "LIKE '%" in sql_upper:
        issues.append("Leading wildcard LIKE '%...' cannot use indexes - consider full-text search.")
        suggestions.append({
            "type": "index",
            "title": "Avoid leading wildcard in LIKE",
            "description": "A leading % prevents index use. Consider prefix matching or full-text search.",
            "impact": "high",
        })

    if "OR " in sql_upper and "WHERE" in sql_upper:
        issues.append("OR in WHERE clause may prevent index use - consider UNION ALL.")
        suggestions.append({
            "type": "rewrite",
            "title": "OR to UNION ALL",
            "description": "Rewrite OR conditions as UNION ALL to allow index seeks on each branch.",
            "impact": "medium",
        })

    if "NOT IN" in sql_upper:
        issues.append("NOT IN with subquery can be slow on large sets - consider NOT EXISTS.")
        suggestions.append({
            "type": "rewrite",
            "title": "NOT IN to NOT EXISTS",
            "description": "NOT EXISTS often performs better than NOT IN with subqueries.",
            "impact": "medium",
        })

    if "ORDER BY" in sql_upper and "LIMIT" not in sql_upper:
        issues.append("ORDER BY without LIMIT sorts the full result set.")
        suggestions.append({
            "type": "rewrite",
            "title": "Add LIMIT to ORDER BY",
            "description": "If only top-N results are needed, add LIMIT to avoid full sort.",
            "impact": "low",
        })

    return {
        "issues": issues,
        "suggestions": suggestions,
        "issue_count": len(issues),
    }
