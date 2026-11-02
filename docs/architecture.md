# AgenticDB Architecture & System Design

## 1. System Overview

AgenticDB is an autonomous AI Database Administrator (DBA) designed to operate alongside production or analytical relational databases (PostgreSQL and SQLite). It continuously observes database telemetry, detects performance degradation anomalies, conducts deep root cause analysis, generates actionable optimizations (query rewrites, index recommendations, statistics refresh), enforces human-in-the-loop safety boundaries, and empirically validates performance gains via isolated benchmarking.

```
┌────────────────────────────────────────────────────────────────────────┐
│                             REACT FRONTEND                             │
│       Vite + TypeScript + Recharts + Lucide Icons + Dark Theme UI       │
│  (Dashboard, Datasets, Schema, Query Assistant, Incidents, Approvals)   │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ REST / JSON
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                           FASTAPI BACKEND                              │
│                                                                        │
│  ┌───────────────────┐  ┌──────────────────────┐  ┌─────────────────┐  │
│  │   Query Service   │  │   Monitoring Engine  │  │ Safety Validator│  │
│  │ (Read-only exec,  │  │ (APScheduler, P95/P99│  │ (AST parsing,   │  │
│  │  EXPLAIN plans)   │  │  latency, anomalies) │  │  Action A/B/C)  │  │
│  └─────────┬─────────┘  └──────────┬───────────┘  └────────┬────────┘  │
│            │                       │                       │           │
│  ┌─────────▼───────────────────────▼───────────────────────▼────────┐  │
│  │                   LANGGRAPH AGENT WORKFLOW                       │  │
│  │                                                                  │  │
│  │   [Anomaly] ──> [Root Cause] ──> [Optimizer] ──> [Safety Check]  │  │
│  │                                                        │         │  │
│  │       [Performance Verification] <── [Human Approval] <┘         │  │
│  └─────────────────────────────────┬────────────────────────────────┘  │
│                                    │                                   │
│  ┌─────────────────────────────────▼────────────────────────────────┐  │
│  │                         LLM SERVICE                              │  │
│  │    Gemini 2.0 Flash / OpenAI / Anthropic / Local Fallback Heuristic│
│  └──────────────────────────────────────────────────────────────────┘  │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                        DATABASE LAYER (SQLAlchemy)                     │
│  • Primary Database: SQLite (agenticdb.db) / PostgreSQL (production)  │
│  • Metadata Tables: datasets, query_history, incidents, optimizations, │
│                     approvals, experiments, monitoring_metrics         │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Agentic Workflow Engine (LangGraph)

AgenticDB implements an asynchronous, stateful agent graph powered by **LangGraph**:

1. **`detect_anomaly_node`**:
   - Compares query execution metrics against baseline SLAs (e.g., P95 latency > 500ms or 3x historical mean).
   - Generates or updates incident tickets in the `incidents` table.

2. **`diagnose_root_cause_node`**:
   - Inspects `EXPLAIN / EXPLAIN QUERY PLAN` outputs.
   - Identifies sequential table scans, missing composite keys, Cartesian cross-products, unindexed foreign key lookups, and missing statistics.

3. **`generate_optimization_node`**:
   - Synthesizes candidate optimizations:
     - **Index creation**: e.g., `CREATE INDEX idx_orders_customer_id ON orders(customer_id);`
     - **Query rewrites**: e.g., converting correlated subqueries to `JOIN` or adding pagination.
     - **Maintenance operations**: `ANALYZE` or `VACUUM`.
   - Generates rollback strategies and risk assessments for each candidate.

4. **`safety_check_node`**:
   - Categorizes each recommendation into Action Classes **A**, **B**, or **C**.
   - Evaluates whether human approval is required before execution.

5. **`approval_gate_node`**:
   - If Action Class is C (persistent schema or state changes): flags status as `pending_approval` and logs an entry in `approvals`.
   - Halts autonomous execution until an operator confirms or rejects the change in the UI.

6. **`verify_performance_node`**:
   - Runs baseline queries and candidate queries 5 times in an isolated environment.
   - Calculates mean execution time, P95 latency, and speedup factor.
   - Verifies semantic output equivalence (checksum & row count matching).

---

## 3. Autonomous Monitoring Service

AgenticDB features an autonomous background monitor (`APScheduler`):
- Runs at configurable intervals (`MONITOR_INTERVAL_SECONDS`, default 30s).
- Gathers database connection metrics, memory metrics, and query execution times.
- Auto-detects anomalies in real time without human intervention.
- Can be started, stopped, or manually triggered via `/api/monitoring/*` endpoints or the UI dashboard.
