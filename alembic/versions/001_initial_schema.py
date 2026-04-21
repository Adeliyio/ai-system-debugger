"""Initial schema - traces, evaluations, RCA, healing, evaluator metrics

Revision ID: 001
Revises:
Create Date: 2026-04-21

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Enum types ---
    trace_status = postgresql.ENUM(
        "pending", "analyzed", "failed", "healed",
        name="trace_status", create_type=True,
    )
    severity_level = postgresql.ENUM(
        "low", "medium", "high", "critical",
        name="severity_level", create_type=True,
    )
    failure_source = postgresql.ENUM(
        "retrieval", "prompt", "model", "context", "unknown",
        name="failure_source", create_type=True,
    )
    healing_strategy = postgresql.ENUM(
        "prompt_repair", "retrieval_correction", "model_reroute", "context_enrichment",
        name="healing_strategy", create_type=True,
    )
    evaluator_type = postgresql.ENUM(
        "llm_judge", "embedding_similarity", "rule_based",
        name="evaluator_type", create_type=True,
    )

    # Create enums
    trace_status.create(op.get_bind(), checkfirst=True)
    severity_level.create(op.get_bind(), checkfirst=True)
    failure_source.create(op.get_bind(), checkfirst=True)
    healing_strategy.create(op.get_bind(), checkfirst=True)
    evaluator_type.create(op.get_bind(), checkfirst=True)

    # --- Traces table ---
    op.create_table(
        "traces",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", sa.String(255), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("response", sa.Text(), nullable=False),
        sa.Column("model_used", sa.String(100), nullable=False),
        sa.Column("context_documents", postgresql.ARRAY(sa.Text()), server_default="{}"),
        sa.Column("latency_ms", sa.Float(), nullable=False),
        sa.Column("token_count_input", sa.Integer(), nullable=False),
        sa.Column("token_count_output", sa.Integer(), nullable=False),
        sa.Column("status", trace_status, nullable=False, server_default="pending"),
        sa.Column("metadata", postgresql.JSONB(), server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_traces_session_id", "traces", ["session_id"])
    op.create_index("ix_traces_created_at", "traces", ["created_at"])
    op.create_index("ix_traces_status", "traces", ["status"])
    op.create_index("ix_traces_model_used", "traces", ["model_used"])

    # --- Evaluations table ---
    op.create_table(
        "evaluations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("trace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("traces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("overall_score", sa.Float(), nullable=False),
        sa.Column("verdicts", postgresql.JSONB(), nullable=False),
        sa.Column("agreement_count", sa.Integer(), nullable=False),
        sa.Column("failure_detected", sa.Boolean(), nullable=False),
        sa.Column("severity", severity_level, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_evaluations_trace_id", "evaluations", ["trace_id"])
    op.create_index("ix_evaluations_created_at", "evaluations", ["created_at"])
    op.create_index("ix_evaluations_failure_detected", "evaluations", ["failure_detected"])

    # --- RCA reports table ---
    op.create_table(
        "rca_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("trace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("traces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("evaluation_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("evaluations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("primary_source", failure_source, nullable=False),
        sa.Column("findings", postgresql.JSONB(), nullable=False),
        sa.Column("analysis_summary", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_rca_trace_id", "rca_reports", ["trace_id"])
    op.create_index("ix_rca_evaluation_id", "rca_reports", ["evaluation_id"])
    op.create_index("ix_rca_primary_source", "rca_reports", ["primary_source"])

    # --- Healing actions table ---
    op.create_table(
        "healing_actions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("trace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("traces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rca_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("rca_reports.id", ondelete="CASCADE"), nullable=False),
        sa.Column("strategy", healing_strategy, nullable=False),
        sa.Column("original_response", sa.Text(), nullable=False),
        sa.Column("repaired_response", sa.Text(), nullable=False),
        sa.Column("repair_prompt", sa.Text(), nullable=True),
        sa.Column("attempt_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("regression_passed", sa.Boolean(), nullable=False),
        sa.Column("regression_results", postgresql.JSONB(), server_default="[]"),
        sa.Column("improvement_score", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_healing_trace_id", "healing_actions", ["trace_id"])
    op.create_index("ix_healing_rca_id", "healing_actions", ["rca_id"])
    op.create_index("ix_healing_strategy", "healing_actions", ["strategy"])
    op.create_index("ix_healing_regression_passed", "healing_actions", ["regression_passed"])

    # --- Evaluator metrics table ---
    op.create_table(
        "evaluator_metrics",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("evaluator_type", evaluator_type, nullable=False),
        sa.Column("accuracy", sa.Float(), nullable=False),
        sa.Column("precision", sa.Float(), nullable=False),
        sa.Column("recall", sa.Float(), nullable=False),
        sa.Column("f1_score", sa.Float(), nullable=False),
        sa.Column("agreement_rate", sa.Float(), nullable=False),
        sa.Column("total_evaluations", sa.Integer(), nullable=False),
        sa.Column("calibrated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_evaluator_metrics_type", "evaluator_metrics", ["evaluator_type"])


def downgrade() -> None:
    op.drop_table("evaluator_metrics")
    op.drop_table("healing_actions")
    op.drop_table("rca_reports")
    op.drop_table("evaluations")
    op.drop_table("traces")

    op.execute("DROP TYPE IF EXISTS evaluator_type")
    op.execute("DROP TYPE IF EXISTS healing_strategy")
    op.execute("DROP TYPE IF EXISTS failure_source")
    op.execute("DROP TYPE IF EXISTS severity_level")
    op.execute("DROP TYPE IF EXISTS trace_status")
