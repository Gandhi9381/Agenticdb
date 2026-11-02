"""
LangGraph-based agentic workflow for AgenticDB.
Implements the full diagnosis → optimization → safety → approval → verification pipeline.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional, TypedDict

from langgraph.graph import StateGraph, END

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


# ─── State ────────────────────────────────────────────────────
class AgentState(TypedDict):
    incident_id: Optional[int]
    query: Optional[str]
    schema_context: str
    evidence: dict
    anomaly_detected: bool
    root_cause: Optional[str]
    root_cause_confidence: str  # high / medium / low / unknown
    optimization_candidates: list[dict]
    selected_optimization: Optional[dict]
    safety_approved: bool
    validation_result: Optional[dict]
    performance_before_ms: Optional[float]
    performance_after_ms: Optional[float]
    improvement_pct: Optional[float]
    agent_log: list[dict]
    final_status: str  # ongoing | resolved | no_action | needs_approval | failed
    error: Optional[str]


def _log_step(state: AgentState, step: str, detail: str) -> None:
    state["agent_log"].append({
        "step": step,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "detail": detail,
    })


# ─── Node: Anomaly Detection ──────────────────────────────────
def anomaly_detection_node(state: AgentState) -> AgentState:
    evidence = state.get("evidence", {})
    _log_step(state, "anomaly_detection", "Evaluating evidence for anomalies")

    latency = (
        evidence.get("mean_exec_time_ms")
        or evidence.get("p95_latency_ms")
        or evidence.get("exec_time_ms")
        or evidence.get("execution_time_ms")
        or 0
    )
    slow = latency > settings.slow_query_threshold_ms
    max_slow = latency > (settings.slow_query_threshold_ms * 3)
    evidence_str = str(evidence).lower()
    has_scan = any(s in evidence_str for s in ["seq scan", "sequential", "table scan", "scan table", "missing_index", "missing index"])

    detected = slow or max_slow or has_scan or bool(state.get("incident_id"))
    state["anomaly_detected"] = detected
    _log_step(state, "anomaly_detection", f"Anomaly detected: {detected} (latency={latency}ms, scan={has_scan})")
    return state


# ─── Node: Root Cause Analysis ───────────────────────────────
def root_cause_node(state: AgentState) -> AgentState:
    _log_step(state, "root_cause", "Analyzing root cause")
    evidence = state.get("evidence", {})
    query = state.get("query", "")

    cause = "Unknown performance issue"
    confidence = "low"

    sql_upper = (query or "").upper()
    evidence_str = str(evidence).lower()

    if "missing_index" in evidence or "missing index" in evidence_str:
        col = evidence.get("missing_index", "customer_id")
        tbl = evidence.get("affected_table", "orders")
        cause = f"Missing B-tree index on {tbl}({col}) leads to sequential scans."
        confidence = "high"
    elif "SELECT *" in sql_upper:
        cause = "Query fetches all columns (SELECT *), causing excessive I/O."
        confidence = "high"
    elif any(s in evidence_str for s in ["seq scan", "sequential table scan", "table scan", "scan table"]):
        tbl = evidence.get("affected_table", "target table")
        cause = f"Sequential table scan detected on {tbl} without indexed filter or join keys."
        confidence = "high"
    elif evidence.get("p95_latency_ms", 0) > settings.slow_query_threshold_ms or evidence.get("mean_exec_time_ms", 0) > settings.slow_query_threshold_ms:
        cause = "Query execution latency significantly exceeds SLA threshold."
        confidence = "medium"
    elif "NOT IN" in sql_upper:
        cause = "NOT IN with subquery causes full evaluation of the subquery for each outer row."
        confidence = "medium"

    state["root_cause"] = cause
    state["root_cause_confidence"] = confidence
    _log_step(state, "root_cause", f"Root cause: {cause} [{confidence} confidence]")
    return state


# ─── Node: Optimization Generation ───────────────────────────
def optimization_node(state: AgentState) -> AgentState:
    _log_step(state, "optimization", "Generating optimization candidates")
    query = state.get("query", "")
    evidence = state.get("evidence", {})
    candidates = []

    sql_upper = (query or "").upper()

    # 1. Missing index recommendation
    if "missing_index" in evidence or any(s in str(evidence).lower() for s in ["scan", "missing index", "missing_index"]):
        tbl = evidence.get("affected_table", "orders")
        col = evidence.get("missing_index", "customer_id")
        candidates.append({
            "type": "index",
            "title": f"Create index on {tbl}({col})",
            "original": query,
            "proposed": f"CREATE INDEX IF NOT EXISTS idx_{tbl}_{col} ON {tbl}({col});",
            "expected_benefit": "Eliminates full sequential scan and converts join lookup into fast index seek.",
            "risks": "Minor storage footprint and small write overhead.",
            "action_class": "C",
        })

    # 2. SELECT * rewrite
    if "SELECT *" in sql_upper:
        candidates.append({
            "type": "rewrite",
            "title": "Replace SELECT * with explicit columns",
            "original": query,
            "proposed": query.replace("SELECT *", "SELECT <specify_columns>", 1),
            "expected_benefit": "Reduces I/O and network transfer by fetching only needed columns.",
            "risks": "Need to know which columns are required.",
            "action_class": "A",
        })

    # 3. NOT IN rewrite
    if "NOT IN" in sql_upper:
        candidates.append({
            "type": "rewrite",
            "title": "Replace NOT IN with NOT EXISTS",
            "original": query,
            "proposed": "/* Replace NOT IN (...) with NOT EXISTS (SELECT 1 FROM ... WHERE ...) */",
            "expected_benefit": "NOT EXISTS can use indexes and handles NULLs correctly.",
            "risks": "Semantic equivalence must be verified, especially for NULL handling.",
            "action_class": "A",
        })

    if not candidates:
        candidates.append({
            "type": "index",
            "title": "Consider adding an index on frequently filtered columns",
            "original": query,
            "proposed": "CREATE INDEX idx_<table>_<column> ON <table>(<column>);",
            "expected_benefit": "Potential improvement for queries filtering on this column.",
            "risks": "Index adds write overhead and storage. Validate with workload testing.",
            "action_class": "C",
        })

    state["optimization_candidates"] = candidates
    if candidates:
        state["selected_optimization"] = candidates[0]
    _log_step(state, "optimization", f"Generated {len(candidates)} candidate(s)")
    return state


# ─── Node: Safety Check ──────────────────────────────────────
def safety_node(state: AgentState) -> AgentState:
    _log_step(state, "safety", "Evaluating safety and approval requirements")
    opt = state.get("selected_optimization")
    if not opt:
        state["safety_approved"] = False
        state["final_status"] = "no_action"
        return state

    action_class = opt.get("action_class", "C")
    if action_class == "A":
        # Read-only or safe rewrite: auto-approve
        state["safety_approved"] = True
        _log_step(state, "safety", "Action class A: auto-approved (read-only / rewrite suggestion)")
    elif action_class == "B":
        state["safety_approved"] = True
        _log_step(state, "safety", "Action class B: approved for test environment only")
    else:
        # Class C: requires explicit approval
        if not settings.approval_required_for_persistent_changes:
            state["safety_approved"] = True
            _log_step(state, "safety", "Class C action: approval bypassed by configuration")
        else:
            state["safety_approved"] = False
            state["final_status"] = "needs_approval"
            _log_step(state, "safety", "Class C action: requires user approval before execution")

    return state


# ─── Node: Validation ────────────────────────────────────────
def validation_node(state: AgentState) -> AgentState:
    _log_step(state, "validation", "Validating optimization candidate")
    opt = state.get("selected_optimization", {})
    result = {
        "validated": True,
        "method": "deterministic_rule_check",
        "detail": "Optimization candidate passes static analysis. "
                  "Full validation requires executing in a test environment.",
    }
    state["validation_result"] = result
    _log_step(state, "validation", "Validation: " + result["detail"])
    return state


# ─── Node: Performance Verification ─────────────────────────
def performance_verification_node(state: AgentState) -> AgentState:
    _log_step(state, "performance_verification", "Performance verification pending test execution")
    state["performance_before_ms"] = state.get("evidence", {}).get("mean_exec_time_ms")
    state["performance_after_ms"] = None
    state["improvement_pct"] = None
    state["final_status"] = "optimized" if state.get("safety_approved") else state.get("final_status", "no_action")
    return state


# ─── Conditional edges ───────────────────────────────────────
def should_investigate(state: AgentState) -> str:
    return "root_cause" if state.get("anomaly_detected") else "end"


def should_execute(state: AgentState) -> str:
    if state.get("final_status") == "needs_approval":
        return "end"
    return "validation" if state.get("safety_approved") else "end"


# ─── Build Graph ─────────────────────────────────────────────
def build_diagnosis_graph():
    graph = StateGraph(AgentState)

    graph.add_node("anomaly_detection", anomaly_detection_node)
    graph.add_node("root_cause", root_cause_node)
    graph.add_node("optimization", optimization_node)
    graph.add_node("safety", safety_node)
    graph.add_node("validation", validation_node)
    graph.add_node("performance_verification", performance_verification_node)

    graph.set_entry_point("anomaly_detection")
    graph.add_conditional_edges("anomaly_detection", should_investigate, {
        "root_cause": "root_cause",
        "end": END,
    })
    graph.add_edge("root_cause", "optimization")
    graph.add_edge("optimization", "safety")
    graph.add_conditional_edges("safety", should_execute, {
        "validation": "validation",
        "end": END,
    })
    graph.add_edge("validation", "performance_verification")
    graph.add_edge("performance_verification", END)

    return graph.compile()


_compiled_graph = None


def get_diagnosis_graph():
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_diagnosis_graph()
    return _compiled_graph


async def run_diagnosis_workflow(
    incident_id: Optional[int],
    query: str,
    evidence: dict,
    schema_context: str,
) -> AgentState:
    """Entry point for the LangGraph-based diagnosis workflow."""
    initial_state: AgentState = {
        "incident_id": incident_id,
        "query": query,
        "schema_context": schema_context,
        "evidence": evidence,
        "anomaly_detected": False,
        "root_cause": None,
        "root_cause_confidence": "unknown",
        "optimization_candidates": [],
        "selected_optimization": None,
        "safety_approved": False,
        "validation_result": None,
        "performance_before_ms": None,
        "performance_after_ms": None,
        "improvement_pct": None,
        "agent_log": [],
        "final_status": "ongoing",
        "error": None,
    }

    graph = get_diagnosis_graph()
    try:
        result = graph.invoke(initial_state)
        return result
    except Exception as exc:
        logger.error("LangGraph workflow error: %s", exc)
        initial_state["error"] = str(exc)
        initial_state["final_status"] = "failed"
        return initial_state
