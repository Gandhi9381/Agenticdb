"""
SQLAlchemy ORM models for AgenticDB application metadata.
"""
from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    Boolean, Column, DateTime, Enum, Float, ForeignKey,
    Integer, JSON, String, Text, UniqueConstraint
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database.engine import Base


# ─── Dataset / Table registry ────────────────────────────────
class DatasetModel(Base):
    __tablename__ = "datasets"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(128), unique=True, nullable=False)
    original_filename = Column(String(256))
    row_count = Column(Integer, default=0)
    column_count = Column(Integer, default=0)
    schema_info = Column(JSON)  # {col: dtype, ...}
    source = Column(String(32), default="csv")  # csv | synthetic | external
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    status = Column(String(32), default="active")  # active | archived


# ─── Query History ────────────────────────────────────────────
class QueryHistoryModel(Base):
    __tablename__ = "query_history"

    id = Column(Integer, primary_key=True, index=True)
    natural_language = Column(Text)
    generated_sql = Column(Text, nullable=False)
    execution_time_ms = Column(Float)
    row_count = Column(Integer)
    status = Column(String(32), default="success")  # success | error | rejected
    error_message = Column(Text)
    plan_json = Column(JSON)
    created_at = Column(DateTime, default=func.now())
    source = Column(String(32), default="user")  # user | agent | workload


# ─── Monitoring Metrics ───────────────────────────────────────
class MonitoringMetricModel(Base):
    __tablename__ = "monitoring_metrics"

    id = Column(Integer, primary_key=True, index=True)
    metric_name = Column(String(128), nullable=False)
    metric_value = Column(Float)
    metric_json = Column(JSON)
    collected_at = Column(DateTime, default=func.now())
    source = Column(String(64), default="pg_stat_statements")


# ─── Incident ─────────────────────────────────────────────────
class IncidentSeverity(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class IncidentStatus(str, enum.Enum):
    open = "open"
    investigating = "investigating"
    resolved = "resolved"
    dismissed = "dismissed"


class IncidentModel(Base):
    __tablename__ = "incidents"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(256), nullable=False)
    description = Column(Text)
    severity = Column(Enum(IncidentSeverity), default=IncidentSeverity.medium)
    status = Column(Enum(IncidentStatus), default=IncidentStatus.open)
    evidence = Column(JSON)
    root_cause = Column(Text)
    query_fingerprint = Column(String(256))
    detected_at = Column(DateTime, default=func.now())
    resolved_at = Column(DateTime)
    agent_log = Column(JSON)  # List of agent steps

    optimizations = relationship("OptimizationModel", back_populates="incident")


# ─── Optimization Candidate ───────────────────────────────────
class OptimizationStatus(str, enum.Enum):
    pending = "pending"
    validated = "validated"
    approved = "approved"
    rejected = "rejected"
    applied = "applied"
    failed = "failed"
    # Extended statuses for fine-grained tracking
    executing = "executing"
    already_satisfied = "already_satisfied"
    skipped = "skipped"


class ExecutionStatus(str, enum.Enum):
    not_executed = "not_executed"
    executing = "executing"
    success = "success"
    already_exists = "already_exists"
    failed = "failed"
    skipped = "skipped"


class OptimizationModel(Base):
    __tablename__ = "optimizations"

    id = Column(Integer, primary_key=True, index=True)
    incident_id = Column(Integer, ForeignKey("incidents.id"), nullable=True)
    title = Column(String(256))
    original_sql = Column(Text)
    proposed_sql = Column(Text)
    optimization_type = Column(String(64))  # rewrite | index | statistics | config
    reasoning = Column(Text)
    expected_benefit = Column(Text)
    risks = Column(Text)
    status = Column(Enum(OptimizationStatus), default=OptimizationStatus.pending)
    validation_result = Column(JSON)
    baseline_latency_ms = Column(Float)
    optimized_latency_ms = Column(Float)
    improvement_pct = Column(Float)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # ── Index-specific identity fields (for idempotency) ──────
    # Stable identity key: "<db_target>::<table>::<columns_sorted>"
    index_identity_key = Column(String(512), nullable=True, index=True)
    target_table = Column(String(128), nullable=True)
    target_columns = Column(String(256), nullable=True)   # comma-separated, sorted
    index_name = Column(String(256), nullable=True)
    db_target = Column(String(128), nullable=True, default="agenticdb_local")

    # ── Execution tracking ────────────────────────────────────
    execution_status = Column(
        String(32),
        default=ExecutionStatus.not_executed.value,
        nullable=False,
    )
    executed_at = Column(DateTime, nullable=True)
    execution_result = Column(Text, nullable=True)   # Human-readable outcome
    execution_error = Column(Text, nullable=True)    # Error detail if failed
    index_verified_exists = Column(Boolean, nullable=True)  # Post-execution check

    # ── Benchmark references ──────────────────────────────────
    benchmark_verified = Column(Boolean, nullable=True, default=False)
    benchmark_note = Column(Text, nullable=True)

    incident = relationship("IncidentModel", back_populates="optimizations")
    approvals = relationship("ApprovalModel", back_populates="optimization")
    experiments = relationship("ExperimentModel", back_populates="optimization")


# ─── Approval ─────────────────────────────────────────────────
class ApprovalStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class ApprovalModel(Base):
    __tablename__ = "approvals"
    # Prevent duplicate pending approvals for the same optimization.
    # We enforce this at application level (see routes) for backward compat
    # with existing records; the constraint here acts as a safety net on new rows.
    __table_args__ = (
        UniqueConstraint("optimization_id", "status", name="uq_approval_opt_pending",
                         sqlite_on_conflict="IGNORE"),
    )

    id = Column(Integer, primary_key=True, index=True)
    optimization_id = Column(Integer, ForeignKey("optimizations.id"))
    action_class = Column(String(8), default="C")  # A, B, C
    proposed_action = Column(Text)
    explanation = Column(Text)
    expected_benefit = Column(Text)
    risk_assessment = Column(Text)
    rollback_strategy = Column(Text)
    status = Column(Enum(ApprovalStatus), default=ApprovalStatus.pending)
    decision_at = Column(DateTime)
    decision_note = Column(Text)
    created_at = Column(DateTime, default=func.now())

    optimization = relationship("OptimizationModel", back_populates="approvals")


# ─── Benchmark Experiment ─────────────────────────────────────
class ExperimentModel(Base):
    __tablename__ = "experiments"

    id = Column(Integer, primary_key=True, index=True)
    optimization_id = Column(Integer, ForeignKey("optimizations.id"), nullable=True)
    name = Column(String(256))
    description = Column(Text)
    baseline_sql = Column(Text)
    candidate_sql = Column(Text)
    baseline_runs = Column(JSON)  # List of latency measurements
    candidate_runs = Column(JSON)
    baseline_avg_ms = Column(Float)
    candidate_avg_ms = Column(Float)
    baseline_median_ms = Column(Float)
    candidate_median_ms = Column(Float)
    improvement_pct = Column(Float)
    correctness_check = Column(Boolean)
    correctness_detail = Column(Text)
    status = Column(String(32), default="pending")
    # index_state_during_run: which indexes existed when the run occurred
    index_state_during_run = Column(JSON, nullable=True)
    verified = Column(Boolean, nullable=True, default=False)
    unverified_reason = Column(Text, nullable=True)
    run_at = Column(DateTime)
    created_at = Column(DateTime, default=func.now())

    optimization = relationship("OptimizationModel", back_populates="experiments")
