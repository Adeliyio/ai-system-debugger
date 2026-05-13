"""Enriched trace schema: cost, latency_breakdown, retrieved_docs, risk_tier,
failure_type taxonomy, fix_outcomes, human_review_queue, failure_clusters.

Revision ID: 002
Revises: 001
Create Date: 2026-04-27

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    # --- New enums ---
    risk_tier = postgresql.ENUM(
        "general", "financial", "legal", "medical",
        name="risk_tier", create_type=True,
    )
    risk_tier.create(bind, checkfirst=True)

    failure_type = postgresql.ENUM(
        "none", "hallucination", "retrieval_failure", "context_loss",
        "reasoning_failure", "prompt_failure",
        name="failure_type", create_type=True,
    )
    failure_type.create(bind, checkfirst=True)

    # --- traces: add new value to trace_status enum ---
    op.execute("ALTER TYPE trace_status ADD VALUE IF NOT EXISTS 'awaiting_review'")
    # add manual_review to healing_strategy enum
    op.execute("ALTER TYPE healing_strategy ADD VALUE IF NOT EXISTS 'manual_review'")

    # --- traces: new columns ---
    op.add_column("traces", sa.Column("retrieved_docs", postgresql.JSONB(), server_default="[]"))
    op.add_column("traces", sa.Column("latency_breakdown", postgresql.JSONB(), server_default="{}"))
    op.add_column("traces", sa.Column("model_cost_usd", sa.Float(), server_default="0.0"))
    op.add_column("traces", sa.Column("evaluation_cost_usd", sa.Float(), server_default="0.0"))
    op.add_column("traces", sa.Column("total_cost_usd", sa.Float(), server_default="0.0"))
    op.add_column("traces", sa.Column("task_type", sa.String(64), nullable=True))
    op.add_column("traces", sa.Column("complexity_score", sa.Float(), nullable=True))
    op.add_column("traces", sa.Column("routing_fallback", sa.Boolean(), server_default="false"))
    op.add_column(
        "traces",
        sa.Column(
            "risk_tier",
            postgresql.ENUM(name="risk_tier", create_type=False),
            nullable=False,
            server_default="general",
        ),
    )
    op.create_index("ix_traces_risk_tier", "traces", ["risk_tier"])

    # --- evaluations: new columns ---
    op.add_column(
        "evaluations",
        sa.Column(
            "failure_type",
            postgresql.ENUM(name="failure_type", create_type=False),
            nullable=False,
            server_default="none",
        ),
    )
    op.add_column(
        "evaluations",
        sa.Column("low_confidence", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.create_index("ix_evaluations_failure_type", "evaluations", ["failure_type"])

    # --- healing_actions: escalation flag ---
    op.add_column(
        "healing_actions",
        sa.Column("escalated_to_openai", sa.Boolean(), nullable=False, server_default="false"),
    )

    # --- fix_outcomes table ---
    op.create_table(
        "fix_outcomes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "failure_source",
            postgresql.ENUM(name="failure_source", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "strategy",
            postgresql.ENUM(name="healing_strategy", create_type=False),
            nullable=False,
        ),
        sa.Column("success_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "last_updated", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.UniqueConstraint("failure_source", "strategy", name="uq_fix_outcome_pair"),
    )
    op.create_index("ix_fix_outcomes_pair", "fix_outcomes", ["failure_source", "strategy"])

    # --- human_review_queue table ---
    op.create_table(
        "human_review_queue",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "trace_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("traces.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "evaluation_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("evaluations.id", ondelete="CASCADE"), nullable=True,
        ),
        sa.Column("reason", sa.String(64), nullable=False),
        sa.Column(
            "severity",
            postgresql.ENUM(name="severity_level", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "risk_tier",
            postgresql.ENUM(name="risk_tier", create_type=False),
            nullable=False,
            server_default="general",
        ),
        sa.Column(
            "label",
            postgresql.ENUM(name="failure_type", create_type=False),
            nullable=True,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("reviewer", sa.String(255), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
    )
    op.create_index("ix_review_trace_id", "human_review_queue", ["trace_id"])
    op.create_index("ix_review_reason", "human_review_queue", ["reason"])
    op.create_index("ix_review_resolved_at", "human_review_queue", ["resolved_at"])

    # --- failure_clusters table ---
    op.create_table(
        "failure_clusters",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "failure_type",
            postgresql.ENUM(name="failure_type", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "primary_source",
            postgresql.ENUM(name="failure_source", create_type=False),
            nullable=False,
        ),
        sa.Column("prompt_fingerprint", sa.String(64), nullable=False),
        sa.Column("occurrence_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("sample_prompt", sa.Text(), nullable=False),
        sa.Column(
            "last_seen", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.UniqueConstraint(
            "failure_type", "primary_source", "prompt_fingerprint",
            name="uq_failure_cluster",
        ),
    )
    op.create_index("ix_failure_clusters_count", "failure_clusters", ["occurrence_count"])


def downgrade() -> None:
    op.drop_table("failure_clusters")
    op.drop_table("human_review_queue")
    op.drop_table("fix_outcomes")

    op.drop_column("healing_actions", "escalated_to_openai")

    op.drop_index("ix_evaluations_failure_type", table_name="evaluations")
    op.drop_column("evaluations", "low_confidence")
    op.drop_column("evaluations", "failure_type")

    op.drop_index("ix_traces_risk_tier", table_name="traces")
    op.drop_column("traces", "risk_tier")
    op.drop_column("traces", "routing_fallback")
    op.drop_column("traces", "complexity_score")
    op.drop_column("traces", "task_type")
    op.drop_column("traces", "total_cost_usd")
    op.drop_column("traces", "evaluation_cost_usd")
    op.drop_column("traces", "model_cost_usd")
    op.drop_column("traces", "latency_breakdown")
    op.drop_column("traces", "retrieved_docs")

    op.execute("DROP TYPE IF EXISTS failure_type")
    op.execute("DROP TYPE IF EXISTS risk_tier")
