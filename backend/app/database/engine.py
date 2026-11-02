"""
Database engine, session factory, and base model.
Supports SQLite (default/development) and PostgreSQL (production/monitoring).
"""
from __future__ import annotations

import logging
import re
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

# ─── SQLAlchemy Engine ────────────────────────────────────────
connect_args = {}
db_url = settings.resolved_database_url
if db_url.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(
    db_url,
    connect_args=connect_args,
    pool_pre_ping=True,
    echo=settings.debug,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


# ─── FastAPI dependency ───────────────────────────────────────
def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def get_db_context() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _run_column_migrations() -> None:
    """
    Add new columns to existing tables without touching any existing data.
    Idempotent: safe to call on every startup.
    """
    new_columns = {
        "optimizations": [
            ("index_identity_key",    "TEXT"),
            ("target_table",          "TEXT"),
            ("target_columns",        "TEXT"),
            ("index_name",            "TEXT"),
            ("db_target",             "TEXT DEFAULT 'agenticdb_local'"),
            ("execution_status",      "TEXT DEFAULT 'not_executed'"),
            ("executed_at",           "DATETIME"),
            ("execution_result",      "TEXT"),
            ("execution_error",       "TEXT"),
            ("index_verified_exists", "INTEGER"),
            ("benchmark_verified",    "INTEGER DEFAULT 0"),
            ("benchmark_note",        "TEXT"),
        ],
        "experiments": [
            ("baseline_median_ms",      "REAL"),
            ("candidate_median_ms",     "REAL"),
            ("index_state_during_run",  "TEXT"),
            ("verified",                "INTEGER DEFAULT 0"),
            ("unverified_reason",       "TEXT"),
        ],
    }

    if not settings.resolved_database_url.startswith("sqlite"):
        return  # Postgres handles schema differently

    try:
        import sqlite3
        db_path = settings.resolved_database_url.replace("sqlite:///", "")
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()

        for table, columns in new_columns.items():
            for col_name, typedef in columns:
                cur.execute(f"PRAGMA table_info({table})")
                existing = [row[1] for row in cur.fetchall()]
                if col_name not in existing:
                    try:
                        cur.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {typedef}")
                        logger.info("Migration: added column %s.%s", table, col_name)
                    except Exception as exc:
                        logger.warning("Migration skipped %s.%s: %s", table, col_name, exc)

        # Back-fill execution_status for existing rows
        cur.execute(
            "UPDATE optimizations SET execution_status='not_executed' "
            "WHERE execution_status IS NULL"
        )

        # Back-fill index_identity_key for existing index recommendations
        cur.execute(
            "SELECT id, optimization_type, proposed_sql, title "
            "FROM optimizations WHERE index_identity_key IS NULL"
        )
        for row in cur.fetchall():
            opt_id, opt_type, proposed_sql, title = row
            if opt_type != "index":
                continue
            table_name = None
            col_name = None
            if proposed_sql:
                m = re.search(
                    r"ON\s+(\w+)\s*\(\s*([^)]+)\s*\)",
                    proposed_sql,
                    re.IGNORECASE,
                )
                if m:
                    table_name = m.group(1).strip()
                    col_name = ",".join(sorted(c.strip() for c in m.group(2).split(",")))
            if not table_name and title:
                m2 = re.search(r"on\s+(\w+)\((\w+)\)", title, re.IGNORECASE)
                if m2:
                    table_name = m2.group(1).strip()
                    col_name = m2.group(2).strip()
            if table_name and col_name:
                identity_key = f"agenticdb_local::{table_name}::{col_name}"
                idx_name = None
                if proposed_sql:
                    m3 = re.search(
                        r"CREATE\s+INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)\s+ON",
                        proposed_sql,
                        re.IGNORECASE,
                    )
                    if m3:
                        idx_name = m3.group(1)
                cur.execute(
                    "UPDATE optimizations SET "
                    "index_identity_key=?, target_table=?, target_columns=?, "
                    "index_name=?, db_target='agenticdb_local' "
                    "WHERE id=? AND index_identity_key IS NULL",
                    (identity_key, table_name, col_name, idx_name, opt_id),
                )

        # Mark existing experiments as unverified (historical results)
        cur.execute(
            "UPDATE experiments SET verified=0, "
            "unverified_reason='Historical result — index state and query equivalence not verified' "
            "WHERE verified IS NULL"
        )

        conn.commit()
        conn.close()
        logger.info("Column migrations complete.")
    except Exception as exc:
        logger.error("Column migration error (non-fatal): %s", exc)


def init_db() -> None:
    """Create all tables and run safe column-addition migrations. Called at startup."""
    from app.models import (  # noqa: F401
        dataset, incident, query_history, optimization, experiment, monitoring_metric
    )
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables created/verified.")
    _run_column_migrations()


# Alias for backward compatibility with service imports
app_engine = engine


def get_monitored_engine():
    """Return a separate engine for the monitored user database."""
    url = settings.monitored_database_url or settings.resolved_database_url
    if url.startswith("sqlite"):
        args = {"check_same_thread": False}
    else:
        args = {}
    return create_engine(url, connect_args=args, pool_pre_ping=True)
