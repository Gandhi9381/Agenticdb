# AgenticDB REST API Specification

The AgenticDB API is implemented in FastAPI and automatically serves interactive Swagger UI documentation at `/docs` and ReDoc at `/redoc`.

Base URL: `http://localhost:8000/api`

---

## Endpoints Summary

### System & Health
- `GET /api/health` — System status, LLM availability, background monitor state.
- `GET /api/databases` — Connected database metadata and registered tables.
- `GET /api/dashboard/summary` — Aggregate statistics (queries, incidents, optimizations, improvements).

### Datasets & Schema
- `POST /api/datasets/upload` — Multipart CSV upload; converts file to SQL table with automatic schema inference.
- `POST /api/datasets/load-sample?rows=1000` — Generates and loads synthetic retail tables (`customers`, `products`, `orders`, `order_items`).
- `GET /api/tables` — Lists all user tables with row counts and source flags.
- `GET /api/tables/{name}/schema` — Column definitions, data types, nullability, and primary keys.
- `GET /api/tables/{name}/preview?limit=50` — Sample data rows for UI preview.

### Query Assistant & History
- `POST /api/query/generate` — Text-to-SQL generation with schema grounding and query history context.
- `POST /api/query/execute` — Safe, read-only SQL execution with latency tracking, row limiting, and history logging.
- `POST /api/query/explain` — Generates query execution plan (`EXPLAIN QUERY PLAN` or PostgreSQL `EXPLAIN (ANALYZE, BUFFERS)`).
- `GET /api/queries/history?limit=50` — Retrieves past query logs with latency, row counts, and status.

### Performance & Incidents
- `GET /api/performance/summary` — P50, P95, P99 latencies, total query volume, error rates.
- `GET /api/performance/slow-queries` — Queries exceeding `SLOW_QUERY_THRESHOLD_MS`.
- `GET /api/incidents?status=open` — List performance incidents.
- `GET /api/incidents/{id}` — Incident details, root cause, evidence metrics, and agent logs.
- `POST /api/incidents/{id}/diagnose` — Triggers LangGraph autonomous diagnosis workflow for an incident.

### Optimizations & Approvals
- `GET /api/optimizations` — List candidate optimizations (indexes, rewrites).
- `GET /api/optimizations/{id}` — Detailed recommendation, reasoning, risk assessment, and benchmark results.
- `POST /api/optimizations/{id}/request-approval` — Submits candidate for human operator review.
- `GET /api/approvals` — List pending, approved, and rejected approvals.
- `POST /api/approvals/{id}/approve?note=...` — Operator approves candidate; executes migration.
- `POST /api/approvals/{id}/reject?note=...` — Operator rejects candidate with explanation.

### Monitoring & Experiments
- `GET /api/monitoring/status` — Current status of APScheduler monitoring worker.
- `POST /api/monitoring/start` — Starts autonomous monitoring.
- `POST /api/monitoring/stop` — Halts monitoring.
- `POST /api/monitoring/run-cycle` — Manually triggers an immediate monitoring cycle.
- `GET /api/experiments` — List empirical verification benchmarks.
- `POST /api/experiments/run` — Executes a 5-run benchmark test comparing baseline vs optimized query.
