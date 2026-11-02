# AgenticDB: An Autonomous AI Database Administrator for Query Optimization, Index Tuning, and Incident Management

<p align="center">
  <strong>Autonomous database observability, proactive index recommendations, AST-guarded query assistance, and empirical performance verification powered by LangGraph.</strong>
</p>

---

## 🌟 Overview

**AgenticDB** is a production-grade, full-stack Autonomous AI Database Administrator (DBA). Rather than acting simply as a passive dashboard or a basic chatbot, AgenticDB actively observes relational database workloads, detects latency spikes and sequential scan bottlenecks, conducts deep root cause analysis using query plans, generates verified optimization plans, and protects production stability through strict human-in-the-loop safety boundaries.

### Core Capabilities:
- ⚡ **Autonomous Telemetry & Anomaly Detection**: Built-in background engine (`APScheduler`) continuously monitors query latencies, detects P95 SLA breaches, and flags degrading queries.
- 🧠 **LangGraph Multi-Step Reasoning**: Stateful agentic workflow (`Anomaly` → `Root Cause` → `Optimization` → `Safety Check` → `Human Gate` → `Empirical Verification`).
- 💬 **AI Query Assistant (Text-to-SQL)**: Grounded in live database schemas, with instant `EXPLAIN` visualization, row limiting, and execution sandboxing.
- 📁 **Instant Dataset Ingestion**: Drag-and-drop CSV upload with automatic data type inference and table creation.
- 🛡️ **Zero-Trust Safety Framework**: AST parsing via `sqlglot`, strict read-only execution sandboxing, row count clamping, and Action Classes (**A**: Read-only, **B**: Test, **C**: Persistent change).
- 🧑‍⚖️ **Human-in-the-Loop Approval Gates**: Dangerous or persistent changes (e.g. `CREATE INDEX`, `DROP INDEX`) are held until reviewed by an operator, with automated rollback SQL scripts.
- 🔬 **Empirical Verification Benchmarks**: Measures 5 runs of baseline vs candidate queries in isolated environments, demonstrating up to **16.2× speedups** before changes are approved.
- 🎨 **Modern Dark-Mode UI**: Built with React, TypeScript, Vite, Recharts, and custom CSS design system.

---

## 🏗️ Architecture

```
┌────────────────────────────────────────────────────────────────────────┐
│                        REACT FRONTEND (Vite + TS)                      │
│   • Dashboard Summary         • AI Query Assistant    • Approvals Gate │
│   • CSV Dataset Ingestion     • Incidents Management  • Benchmarks     │
│   • Schema Explorer           • Performance Analytics • Settings       │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ HTTP / REST (JSON)
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                        FASTAPI BACKEND SERVICE                         │
│                                                                        │
│   ┌────────────────────┐ ┌────────────────────┐ ┌───────────────────┐  │
│   │   Query Service    │ │ Monitoring Engine  │ │  Safety Validator │  │
│   │ (AST verification, │ │ (APScheduler, P95/ │ │ (sqlglot parser,  │  │
│   │  sandbox execution)│ │  P99 latency SLA)  │ │  Action Class A/C)│  │
│   └─────────┬──────────┘ └─────────┬──────────┘ └─────────┬─────────┘  │
│             │                      │                      │            │
│   ┌─────────▼──────────────────────▼──────────────────────▼────────┐   │
│   │                LANGGRAPH AGENT WORKFLOW ENGINE                 │   │
│   │   [Anomaly] ──> [Root Cause] ──> [Optimizer] ──> [Safety]      │   │
│   │                                                     │          │   │
│   │       [Performance Benchmark] <── [Approval Gate] <┘          │   │
│   └────────────────────────────────┬───────────────────────────────┘   │
│                                    │                                   │
│   ┌────────────────────────────────▼───────────────────────────────┐   │
│   │                       LLM PROVIDER LAYER                       │   │
│   │   Google Gemini 2.0 Flash / OpenAI / Anthropic / Fallback Heuristics│
│   └────────────────────────────────────────────────────────────────┘   │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                      DATABASE LAYER (SQLAlchemy)                       │
│   • Primary: SQLite (development) or PostgreSQL (production)           │
│   • Application metadata: datasets, query_history, incidents,          │
│     optimizations, approvals, experiments, monitoring_metrics          │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 🚀 Quick Start Guide

### Prerequisites
- Python 3.10+
- Node.js 18+ and npm
- (Optional) Docker & Docker Compose for containerized PostgreSQL deployment

### 1. Clone & Set Up Environment

```bash
cd agenticdb
cp .env.example backend/.env
```

Edit `backend/.env` to configure your LLM provider (optional — fallback heuristic rules allow testing without an API key):
```env
LLM_PROVIDER=google
LLM_MODEL=gemini-2.0-flash
LLM_API_KEY=your_gemini_api_key_here
DATABASE_URL=sqlite:///./agenticdb.db
MONITOR_INTERVAL_SECONDS=30
SLOW_QUERY_THRESHOLD_MS=500
```

### 2. One-Click Launch (Windows)

Simply run the included launch script:
```powershell
.\start.ps1
```
or
```cmd
start.bat
```

This will automatically:
1. Seed the demo database with realistic retail data and simulated incidents.
2. Start the FastAPI backend on `http://localhost:8000`.
3. Start the Vite React frontend on `http://localhost:5173`.

### 3. Manual Step-by-Step Setup

#### Backend:
```bash
cd backend
pip install -r requirements.txt
python -m pytest tests -v          # Run the 20-test automated suite
python ../datasets/scripts/seed_demo_data.py   # Seed sample data
uvicorn app.main:app --reload --port 8000
```

#### Frontend:
```bash
cd frontend
npm install
npm run dev
```

Open your browser at `http://localhost:5173`.

---

## 🐳 Docker Compose Deployment

To run AgenticDB with a dedicated PostgreSQL 16 container:

```bash
docker-compose up --build
```
- Frontend UI: `http://localhost:5173`
- Backend API: `http://localhost:8000`
- API Documentation (Swagger): `http://localhost:8000/docs`

---

## 🛡️ Safety & Governance System

AgenticDB strictly separates queries and proposed optimizations into distinct Action Classes:

| Class | Type | Execution Policy | Example |
|---|---|---|---|
| **Class A** | Non-mutating read | Autonomous execution | `SELECT`, `EXPLAIN QUERY PLAN`, catalog inspection |
| **Class B** | Isolated test workload | Sandboxed execution | Isolated 5-run benchmark comparisons |
| **Class C** | Persistent schema/state | **Mandatory Human Approval** | `CREATE INDEX`, `DROP INDEX`, schema migrations |

### Safety Invariants Enforced:
1. **AST SQL Validator**: Uses `sqlglot` to verify queries are syntactically valid single statements. Destructive operations (`DROP`, `TRUNCATE`, `DELETE`, `GRANT`, `LOAD DATA`) are blocked.
2. **Row Limit Clamping**: Queries without a limit are automatically assigned `LIMIT 10000`. Excessive limits are clamped to prevent memory exhaustion.
3. **Rollback Strategy Provided**: Every Class C recommendation includes an automated rollback SQL statement (e.g. `DROP INDEX IF EXISTS ...`) before it can be queued for approval.

---

## 📊 Evaluation & Empirical Benchmarks

AgenticDB includes an empirical benchmark harness comparing baseline vs optimized execution times across 5 repeated runs:

| Benchmark Case | Description | Baseline | Optimized | Speedup | Result Verification |
|---|---|---|---|---|---|
| **Unindexed Join** | `orders` ⨝ `customers` on `customer_id` | 745.2 ms | 46.1 ms | **16.2×** | Verified (500 rows match) |
| **Line Items Aggregation** | `order_items` grouped by `product_id` | 890.4 ms | 180.2 ms | **4.9×** | Verified (6 categories match) |
| **Date Range Lookup** | Filter on `orders(order_date)` | 512.8 ms | 18.4 ms | **27.8×** | Verified (14 rows match) |

### Test Suite Status:
- 20 unit and integration tests passing (`100% pass rate` in `backend/tests/test_agenticdb.py`).
- Validates SQL validation, row limits, CSV parsing, schema extraction, and all REST endpoints.

---

## 📂 Project Structure

```
agenticdb/
├── backend/
│   ├── app/
│   │   ├── agents/          # LangGraph state machine & reasoning workflow
│   │   ├── api/             # FastAPI REST endpoints
│   │   ├── core/            # Configuration & environment settings
│   │   ├── database/        # SQLAlchemy engine, session, & schema init
│   │   ├── models/          # ORM models (incidents, approvals, etc.)
│   │   ├── monitoring/      # APScheduler background worker
│   │   ├── safety/          # AST SQL validator & Action Class classifier
│   │   └── services/        # Query execution, data generator, LLM service
│   ├── tests/               # Automated pytest suite (20 tests)
│   ├── Dockerfile
│   └── requirements.txt
├── datasets/
│   ├── sample/              # Sample CSV datasets (customers, orders, products)
│   └── scripts/             # Seeding & workload generation scripts
├── docs/
│   ├── architecture.md      # Detailed system architecture
│   ├── api_spec.md          # REST API reference
│   ├── safety_model.md      # Safety framework & action classes
│   └── evaluations.md       # Empirical benchmark results
├── frontend/
│   ├── src/
│   │   ├── services/api.ts  # TypeScript API client
│   │   ├── App.tsx          # Full 11-page React UI application
│   │   └── index.css        # Premium dark-theme design system
│   ├── Dockerfile
│   └── package.json
├── docker-compose.yml       # Multi-container Postgres + Backend + Frontend
├── start.bat                # Windows launch batch script
├── start.ps1                # Windows PowerShell launch script
└── README.md
```

---

## 📄 License
This project is licensed under the MIT License.
