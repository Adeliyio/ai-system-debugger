import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, ConsoleSpanExporter
from opentelemetry.sdk.resources import Resource
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.models.schemas import (
    TraceCreate,
    TraceResponse,
    TraceStatus,
    RetrievedDocument,
    LatencyBreakdown,
    CostBreakdown,
    RiskTier,
)
from backend.storage.models import TraceRecord

logger = structlog.get_logger(__name__)

# Initialize OpenTelemetry tracer
resource = Resource.create({"service.name": settings.app_name})
provider = TracerProvider(resource=resource)
provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
trace.set_tracer_provider(provider)
otel_tracer = trace.get_tracer(__name__)


def _coerce_uuid(value: Any) -> uuid.UUID:
    """Convert string or UUID input to uuid.UUID for db.get lookups."""
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))


def _build_retrieved_docs(trace_data: TraceCreate) -> list[dict]:
    """Use retrieved_docs if provided; otherwise synthesize from context_documents."""
    if trace_data.retrieved_docs:
        return [d.model_dump() for d in trace_data.retrieved_docs]
    return [
        {"id": f"doc_{i}", "content": doc, "similarity_score": 0.0}
        for i, doc in enumerate(trace_data.context_documents)
    ]


def _record_to_response(record: TraceRecord) -> TraceResponse:
    """Map a TraceRecord ORM row to a TraceResponse Pydantic model."""
    retrieved = record.retrieved_docs or []
    retrieved_docs_models = [RetrievedDocument(**d) for d in retrieved]

    latency_bd = None
    if record.latency_breakdown:
        latency_bd = LatencyBreakdown(**record.latency_breakdown)

    cost = None
    if (record.model_cost_usd or 0) or (record.evaluation_cost_usd or 0) or (record.total_cost_usd or 0):
        cost = CostBreakdown(
            input_tokens=record.token_count_input,
            output_tokens=record.token_count_output,
            model_cost_usd=record.model_cost_usd or 0.0,
            evaluation_cost_usd=record.evaluation_cost_usd or 0.0,
            total_cost_usd=record.total_cost_usd or 0.0,
        )

    return TraceResponse(
        id=str(record.id),
        session_id=record.session_id,
        prompt=record.prompt,
        response=record.response,
        model_used=record.model_used,
        context_documents=record.context_documents or [],
        retrieved_docs=retrieved_docs_models,
        latency_ms=record.latency_ms,
        latency_breakdown=latency_bd,
        token_count_input=record.token_count_input,
        token_count_output=record.token_count_output,
        cost=cost,
        task_type=record.task_type,
        complexity_score=record.complexity_score,
        routing_fallback=bool(record.routing_fallback),
        risk_tier=RiskTier(record.risk_tier),
        status=TraceStatus(record.status),
        metadata=record.metadata_ or {},
        created_at=record.created_at or datetime.now(timezone.utc),
    )


class InstrumentationService:
    """Captures and stores structured traces from AI system interactions."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def capture_trace(self, trace_data: TraceCreate) -> TraceResponse:
        """Record a new AI interaction trace with full context."""
        with otel_tracer.start_as_current_span("capture_trace") as span:
            trace_id = uuid.uuid4()

            span.set_attribute("trace.session_id", trace_data.session_id)
            span.set_attribute("trace.model_used", trace_data.model_used)
            span.set_attribute("trace.latency_ms", trace_data.latency_ms)

            cost = trace_data.cost or CostBreakdown(
                input_tokens=trace_data.token_count_input,
                output_tokens=trace_data.token_count_output,
            )

            record = TraceRecord(
                id=trace_id,
                session_id=trace_data.session_id,
                prompt=trace_data.prompt,
                response=trace_data.response,
                model_used=trace_data.model_used,
                context_documents=trace_data.context_documents,
                retrieved_docs=_build_retrieved_docs(trace_data),
                latency_ms=trace_data.latency_ms,
                latency_breakdown=(
                    trace_data.latency_breakdown.model_dump()
                    if trace_data.latency_breakdown
                    else {}
                ),
                token_count_input=trace_data.token_count_input,
                token_count_output=trace_data.token_count_output,
                model_cost_usd=cost.model_cost_usd,
                evaluation_cost_usd=cost.evaluation_cost_usd,
                total_cost_usd=cost.total_cost_usd,
                task_type=trace_data.task_type,
                complexity_score=trace_data.complexity_score,
                routing_fallback=trace_data.routing_fallback,
                risk_tier=trace_data.risk_tier.value,
                status="pending",
                metadata_=trace_data.metadata,
            )

            self.db.add(record)
            await self.db.flush()

            logger.info(
                "trace_captured",
                trace_id=str(trace_id),
                session_id=trace_data.session_id,
                model=trace_data.model_used,
                latency_ms=trace_data.latency_ms,
                risk_tier=trace_data.risk_tier.value,
            )

            return _record_to_response(record)

    async def update_trace_status(self, trace_id: str, status: TraceStatus) -> None:
        """Update the status of an existing trace."""
        record = await self.db.get(TraceRecord, _coerce_uuid(trace_id))
        if record is None:
            raise ValueError(f"Trace {trace_id} not found")

        record.status = status.value
        await self.db.flush()

        logger.info(
            "trace_status_updated",
            trace_id=trace_id,
            new_status=status.value,
        )

    async def get_trace(self, trace_id: str) -> TraceResponse:
        """Retrieve a trace by ID."""
        record = await self.db.get(TraceRecord, _coerce_uuid(trace_id))
        if record is None:
            raise ValueError(f"Trace {trace_id} not found")
        return _record_to_response(record)
