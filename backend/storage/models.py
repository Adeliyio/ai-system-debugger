import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    String,
    Text,
    Float,
    Integer,
    Boolean,
    DateTime,
    ForeignKey,
    Enum as SAEnum,
    Index,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB, ARRAY
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class TraceRecord(Base):
    __tablename__ = "traces"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(String(255), nullable=False, index=True)
    prompt = Column(Text, nullable=False)
    response = Column(Text, nullable=False)
    model_used = Column(String(100), nullable=False)
    context_documents = Column(ARRAY(Text), default=[])
    latency_ms = Column(Float, nullable=False)
    token_count_input = Column(Integer, nullable=False)
    token_count_output = Column(Integer, nullable=False)
    status = Column(
        SAEnum("pending", "analyzed", "failed", "healed", name="trace_status"),
        default="pending",
        nullable=False,
    )
    metadata_ = Column("metadata", JSONB, default={})
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    evaluations = relationship("EvaluationRecord", back_populates="trace", cascade="all, delete-orphan")
    rca_reports = relationship("RCARecord", back_populates="trace", cascade="all, delete-orphan")
    healing_actions = relationship("HealingRecord", back_populates="trace", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_traces_created_at", "created_at"),
        Index("ix_traces_status", "status"),
        Index("ix_traces_model_used", "model_used"),
    )


class EvaluationRecord(Base):
    __tablename__ = "evaluations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    trace_id = Column(
        UUID(as_uuid=True),
        ForeignKey("traces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    passed = Column(Boolean, nullable=False)
    overall_score = Column(Float, nullable=False)
    verdicts = Column(JSONB, nullable=False)
    agreement_count = Column(Integer, nullable=False)
    failure_detected = Column(Boolean, nullable=False)
    severity = Column(
        SAEnum("low", "medium", "high", "critical", name="severity_level"),
        nullable=False,
    )
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    trace = relationship("TraceRecord", back_populates="evaluations")
    rca_reports = relationship("RCARecord", back_populates="evaluation", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_evaluations_created_at", "created_at"),
        Index("ix_evaluations_failure_detected", "failure_detected"),
    )


class RCARecord(Base):
    __tablename__ = "rca_reports"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    trace_id = Column(
        UUID(as_uuid=True),
        ForeignKey("traces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    evaluation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("evaluations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    primary_source = Column(
        SAEnum("retrieval", "prompt", "model", "context", "unknown", name="failure_source"),
        nullable=False,
    )
    findings = Column(JSONB, nullable=False)
    analysis_summary = Column(Text, nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    trace = relationship("TraceRecord", back_populates="rca_reports")
    evaluation = relationship("EvaluationRecord", back_populates="rca_reports")
    healing_actions = relationship("HealingRecord", back_populates="rca_report", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_rca_primary_source", "primary_source"),
    )


class HealingRecord(Base):
    __tablename__ = "healing_actions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    trace_id = Column(
        UUID(as_uuid=True),
        ForeignKey("traces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    rca_id = Column(
        UUID(as_uuid=True),
        ForeignKey("rca_reports.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    strategy = Column(
        SAEnum(
            "prompt_repair",
            "retrieval_correction",
            "model_reroute",
            "context_enrichment",
            name="healing_strategy",
        ),
        nullable=False,
    )
    original_response = Column(Text, nullable=False)
    repaired_response = Column(Text, nullable=False)
    repair_prompt = Column(Text, nullable=True)
    attempt_number = Column(Integer, nullable=False, default=1)
    regression_passed = Column(Boolean, nullable=False)
    regression_results = Column(JSONB, default=[])
    improvement_score = Column(Float, nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    trace = relationship("TraceRecord", back_populates="healing_actions")
    rca_report = relationship("RCARecord", back_populates="healing_actions")

    __table_args__ = (
        Index("ix_healing_strategy", "strategy"),
        Index("ix_healing_regression_passed", "regression_passed"),
    )


class EvaluatorMetricsRecord(Base):
    __tablename__ = "evaluator_metrics"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    evaluator_type = Column(
        SAEnum("llm_judge", "embedding_similarity", "rule_based", name="evaluator_type"),
        nullable=False,
    )
    accuracy = Column(Float, nullable=False)
    precision = Column(Float, nullable=False)
    recall = Column(Float, nullable=False)
    f1_score = Column(Float, nullable=False)
    agreement_rate = Column(Float, nullable=False)
    total_evaluations = Column(Integer, nullable=False)
    calibrated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_evaluator_metrics_type", "evaluator_type"),
    )
