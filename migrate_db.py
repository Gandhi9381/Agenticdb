"""
Safe backward-compatible migration for AgenticDB SQLite database.
Adds new columns to the 'optimizations', 'experiments', and 'approvals' tables.
Preserves all existing rows, statuses, IDs, timestamps, and decisions.
Also back-fills index_identity_key and execution_status for existing records.
"""
import sqlite3
import os
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("migration")

# Locate the active backend database (same path as resolved_database_url)
_backend_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend")
DB_PATH = os.path.join(_backend_dir, "agenticdb.db")


def column_exists(cur: sqlite3.Cursor, table: str, column: str) -> bool:
    cur.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cur.fetchall())


def add_column_if_missing(cur: sqlite3.Cursor, table: str, column: str, typedef: str) -> bool:
    if not column_exists(cur, table, column):
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {typedef}")
        logger.info("  Added column %s.%s", table, column)
        return True
    return False


def run_migration():
    if not os.path.exists(DB_PATH):
        logger.error("Database not found: %s", DB_PATH)
        return

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    logger.info("Running migration on: %s", DB_PATH)

    # ── optimizations table ───────────────────────────────────
    opt_cols = [
        ("index_identity_key",    "TEXT"),
        ("target_table",          "TEXT"),
        ("target_columns",        "TEXT"),
        ("index_name",            "TEXT"),
        ("db_target",             "TEXT DEFAULT 'agenticdb_local'"),
        ("execution_status",      "TEXT DEFAULT 'not_executed'"),
        ("executed_at",           "DATETIME"),
        ("execution_result",      "TEXT"),
        ("execution_error",       "TEXT"),
        ("index_verified_exists", "INTEGER"),   # SQLite bool as int
        ("benchmark_verified",    "INTEGER DEFAULT 0"),
        ("benchmark_note",        "TEXT"),
    ]
    for col, typedef in opt_cols:
        add_column_if_missing(cur, "optimizations", col, typedef)

    # ── Back-fill execution_status for existing rows ──────────
    # Approved rows that were NOT executed should stay "not_executed";
    # they should NOT be marked "success" just because they are approved.
    cur.execute(
        "UPDATE optimizations SET execution_status = 'not_executed' "
        "WHERE execution_status IS NULL"
    )

    # ── Back-fill index_identity_key for existing index rows ──
    cur.execute(
        "SELECT id, optimization_type, proposed_sql, title FROM optimizations"
    )
    for row in cur.fetchall():
        opt_id, opt_type, proposed_sql, title = row
        if opt_type != "index":
            continue
        # Parse table/column from proposed_sql or title
        table_name = None
        col_name = None
        if proposed_sql:
            import re
            # Match: CREATE INDEX ... ON <table>(<col>)
            m = re.search(
                r"ON\s+(\w+)\s*\(\s*([^)]+)\s*\)",
                proposed_sql,
                re.IGNORECASE,
            )
            if m:
                table_name = m.group(1).strip()
                col_name = ",".join(
                    sorted(c.strip() for c in m.group(2).split(","))
                )
        if not table_name and title:
            m = re.search(r"on\s+(\w+)\((\w+)\)", title, re.IGNORECASE)
            if m:
                table_name = m.group(1).strip()
                col_name = m.group(2).strip()

        if table_name and col_name:
            identity_key = f"agenticdb_local::{table_name}::{col_name}"
            # Extract index name from proposed_sql
            idx_name = None
            if proposed_sql:
                m2 = re.search(
                    r"CREATE\s+INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)\s+ON",
                    proposed_sql,
                    re.IGNORECASE,
                )
                if m2:
                    idx_name = m2.group(1)
            cur.execute(
                "UPDATE optimizations SET "
                "index_identity_key=?, target_table=?, target_columns=?, "
                "index_name=?, db_target='agenticdb_local' "
                "WHERE id=? AND index_identity_key IS NULL",
                (identity_key, table_name, col_name, idx_name, opt_id),
            )

    # ── experiments table ─────────────────────────────────────
    exp_cols = [
        ("baseline_median_ms",       "REAL"),
        ("candidate_median_ms",      "REAL"),
        ("index_state_during_run",   "TEXT"),
        ("verified",                 "INTEGER DEFAULT 0"),
        ("unverified_reason",        "TEXT"),
    ]
    for col, typedef in exp_cols:
        add_column_if_missing(cur, "experiments", col, typedef)

    # Mark existing experiments as unverified (per spec: old results are unverified)
    cur.execute(
        "UPDATE experiments SET verified=0, "
        "unverified_reason='Historical result — index state and query equivalence not verified' "
        "WHERE verified IS NULL"
    )

    conn.commit()
    conn.close()
    logger.info("Migration complete. All existing data preserved.")


if __name__ == "__main__":
    run_migration()
