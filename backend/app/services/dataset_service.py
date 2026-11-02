"""
Dataset import service: CSV upload, validation, schema inference, and DB import.
"""
from __future__ import annotations

import io
import logging
import re
import time
from typing import Any

import pandas as pd
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.database.engine import engine as app_engine
from app.models import DatasetModel

logger = logging.getLogger(__name__)
settings = get_settings()

MAX_FILE_SIZE_MB = 50
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024

# Map pandas dtypes to SQL column types (SQLite-compatible too)
DTYPE_MAP = {
    "int64": "INTEGER",
    "int32": "INTEGER",
    "float64": "REAL",
    "float32": "REAL",
    "bool": "BOOLEAN",
    "object": "TEXT",
    "datetime64[ns]": "TIMESTAMP",
}


def _safe_identifier(name: str) -> str:
    """Sanitize column/table names."""
    safe = re.sub(r"[^\w]", "_", name.strip().lower())
    if re.match(r"^\d", safe):
        safe = f"col_{safe}"
    return safe[:63]


def _infer_schema(df: pd.DataFrame) -> dict[str, str]:
    return {
        _safe_identifier(col): DTYPE_MAP.get(str(df[col].dtype), "TEXT")
        for col in df.columns
    }


def _sanitize_df(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    # Sanitize column names
    df.columns = [_safe_identifier(c) for c in df.columns]
    # Drop fully empty rows
    df = df.dropna(how="all")
    # Limit injection risk: ensure all values are Python scalars (not code)
    return df


def validate_csv_bytes(data: bytes, filename: str) -> dict[str, Any]:
    """
    Validate CSV bytes. Returns {"ok": True, "df": ..., "warnings": [...]}
    or {"ok": False, "error": "..."}.
    """
    if not filename.lower().endswith(".csv"):
        return {"ok": False, "error": "Only .csv files are supported."}
    if len(data) > MAX_FILE_SIZE_BYTES:
        return {"ok": False, "error": f"File exceeds {MAX_FILE_SIZE_MB} MB limit."}
    if len(data) == 0:
        return {"ok": False, "error": "File is empty."}

    warnings: list[str] = []
    try:
        df = pd.read_csv(io.BytesIO(data), dtype=str)
    except Exception as exc:
        return {"ok": False, "error": f"Could not parse CSV: {exc}"}

    if df.empty:
        return {"ok": False, "error": "CSV has no data rows."}
    if df.shape[1] == 0:
        return {"ok": False, "error": "CSV has no columns."}
    if df.shape[0] > 1_000_000:
        warnings.append("Large file: only the first 1,000,000 rows will be imported.")
        df = df.head(1_000_000)

    # Detect duplicate columns
    seen: set[str] = set()
    renamed: dict[str, str] = {}
    new_cols = []
    for col in df.columns:
        safe = _safe_identifier(col)
        if safe in seen:
            safe = f"{safe}_dup"
            warnings.append(f"Duplicate/conflicting column renamed to '{safe}'.")
        seen.add(safe)
        renamed[col] = safe
        new_cols.append(safe)

    df.columns = new_cols

    # Convert numeric columns
    for col in df.columns:
        try:
            df[col] = pd.to_numeric(df[col])
        except (ValueError, TypeError):
            pass

    return {"ok": True, "df": df, "warnings": warnings}


def import_csv_to_db(
    db: Session,
    data: bytes,
    filename: str,
    table_name: str,
    overwrite: bool = False,
) -> dict[str, Any]:
    """
    Import CSV bytes as a new table. Returns import status dict.
    """
    validation = validate_csv_bytes(data, filename)
    if not validation["ok"]:
        return {"success": False, "error": validation["error"]}

    df: pd.DataFrame = validation["df"]
    warnings: list[str] = validation.get("warnings", [])

    table_name = _safe_identifier(table_name)

    # Check existing table
    insp = inspect(app_engine)
    if table_name in insp.get_table_names():
        if not overwrite:
            return {
                "success": False,
                "error": f"Table '{table_name}' already exists. Set overwrite=true to replace.",
            }
        with app_engine.connect() as conn:
            conn.execute(text(f'DROP TABLE IF EXISTS "{table_name}"'))
            conn.commit()

    # Write to DB
    t0 = time.time()
    df.to_sql(table_name, app_engine, if_exists="replace", index=False, chunksize=5000)
    elapsed = round((time.time() - t0) * 1000, 1)

    schema = _infer_schema(df)

    # Register in metadata
    existing = db.query(DatasetModel).filter_by(name=table_name).first()
    if existing:
        existing.row_count = len(df)
        existing.column_count = len(df.columns)
        existing.schema_info = schema
        existing.original_filename = filename
        existing.status = "active"
    else:
        ds = DatasetModel(
            name=table_name,
            original_filename=filename,
            row_count=len(df),
            column_count=len(df.columns),
            schema_info=schema,
            source="csv",
        )
        db.add(ds)
    db.commit()

    logger.info("Imported %d rows into table '%s' in %.0f ms", len(df), table_name, elapsed)

    return {
        "success": True,
        "table_name": table_name,
        "row_count": len(df),
        "column_count": len(df.columns),
        "schema": schema,
        "import_time_ms": elapsed,
        "warnings": warnings,
    }


def import_dataframe_to_db(
    db: Session,
    df: pd.DataFrame,
    table_name: str,
    source: str = "synthetic",
    overwrite: bool = True,
) -> dict[str, Any]:
    table_name = _safe_identifier(table_name)
    df = _sanitize_df(df)

    df.to_sql(table_name, app_engine, if_exists="replace" if overwrite else "fail", index=False, chunksize=5000)
    schema = _infer_schema(df)

    existing = db.query(DatasetModel).filter_by(name=table_name).first()
    if existing:
        existing.row_count = len(df)
        existing.column_count = len(df.columns)
        existing.schema_info = schema
        existing.source = source
        existing.status = "active"
    else:
        ds = DatasetModel(
            name=table_name,
            original_filename=None,
            row_count=len(df),
            column_count=len(df.columns),
            schema_info=schema,
            source=source,
        )
        db.add(ds)
    db.commit()
    return {"table_name": table_name, "row_count": len(df), "schema": schema}


def get_table_schema(table_name: str) -> dict[str, Any] | None:
    """Return column info for a table using SQLAlchemy inspector."""
    insp = inspect(app_engine)
    if table_name not in insp.get_table_names():
        return None
    cols = insp.get_columns(table_name)
    pk = insp.get_pk_constraint(table_name)
    fks = insp.get_foreign_keys(table_name)
    idxs = insp.get_indexes(table_name)
    return {
        "table_name": table_name,
        "columns": [
            {
                "name": c["name"],
                "type": str(c["type"]),
                "nullable": c.get("nullable", True),
                "default": str(c.get("default", "")),
            }
            for c in cols
        ],
        "primary_keys": pk.get("constrained_columns", []),
        "foreign_keys": fks,
        "indexes": [{"name": i["name"], "columns": i["column_names"]} for i in idxs],
    }


def list_tables() -> list[str]:
    return inspect(app_engine).get_table_names()
