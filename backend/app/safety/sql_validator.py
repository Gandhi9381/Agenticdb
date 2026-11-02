"""
SQL safety layer: parsing, permission enforcement, injection prevention.
"""
from __future__ import annotations

import logging
import re
from typing import Any

import sqlglot
import sqlglot.expressions as exp

logger = logging.getLogger(__name__)

# SQL statements that are explicitly allowed for the NL Query assistant
ALLOWED_STATEMENT_TYPES = {"select"}

# Forbidden clauses/keywords even inside SELECT
FORBIDDEN_PATTERNS = [
    r"\bINTO\s+OUTFILE\b",
    r"\bLOAD\s+DATA\b",
    r"\bEXEC(UTE)?\b",
    r"\bXP_\w+\b",
    r"\bINFORMATION_SCHEMA\b",
    r"\bSYS\.\b",
    r"\bPG_READ_FILE\b",
    r"\bPG_WRITE_FILE\b",
    r"--",          # SQL comments (possible injection)
    r"/\*.*\*/",    # Block comments
]


class SQLValidationError(ValueError):
    """Raised when SQL fails the safety check."""
    pass


def validate_read_only_sql(sql: str) -> str:
    """
    Parse and validate that sql is a single, safe SELECT statement.
    Returns the canonical (stripped) SQL, or raises SQLValidationError.
    """
    sql = sql.strip().rstrip(";")

    # Check forbidden patterns first
    upper = sql.upper()
    for pattern in FORBIDDEN_PATTERNS:
        if re.search(pattern, upper, re.IGNORECASE):
            raise SQLValidationError(f"Forbidden SQL pattern detected: {pattern}")

    # Parse with sqlglot
    try:
        statements = sqlglot.parse(sql)
    except Exception as exc:
        raise SQLValidationError(f"SQL parse error: {exc}") from exc

    if len(statements) != 1:
        raise SQLValidationError(
            f"Only a single SQL statement is allowed; received {len(statements)}."
        )

    stmt = statements[0]
    if stmt is None:
        raise SQLValidationError("Empty SQL statement.")

    # Must be SELECT
    stmt_type = type(stmt).__name__.lower()
    if stmt_type not in ALLOWED_STATEMENT_TYPES:
        raise SQLValidationError(
            f"Only SELECT queries are permitted through this interface. "
            f"Received statement type: {stmt_type.upper()}."
        )

    # No subquery writes (INSERT INTO ... SELECT)
    for node in stmt.walk():
        if isinstance(node, (exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create)):
            raise SQLValidationError(
                "Nested write operations are not permitted in read-only queries."
            )

    return sql


def add_row_limit(sql: str, max_rows: int = 10_000) -> str:
    """Ensure the query has a LIMIT clause not exceeding max_rows."""
    match = re.search(r"\bLIMIT\s+(\d+)\b", sql, re.IGNORECASE)
    if match:
        val = int(match.group(1))
        if val > max_rows:
            return re.sub(r"\bLIMIT\s+\d+\b", f"LIMIT {max_rows}", sql, count=1, flags=re.IGNORECASE)
        return sql
    if not re.search(r"\bLIMIT\b", sql, re.IGNORECASE):
        clean_sql = sql.rstrip("; \t\n")
        return f"{clean_sql} LIMIT {max_rows}"
    return sql


def extract_sql_from_llm_response(text: str) -> str:
    """
    Extract SQL from LLM response which may include markdown code fences.
    """
    # Try ```sql ... ``` block
    match = re.search(r"```(?:sql)?\s*\n?(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()

    # Try to find first SELECT statement
    match = re.search(r"(SELECT\s.+?)(?:;|$)", text, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()

    return text.strip()


def detect_action_class(sql: str) -> str:
    """
    Determine safety action class for a SQL statement.
    A = read-only
    B = plan/test only
    C = persistent change (requires approval)
    """
    upper = sql.strip().upper()
    if upper.startswith("SELECT") or upper.startswith("EXPLAIN"):
        return "A"
    if any(upper.startswith(w) for w in ["CREATE INDEX", "DROP INDEX"]):
        return "C"
    if any(upper.startswith(w) for w in ["CREATE", "DROP", "ALTER", "TRUNCATE", "DELETE", "UPDATE", "INSERT"]):
        return "C"
    return "B"
