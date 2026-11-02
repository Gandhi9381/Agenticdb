"""
AgenticDB API Router: Health, Datasets, Schema, Query, Incidents, Optimizations, Approvals, Monitoring, Experiments
"""
from __future__ import annotations

import time
from typing import Any, Optional
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.database.engine import get_db
from app.models import (
    DatasetModel, QueryHistoryModel, IncidentModel,
    IncidentStatus, OptimizationModel, OptimizationStatus, ExecutionStatus,
    ApprovalModel, ApprovalStatus, ExperimentModel,
)
from app.services.dataset_service import (
    import_csv_to_db, import_dataframe_to_db,
    get_table_schema, list_tables,
)
from app.services.data_generator import generate_all
from app.services.query_service import (
    build_schema_context, execute_read_only_sql,
    explain_sql, analyze_query_performance,
)
from app.services.llm_service import (
    generate_sql, generate_optimization_suggestions,
    generate_incident_diagnosis,
)
from app.monitoring.monitor import (
    run_monitoring_cycle, start_monitoring, stop_monitoring,
    is_monitoring_active,
)
from app.agents.diagnosis_graph import run_diagnosis_workflow

settings = get_settings()
router = APIRouter()


# ─── Health ──────────────────────────────────────────────────
@router.get("/health")
def health():
    current_settings = get_settings(reload=True)
    return {
        "status": "ok",
        "llm_configured": current_settings.llm_configured,
        "llm_provider": current_settings.llm_provider,
        "llm_model": current_settings.llm_model if current_settings.llm_configured else None,
        "monitoring_active": is_monitoring_active(),
        "timestamp": datetime.utcnow().isoformat(),
    }


# ─── Databases ───────────────────────────────────────────────
@router.get("/databases")
def list_databases(db: Session = Depends(get_db)):
    datasets = db.query(DatasetModel).filter_by(status="active").all()
    tables = list_tables()
    return {
        "databases": [
            {
                "name": "agenticdb_local",
                "type": "sqlite" if not settings.is_postgres else "postgresql",
                "url": settings.database_url.split("@")[-1] if "@" in settings.database_url else settings.database_url,
                "status": "connected",
                "table_count": len(tables),
            }
        ],
        "total_tables": len(tables),
        "registered_datasets": len(datasets),
    }


# ─── Dataset Upload ───────────────────────────────────────────
@router.post("/datasets/upload")
async def upload_dataset(
    file: UploadFile = File(...),
    table_name: Optional[str] = Form(None),
    overwrite: bool = Form(False),
    db: Session = Depends(get_db),
):
    data = await file.read()
    tname = table_name or file.filename.replace(".csv", "").replace("-", "_").replace(" ", "_")
    result = import_csv_to_db(db, data, file.filename, tname, overwrite)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/datasets/load-sample")
def load_sample_data(
    rows: int = 1000,
    db: Session = Depends(get_db),
):
    tables = generate_all(rows=rows, seed=settings.sample_data_seed)
    results = {}
    for tname, df in tables.items():
        r = import_dataframe_to_db(db, df, tname, source="synthetic", overwrite=True)
        results[tname] = r
    return {"success": True, "tables": results}


# ─── Tables & Schema ─────────────────────────────────────────
@router.get("/tables")
def get_tables(db: Session = Depends(get_db)):
    tables = list_tables()
    datasets = {d.name: d for d in db.query(DatasetModel).all()}
    return {
        "tables": [
            {
                "name": t,
                "row_count": datasets[t].row_count if t in datasets else None,
                "source": datasets[t].source if t in datasets else "unknown",
            }
            for t in tables
        ],
        "count": len(tables),
    }


@router.get("/tables/{table_name}/schema")
def get_schema(table_name: str):
    schema = get_table_schema(table_name)
    if not schema:
        raise HTTPException(status_code=404, detail=f"Table '{table_name}' not found.")
    return schema


@router.get("/tables/{table_name}/preview")
def preview_table(table_name: str, limit: int = 50, db: Session = Depends(get_db)):
    result = execute_read_only_sql(
        f'SELECT * FROM "{table_name}" LIMIT {min(limit, 200)}',
        db,
        source="system",
    )
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


# ─── Query: Generate & Execute ────────────────────────────────
class QueryRequest(BaseModel):
    question: str
    tables: Optional[list[str]] = None
    history: Optional[list[dict]] = None


@router.post("/query/generate")
async def query_generate(req: QueryRequest, db: Session = Depends(get_db)):
    schema = build_schema_context(req.tables)
    result = await generate_sql(req.question, schema, req.history)
    return {
        "question": req.question,
        "sql": result.get("sql"),
        "explanation": result.get("explanation"),
        "llm_used": result.get("llm_used", False),
        "schema_used": schema,
    }


class ExecuteRequest(BaseModel):
    sql: str
    natural_language: Optional[str] = None


@router.post("/query/execute")
def query_execute(req: ExecuteRequest, db: Session = Depends(get_db)):
    result = execute_read_only_sql(req.sql, db, natural_language=req.natural_language)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


class ExplainRequest(BaseModel):
    sql: str


@router.post("/query/explain")
def query_explain(req: ExplainRequest):
    result = explain_sql(req.sql)
    analysis = analyze_query_performance(req.sql)
    return {**result, "static_analysis": analysis}


class OptimizeQueryRequest(BaseModel):
    sql: str


@router.post("/query/optimize")
async def query_optimize(req: OptimizeQueryRequest):
    """Generate AI optimization recommendations for a query based on schema and EXPLAIN plan."""
    plan_result = explain_sql(req.sql)
    schema = build_schema_context()
    suggestions = await generate_optimization_suggestions(
        query=req.sql,
        plan=plan_result.get("plan", {}),
        schema_context=schema,
    )
    return suggestions


# ─── Query History ────────────────────────────────────────────
@router.get("/queries/history")
def query_history(limit: int = 50, db: Session = Depends(get_db)):
    rows = (
        db.query(QueryHistoryModel)
        .order_by(QueryHistoryModel.created_at.desc())
        .limit(limit)
        .all()
    )
    return {
        "history": [
            {
                "id": r.id,
                "natural_language": r.natural_language,
                "generated_sql": r.generated_sql,
                "execution_time_ms": r.execution_time_ms,
                "row_count": r.row_count,
                "status": r.status,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    }


# ─── Performance ─────────────────────────────────────────────
@router.get("/performance/summary")
def performance_summary(db: Session = Depends(get_db)):
    queries = db.query(QueryHistoryModel).all()
    success = [q for q in queries if q.status == "success" and q.execution_time_ms]
    slow = [q for q in success if q.execution_time_ms > settings.slow_query_threshold_ms]

    avg = sum(q.execution_time_ms for q in success) / len(success) if success else None
    times = sorted(q.execution_time_ms for q in success)
    p95 = times[min(len(times) - 1, int(0.95 * len(times)))] if times else None

    return {
        "total_queries": len(queries),
        "successful_queries": len(success),
        "slow_queries": len(slow),
        "avg_execution_time_ms": round(avg, 2) if avg else None,
        "p95_execution_time_ms": round(p95, 2) if p95 else None,
        "slow_query_threshold_ms": settings.slow_query_threshold_ms,
    }


@router.get("/performance/slow-queries")
def slow_queries(db: Session = Depends(get_db)):
    queries = (
        db.query(QueryHistoryModel)
        .filter(QueryHistoryModel.execution_time_ms > settings.slow_query_threshold_ms)
        .filter(QueryHistoryModel.status == "success")
        .order_by(QueryHistoryModel.execution_time_ms.desc())
        .limit(50)
        .all()
    )
    return {
        "slow_queries": [
            {
                "id": q.id,
                "sql": q.generated_sql,
                "execution_time_ms": q.execution_time_ms,
                "created_at": q.created_at.isoformat() if q.created_at else None,
            }
            for q in queries
        ]
    }


# ─── Incidents ────────────────────────────────────────────────
@router.get("/incidents")
def list_incidents(status: Optional[str] = None, db: Session = Depends(get_db)):
    q = db.query(IncidentModel).order_by(IncidentModel.detected_at.desc())
    if status:
        q = q.filter(IncidentModel.status == status)
    incidents = q.limit(100).all()
    return {
        "incidents": [
            {
                "id": i.id,
                "title": i.title,
                "severity": i.severity.value if i.severity else None,
                "status": i.status.value if i.status else None,
                "detected_at": i.detected_at.isoformat() if i.detected_at else None,
            }
            for i in incidents
        ]
    }


@router.get("/incidents/{incident_id}")
def get_incident(incident_id: int, db: Session = Depends(get_db)):
    incident = db.query(IncidentModel).filter_by(id=incident_id).first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found.")
    return {
        "id": incident.id,
        "title": incident.title,
        "description": incident.description,
        "severity": incident.severity.value if incident.severity else None,
        "status": incident.status.value if incident.status else None,
        "evidence": incident.evidence,
        "root_cause": incident.root_cause,
        "agent_log": incident.agent_log,
        "detected_at": incident.detected_at.isoformat() if incident.detected_at else None,
        "resolved_at": incident.resolved_at.isoformat() if incident.resolved_at else None,
    }


class DiagnoseRequest(BaseModel):
    query: Optional[str] = None
    evidence: Optional[dict] = None


@router.post("/incidents/{incident_id}/diagnose")
async def diagnose_incident(
    incident_id: int,
    req: DiagnoseRequest,
    db: Session = Depends(get_db),
):
    from app.services.optimization_service import create_index_recommendation_idempotent

    incident = db.query(IncidentModel).filter_by(id=incident_id).first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found.")

    evidence = req.evidence or incident.evidence or {}
    query = req.query or ""
    schema = build_schema_context()

    # Run LangGraph workflow
    workflow_result = await run_diagnosis_workflow(
        incident_id=incident_id,
        query=query,
        evidence=evidence,
        schema_context=schema,
    )

    # Run LLM diagnosis if configured
    llm_diagnosis = await generate_incident_diagnosis(incident.title, evidence, schema)

    # Update incident
    incident.root_cause = workflow_result.get("root_cause", "")
    incident.status = IncidentStatus.investigating
    incident.agent_log = workflow_result.get("agent_log", [])
    db.commit()

    # Create optimization candidates using idempotent service
    candidates = workflow_result.get("optimization_candidates", [])
    created_opts = []
    for c in candidates:
        if c.get("type") == "index" and c.get("proposed"):
            # Use idempotent index recommendation creation
            r = create_index_recommendation_idempotent(
                db,
                title=c.get("title", "Optimization"),
                proposed_sql=c.get("proposed"),
                reasoning=c.get("expected_benefit", ""),
                expected_benefit=c.get("expected_benefit", ""),
                risks=c.get("risks", ""),
                original_sql=c.get("original") or None,
                incident_id=incident_id,
            )
            created_opts.append(r)
        else:
            # Non-index optimization (rewrites, etc.) — always create
            opt = OptimizationModel(
                incident_id=incident_id,
                title=c.get("title", "Optimization"),
                original_sql=c.get("original") or None,
                proposed_sql=c.get("proposed"),
                optimization_type=c.get("type", "rewrite"),
                reasoning=c.get("expected_benefit"),
                expected_benefit=c.get("expected_benefit"),
                risks=c.get("risks"),
                status=OptimizationStatus.pending,
            )
            db.add(opt)
            db.commit()
            created_opts.append({"created": True, "optimization_id": opt.id})

    return {
        "incident_id": incident_id,
        "workflow": {
            "root_cause": workflow_result.get("root_cause"),
            "confidence": workflow_result.get("root_cause_confidence"),
            "agent_log": workflow_result.get("agent_log"),
            "optimization_candidates": workflow_result.get("optimization_candidates"),
            "final_status": workflow_result.get("final_status"),
        },
        "llm_diagnosis": llm_diagnosis.get("diagnosis"),
        "optimization_creation_results": created_opts,
    }


# ─── Optimizations ────────────────────────────────────────────
def _opt_to_dict_summary(o: OptimizationModel) -> dict:
    """Compact representation for the list view."""
    return {
        "id": o.id,
        "title": o.title,
        "type": o.optimization_type,
        "status": o.status.value if o.status else None,
        "execution_status": o.execution_status or ExecutionStatus.not_executed.value,
        "improvement_pct": o.improvement_pct,
        "benchmark_verified": bool(o.benchmark_verified),
        "target_table": o.target_table,
        "target_columns": o.target_columns,
        "index_name": o.index_name,
        "created_at": o.created_at.isoformat() if o.created_at else None,
    }


def _opt_to_dict_full(o: OptimizationModel) -> dict:
    """Full representation for the detail view."""
    # Determine original_sql display value
    original_sql_display = o.original_sql
    if o.optimization_type == "index" and not original_sql_display:
        original_sql_display = None  # Will be rendered as "Not applicable"

    # Determine proposed action display
    proposed_action_display = o.proposed_sql
    if not proposed_action_display and o.target_table and o.index_name:
        proposed_action_display = (
            f"Create index {o.index_name} on {o.target_table}({o.target_columns})"
        )

    # Determine improvement display
    improvement_display = None
    if o.improvement_pct is not None and o.benchmark_verified:
        improvement_display = o.improvement_pct
    # else: not measured / unverified

    return {
        "id": o.id,
        "title": o.title,
        "optimization_type": o.optimization_type,
        "status": o.status.value if o.status else None,
        "db_target": o.db_target or "agenticdb_local",
        "target_table": o.target_table,
        "target_columns": o.target_columns,
        "index_name": o.index_name,
        "index_identity_key": o.index_identity_key,
        # Original SQL: null means "not applicable for index ops"
        "original_sql": original_sql_display,
        "original_sql_label": (
            "Not applicable — this recommendation is an index operation"
            if o.optimization_type == "index" and not original_sql_display
            else None
        ),
        # Proposed action
        "proposed_sql": o.proposed_sql,
        "proposed_action_display": proposed_action_display,
        # Reasoning
        "reasoning": o.reasoning,
        "expected_benefit": o.expected_benefit,
        "risks": o.risks,
        # Execution tracking
        "execution_status": o.execution_status or ExecutionStatus.not_executed.value,
        "executed_at": o.executed_at.isoformat() if o.executed_at else None,
        "execution_result": o.execution_result,
        "execution_error": o.execution_error,
        "index_verified_exists": o.index_verified_exists,
        # Benchmarking
        "baseline_latency_ms": o.baseline_latency_ms,
        "optimized_latency_ms": o.optimized_latency_ms,
        "improvement_pct": improvement_display,
        "improvement_pct_raw": o.improvement_pct,
        "benchmark_verified": bool(o.benchmark_verified),
        "benchmark_note": o.benchmark_note,
        # Validation
        "validation_result": o.validation_result,
        "created_at": o.created_at.isoformat() if o.created_at else None,
        "updated_at": o.updated_at.isoformat() if o.updated_at else None,
    }


@router.get("/optimizations")
def list_optimizations(db: Session = Depends(get_db)):
    opts = db.query(OptimizationModel).order_by(OptimizationModel.created_at.desc()).limit(100).all()
    return {"optimizations": [_opt_to_dict_summary(o) for o in opts]}


@router.get("/optimizations/{opt_id}")
def get_optimization(opt_id: int, db: Session = Depends(get_db)):
    opt = db.query(OptimizationModel).filter_by(id=opt_id).first()
    if not opt:
        raise HTTPException(status_code=404, detail="Optimization not found.")

    result = _opt_to_dict_full(opt)

    # Attach latest experiment if any
    latest_exp = (
        db.query(ExperimentModel)
        .filter_by(optimization_id=opt_id)
        .order_by(ExperimentModel.created_at.desc())
        .first()
    )
    if latest_exp:
        result["latest_experiment"] = {
            "id": latest_exp.id,
            "baseline_avg_ms": latest_exp.baseline_avg_ms,
            "candidate_avg_ms": latest_exp.candidate_avg_ms,
            "baseline_median_ms": latest_exp.baseline_median_ms,
            "candidate_median_ms": latest_exp.candidate_median_ms,
            "improvement_pct": latest_exp.improvement_pct,
            "correctness_check": latest_exp.correctness_check,
            "correctness_detail": latest_exp.correctness_detail,
            "verified": latest_exp.verified,
            "unverified_reason": latest_exp.unverified_reason,
            "index_state": latest_exp.index_state_during_run,
            "run_at": latest_exp.run_at.isoformat() if latest_exp.run_at else None,
        }

    # Attach approved approval if any
    # Note: ApprovalModel uses decision_at (not updated_at) for when a decision was made
    approved_approval = (
        db.query(ApprovalModel)
        .filter_by(optimization_id=opt_id, status=ApprovalStatus.approved)
        .order_by(ApprovalModel.decision_at.desc())
        .first()
    )
    if approved_approval:
        result["approved_approval_id"] = approved_approval.id

    return result


@router.post("/optimizations/{opt_id}/request-approval")
def request_approval(opt_id: int, db: Session = Depends(get_db)):
    opt = db.query(OptimizationModel).filter_by(id=opt_id).first()
    if not opt:
        raise HTTPException(status_code=404, detail="Optimization not found.")

    # Idempotency: prevent duplicate pending approvals for the same optimization
    existing_pending = (
        db.query(ApprovalModel)
        .filter_by(optimization_id=opt_id, status=ApprovalStatus.pending)
        .first()
    )
    if existing_pending:
        return {
            "approval_id": existing_pending.id,
            "status": "already_pending",
            "message": f"Approval #{existing_pending.id} is already pending for this optimization.",
        }

    # Build a meaningful proposed_action display string
    if opt.optimization_type == "index" and opt.target_table:
        proposed_action = (
            f"CREATE INDEX {opt.index_name} ON {opt.target_table}({opt.target_columns})"
            if opt.index_name else opt.proposed_sql or opt.title
        )
    else:
        proposed_action = opt.proposed_sql or opt.title

    approval = ApprovalModel(
        optimization_id=opt_id,
        action_class="C",
        proposed_action=proposed_action,
        explanation=opt.reasoning,
        expected_benefit=opt.expected_benefit,
        risk_assessment=opt.risks,
        rollback_strategy="Drop created index or revert SQL change manually.",
    )
    db.add(approval)
    opt.status = OptimizationStatus.pending
    db.commit()
    db.refresh(approval)
    return {"approval_id": approval.id, "status": "pending_approval"}


# ─── Execute approved optimization ───────────────────────────
class ExecuteOptRequest(BaseModel):
    approval_id: int


@router.post("/optimizations/{opt_id}/execute")
def execute_optimization(
    opt_id: int,
    req: ExecuteOptRequest,
    db: Session = Depends(get_db),
):
    """
    Execute an approved Class C index operation.
    Only callable after explicit approval. The SQL Query Assistant must NOT be used for this.
    """
    from app.services.optimization_service import execute_approved_index
    result = execute_approved_index(db, opt_id, req.approval_id)
    if result.get("error") and not result.get("executed"):
        raise HTTPException(status_code=400, detail=result["error"])
    return result


# ─── Verify index existence ───────────────────────────────────
@router.get("/optimizations/{opt_id}/verify-index")
def verify_index(opt_id: int, db: Session = Depends(get_db)):
    """
    Check whether the index for this optimization actually exists in the database.
    Does NOT execute or create anything.
    """
    from app.services.optimization_service import check_index_exists, check_equivalent_index_exists

    opt = db.query(OptimizationModel).filter_by(id=opt_id).first()
    if not opt:
        raise HTTPException(status_code=404, detail="Optimization not found.")

    table_name = opt.target_table
    columns_sorted = opt.target_columns
    index_name = opt.index_name

    if not table_name or not columns_sorted:
        return {
            "optimization_id": opt_id,
            "index_exists": None,
            "detail": "Optimization has no structured table/column fields — cannot verify.",
        }

    named_exists = check_index_exists(index_name, table_name) if index_name else False
    equivalent_idx = check_equivalent_index_exists(table_name, columns_sorted)

    index_exists = named_exists or bool(equivalent_idx)

    # Update the record
    opt.index_verified_exists = index_exists
    db.commit()

    return {
        "optimization_id": opt_id,
        "target_table": table_name,
        "target_columns": columns_sorted,
        "index_name": index_name,
        "named_index_exists": named_exists,
        "equivalent_index_found": equivalent_idx,
        "index_exists": index_exists,
        "detail": (
            f"Index '{equivalent_idx}' satisfies this recommendation."
            if equivalent_idx else
            ("Named index exists." if named_exists else "No equivalent index found in database.")
        ),
    }


# ─── Benchmark for optimization ───────────────────────────────
class OptBenchmarkRequest(BaseModel):
    baseline_sql: str
    candidate_sql: str
    runs: int = 5
    warmup_runs: int = 1


@router.post("/optimizations/{opt_id}/benchmark")
def benchmark_optimization(
    opt_id: int,
    req: OptBenchmarkRequest,
    db: Session = Depends(get_db),
):
    """
    Run a before/after benchmark for this optimization.
    Both queries must be read-only SELECT statements.
    """
    from app.services.optimization_service import run_benchmark

    opt = db.query(OptimizationModel).filter_by(id=opt_id).first()
    if not opt:
        raise HTTPException(status_code=404, detail="Optimization not found.")

    name = f"Benchmark for: {opt.title}"
    result = run_benchmark(
        db,
        baseline_sql=req.baseline_sql,
        candidate_sql=req.candidate_sql,
        optimization_id=opt_id,
        name=name,
        runs=req.runs,
        warmup_runs=req.warmup_runs,
    )

    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])

    # Update opt with verified benchmark result if valid
    if result.get("valid") and result.get("improvement_pct") is not None:
        opt.baseline_latency_ms = result["baseline_avg_ms"]
        opt.optimized_latency_ms = result["candidate_avg_ms"]
        opt.improvement_pct = result["improvement_pct"]
        opt.benchmark_verified = True
        opt.benchmark_note = "; ".join(result.get("validity_notes", []))
        db.commit()

    return result


# ─── Approvals ────────────────────────────────────────────────
@router.get("/approvals")
def list_approvals(db: Session = Depends(get_db)):
    approvals = db.query(ApprovalModel).order_by(ApprovalModel.created_at.desc()).all()
    return {
        "approvals": [
            {
                "id": a.id,
                "optimization_id": a.optimization_id,
                "action_class": a.action_class,
                "proposed_action": a.proposed_action,
                "explanation": a.explanation,
                "expected_benefit": a.expected_benefit,
                "risk_assessment": a.risk_assessment,
                "status": a.status.value if a.status else None,
                "decision_at": a.decision_at.isoformat() if a.decision_at else None,
                "decision_note": a.decision_note,
                "created_at": a.created_at.isoformat() if a.created_at else None,
                # Include optimization summary for context
                "optimization_title": (
                    a.optimization.title if a.optimization else None
                ),
                "optimization_type": (
                    a.optimization.optimization_type if a.optimization else None
                ),
                "execution_status": (
                    a.optimization.execution_status if a.optimization else None
                ),
            }
            for a in approvals
        ]
    }


@router.post("/approvals/{approval_id}/approve")
def approve_action(approval_id: int, note: str = "", db: Session = Depends(get_db)):
    approval = db.query(ApprovalModel).filter_by(id=approval_id).first()
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found.")
    if approval.status != ApprovalStatus.pending:
        raise HTTPException(
            status_code=400,
            detail=f"Approval #{approval_id} is already '{approval.status.value}'. Cannot re-approve.",
        )
    approval.status = ApprovalStatus.approved
    approval.decision_at = datetime.utcnow()
    approval.decision_note = note
    if approval.optimization:
        approval.optimization.status = OptimizationStatus.approved
    db.commit()
    return {
        "status": "approved",
        "approval_id": approval_id,
        "note": (
            "Approval recorded. Use POST /optimizations/{id}/execute with this approval_id to run the operation."
        ),
    }


@router.post("/approvals/{approval_id}/reject")
def reject_action(approval_id: int, note: str = "", db: Session = Depends(get_db)):
    approval = db.query(ApprovalModel).filter_by(id=approval_id).first()
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found.")
    if approval.status != ApprovalStatus.pending:
        raise HTTPException(
            status_code=400,
            detail=f"Approval #{approval_id} is already '{approval.status.value}'. Cannot re-reject.",
        )
    approval.status = ApprovalStatus.rejected
    approval.decision_at = datetime.utcnow()
    approval.decision_note = note
    if approval.optimization:
        approval.optimization.status = OptimizationStatus.rejected
    db.commit()
    return {"status": "rejected", "approval_id": approval_id}


# ─── Monitoring ───────────────────────────────────────────────
@router.post("/monitoring/start")
def start_mon():
    return start_monitoring()


@router.post("/monitoring/stop")
def stop_mon():
    return stop_monitoring()


@router.post("/monitoring/run-cycle")
def run_cycle():
    return run_monitoring_cycle()


@router.get("/monitoring/status")
def monitoring_status():
    return {
        "active": is_monitoring_active(),
        "interval_seconds": settings.monitor_interval_seconds,
        "slow_query_threshold_ms": settings.slow_query_threshold_ms,
    }


# ─── Experiments ─────────────────────────────────────────────
class ExperimentRequest(BaseModel):
    name: str
    baseline_sql: str
    candidate_sql: str
    runs: int = 5
    warmup_runs: int = 1
    description: Optional[str] = None
    optimization_id: Optional[int] = None


@router.post("/experiments/run")
def run_experiment(req: ExperimentRequest, db: Session = Depends(get_db)):
    from app.services.optimization_service import run_benchmark

    result = run_benchmark(
        db,
        baseline_sql=req.baseline_sql,
        candidate_sql=req.candidate_sql,
        optimization_id=req.optimization_id,
        name=req.name,
        description=req.description or "",
        runs=req.runs,
        warmup_runs=req.warmup_runs,
    )

    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])

    return {
        "experiment_id": result.get("experiment_id"),
        "baseline_avg_ms": result["baseline_avg_ms"],
        "baseline_median_ms": result.get("baseline_median_ms"),
        "candidate_avg_ms": result["candidate_avg_ms"],
        "candidate_median_ms": result.get("candidate_median_ms"),
        "improvement_pct": result["improvement_pct"],
        "baseline_runs": result["baseline_runs"],
        "candidate_runs": result["candidate_runs"],
        "correctness_check": result.get("correctness_check"),
        "correctness_detail": result.get("correctness_detail"),
        "valid": result.get("valid", False),
        "validity_notes": result.get("validity_notes", []),
        "index_state": result.get("index_state_during_run", {}),
        "note": (
            "improvement_pct > 0 means candidate was faster in this measurement. "
            "Small dataset results have high timing noise and may not reflect real-world benefit."
            if result.get("valid") else
            "Improvement percentage not reported — see validity_notes."
        ),
    }


@router.get("/experiments")
def list_experiments(db: Session = Depends(get_db)):
    exps = db.query(ExperimentModel).order_by(ExperimentModel.created_at.desc()).limit(50).all()
    return {
        "experiments": [
            {
                "id": e.id,
                "name": e.name,
                "optimization_id": e.optimization_id,
                "baseline_avg_ms": e.baseline_avg_ms,
                "baseline_median_ms": e.baseline_median_ms,
                "candidate_avg_ms": e.candidate_avg_ms,
                "candidate_median_ms": e.candidate_median_ms,
                "improvement_pct": e.improvement_pct if e.verified else None,
                "improvement_pct_raw": e.improvement_pct,
                "verified": e.verified,
                "unverified_reason": e.unverified_reason,
                "correctness_check": e.correctness_check,
                "status": e.status,
                "run_at": e.run_at.isoformat() if e.run_at else None,
            }
            for e in exps
        ]
    }


# ─── Dashboard summary ────────────────────────────────────────
@router.get("/dashboard/summary")
def dashboard_summary(db: Session = Depends(get_db)):
    total_queries = db.query(QueryHistoryModel).count()
    slow = db.query(QueryHistoryModel).filter(
        QueryHistoryModel.execution_time_ms > settings.slow_query_threshold_ms
    ).count()
    open_incidents = db.query(IncidentModel).filter_by(status=IncidentStatus.open).count()
    resolved = db.query(IncidentModel).filter_by(status=IncidentStatus.resolved).count()
    pending_approvals = db.query(ApprovalModel).filter_by(status=ApprovalStatus.pending).count()
    tables = list_tables()
    optimizations = db.query(OptimizationModel).count()

    curr_settings = get_settings(reload=True)
    return {
        "tables": len(tables),
        "total_queries": total_queries,
        "slow_queries": slow,
        "open_incidents": open_incidents,
        "resolved_incidents": resolved,
        "pending_approvals": pending_approvals,
        "optimizations": optimizations,
        "monitoring_active": is_monitoring_active(),
        "llm_configured": curr_settings.llm_configured,
    }
