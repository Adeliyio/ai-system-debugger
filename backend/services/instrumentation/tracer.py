import uuid
from datetime import datetime, timezone

import structlog
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, ConsoleSpanExporter
from opentelemetry.sdk.resources import Resource
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.models.schemas import TraceCreate, TraceResponse, TraceStatus
from backend.storage.models import TraceRecord

logger = structlog.get_logger(__name__)

# Initialize OpenTelemetry tracer
resource = Resource.create({"service.name": settings.app_name})
provider = TracerProvider(resource=resource)
provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
trace.set_tracer_provider(provider)
otel_tracer = trace.get_tracer(__name__)


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
            span.set_attribute("trace.token_count_input", trace_data.token_count_input)
            span.set_attribute("trace.token_count_output", trace_data.token_count_output)

            record = TraceRecord(
                id=trace_id,
                session_id=trace_data.session_id,
                prompt=trace_data.prompt,
                response=trace_data.response,
                model_used=trace_data.model_used,
                context_documents=trace_data.context_documents,
                latency_ms=trace_data.latency_ms,
                token_count_input=trace_data.token_count_input,
                token_count_output=trace_data.token_count_output,
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
            )

            return TraceResponse(
                id=str(trace_id),
                session_id=record.session_id,
                prompt=record.prompt,
                response=record.response,
                model_used=record.model_used,
                context_documents=record.context_documents,
                latency_ms=record.latency_ms,
                token_count_input=record.token_count_input,
                token_count_output=record.token_count_output,
                status=TraceStatus.pending,
                metadata=record.metadata_,
                created_at=record.created_at or datetime.now(timezone.utc),
            )

    async def update_trace_status(self, trace_id: str, status: TraceStatus) -> None:
        """Update the status of an existing trace."""
        record = await self.db.get(TraceRecord, trace_id)
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
        record = await self.db.get(TraceRecord, trace_id)
        if record is None:
            raise ValueError(f"Trace {trace_id} not found")

        return TraceResponse(
            id=str(record.id),
            session_id=record.session_id,
            prompt=record.prompt,
            response=record.response,
            model_used=record.model_used,
            context_documents=record.context_documents or [],
            latency_ms=record.latency_ms,
            token_count_input=record.token_count_input,
            token_count_output=record.token_count_output,
            status=TraceStatus(record.status),
            metadata=record.metadata_ or {},
            created_at=record.created_at,
        )
