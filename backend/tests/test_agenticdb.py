"""
AgenticDB test suite.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.database.engine import init_db
from app.safety.sql_validator import validate_read_only_sql, SQLValidationError, add_row_limit
from app.services.data_generator import generate_all
from app.services.dataset_service import validate_csv_bytes

# Initialize database schema for tests
init_db()

client = TestClient(app)


# ─── Health ──────────────────────────────────────────────────
def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


# ─── SQL Validator ────────────────────────────────────────────
def test_valid_select():
    sql = validate_read_only_sql("SELECT id, name FROM customers WHERE id = 1")
    assert "SELECT" in sql.upper()


def test_reject_drop():
    with pytest.raises(SQLValidationError):
        validate_read_only_sql("DROP TABLE customers")


def test_reject_insert():
    with pytest.raises(SQLValidationError):
        validate_read_only_sql("INSERT INTO customers VALUES (1, 'a')")


def test_reject_multiple_statements():
    with pytest.raises(SQLValidationError):
        validate_read_only_sql("SELECT 1; DROP TABLE customers")


def test_reject_load_data():
    with pytest.raises(SQLValidationError):
        validate_read_only_sql("SELECT 1; LOAD DATA INFILE '/etc/passwd'")


def test_add_row_limit():
    sql = add_row_limit("SELECT * FROM customers", 100)
    assert "100" in sql or "LIMIT" in sql.upper()


def test_limit_respected():
    sql = add_row_limit("SELECT * FROM customers LIMIT 50000", 10000)
    assert "50000" not in sql


# ─── Data Generator ───────────────────────────────────────────
def test_generate_retail_data():
    tables = generate_all(rows=100, seed=1)
    assert "customers" in tables
    assert "products" in tables
    assert "orders" in tables
    assert "order_items" in tables
    assert len(tables["customers"]) > 0
    assert len(tables["order_items"]) > 0


def test_data_reproducible():
    t1 = generate_all(rows=100, seed=42)
    t2 = generate_all(rows=100, seed=42)
    assert list(t1["customers"]["customer_id"]) == list(t2["customers"]["customer_id"])


# ─── CSV Validation ───────────────────────────────────────────
def test_valid_csv():
    csv = b"name,age,city\nAlice,30,Mumbai\nBob,25,Delhi\n"
    r = validate_csv_bytes(csv, "test.csv")
    assert r["ok"]
    assert len(r["df"]) == 2


def test_invalid_extension():
    r = validate_csv_bytes(b"data", "file.xlsx")
    assert not r["ok"]
    assert "csv" in r["error"].lower()


def test_empty_csv():
    r = validate_csv_bytes(b"", "empty.csv")
    assert not r["ok"]


def test_csv_no_data_rows():
    r = validate_csv_bytes(b"col1,col2\n", "headers_only.csv")
    assert not r["ok"]


# ─── API: Tables ─────────────────────────────────────────────
def test_get_tables():
    r = client.get("/api/tables")
    assert r.status_code == 200
    assert "tables" in r.json()


def test_dashboard():
    r = client.get("/api/dashboard/summary")
    assert r.status_code == 200
    data = r.json()
    assert "total_queries" in data
    assert "open_incidents" in data


# ─── API: Incidents ───────────────────────────────────────────
def test_list_incidents():
    r = client.get("/api/incidents")
    assert r.status_code == 200
    assert "incidents" in r.json()


# ─── API: Monitoring ─────────────────────────────────────────
def test_monitoring_status():
    r = client.get("/api/monitoring/status")
    assert r.status_code == 200
    assert "active" in r.json()


# ─── API: Query Execute ───────────────────────────────────────
def test_execute_select_1():
    r = client.post("/api/query/execute", json={"sql": "SELECT 1 AS val"})
    # Should succeed or fail gracefully
    assert r.status_code in (200, 400)


def test_reject_dangerous_sql():
    r = client.post("/api/query/execute", json={"sql": "DROP TABLE IF EXISTS customers"})
    assert r.status_code == 400
