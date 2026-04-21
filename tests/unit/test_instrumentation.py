import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.services.instrumentation.tracer import InstrumentationService
from backend.models.schemas import TraceCreate, TraceStatus


class TestInstrumentationService:
    """Tests for trace capture and retrieval."""

    @pytest.mark.asyncio
    async def test_capture_trace_creates_record(self, mock_db, sample_trace_create):
        service = InstrumentationService(mock_db)

        result = await service.capture_trace(sample_trace_create)

        assert result.session_id == sample_trace_create.session_id
        assert result.prompt == sample_trace_create.prompt
        assert result.response == sample_trace_create.response
        assert result.model_used == sample_trace_create.model_used
        assert result.status == TraceStatus.pending
        assert result.latency_ms == sample_trace_create.latency_ms
        mock_db.add.assert_called_once()
        mock_db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_capture_trace_preserves_metadata(self, mock_db, sample_trace_create):
        service = InstrumentationService(mock_db)

        result = await service.capture_trace(sample_trace_create)

        assert result.metadata == {"source": "test"}

    @pytest.mark.asyncio
    async def test_capture_trace_preserves_context_documents(self, mock_db, sample_trace_create):
        service = InstrumentationService(mock_db)

        result = await service.capture_trace(sample_trace_create)

        assert len(result.context_documents) == 1
        assert "France" in result.context_documents[0]

    @pytest.mark.asyncio
    async def test_get_trace_returns_response(self, mock_db, sample_trace_record):
        mock_db.get.return_value = sample_trace_record

        service = InstrumentationService(mock_db)
        result = await service.get_trace(str(sample_trace_record.id))

        assert result.id == str(sample_trace_record.id)
        assert result.prompt == sample_trace_record.prompt

    @pytest.mark.asyncio
    async def test_get_trace_raises_for_missing(self, mock_db):
        mock_db.get.return_value = None

        service = InstrumentationService(mock_db)
        with pytest.raises(ValueError, match="not found"):
            await service.get_trace("nonexistent-id")

    @pytest.mark.asyncio
    async def test_update_trace_status(self, mock_db, sample_trace_record):
        mock_db.get.return_value = sample_trace_record

        service = InstrumentationService(mock_db)
        await service.update_trace_status(str(sample_trace_record.id), TraceStatus.analyzed)

        assert sample_trace_record.status == "analyzed"
        mock_db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_update_status_raises_for_missing(self, mock_db):
        mock_db.get.return_value = None

        service = InstrumentationService(mock_db)
        with pytest.raises(ValueError, match="not found"):
            await service.update_trace_status("nonexistent", TraceStatus.failed)
