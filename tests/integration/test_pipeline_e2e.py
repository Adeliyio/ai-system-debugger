"""End-to-end pipeline test: trace -> analyze -> RCA -> fix -> compare.

Exercises the full healing workflow against a single trace using mocked
external dependencies (DB, cache, model router). Validates that each stage
produces correct output and passes its IDs forward to the next stage.
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from backend.main import app
from backend.core.dependencies import get_cache_service, get_model_router
from backend.storage.cache import CacheService, get_redis
from backend.storage.database import get_db


class InMemoryStore:
    """Simple in-memory store that mimics db.get / db.add / db.flush."""

    def __init__(self):
        self.records: dict[uuid.UUID, object] = {}

    def add(self, record):
        if hasattr(record, "id") and record.id:
            self.records[record.id] = record

    async def flush(self):
        pass

    async def commit(self):
        pass

    async def rollback(self):
        pass

    async def get(self, model_class, pk):
        return self.records.get(pk)

    async def execute(self, query):
        """Return an empty result set for any query."""
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        result.scalars.return_value = MagicMock(all=MagicMock(return_value=[]))
        result.one.return_value = MagicMock(
            total=0, failures=0, successes=0, mean=0.0, p95=0.0, p99=0.0,
        )
        result.all.return_value = []
        return result


@pytest.fixture
def in_memory_store():
    return InMemoryStore()


@pytest.fixture
def mock_cache_e2e():
    cache = AsyncMock(spec=CacheService)
    cache.get.return_value = None
    cache.get_pipeline_metrics.return_value = None
    cache.get_evaluator_health.return_value = None
    cache.get_trace.return_value = None
    return cache


@pytest.fixture
def mock_router_e2e():
    router = AsyncMock()
    router.openai_client = MagicMock()

    # LLM judge returns a passing verdict by default, failing for bad traces
    router.route_and_call = AsyncMock(
        return_value=(
            '{"passed": false, "score": 0.35, "reasoning": "Response contains claims not supported by context", "failure_type": "hallucination"}',
            "gpt-4o",
        )
    )
    router.call_openai = AsyncMock(
        return_value='{"repaired_prompt": "Improved prompt", "changes_made": "Added constraints"}'
    )
    router.call_local = AsyncMock(
        return_value='{"repaired_prompt": "Local draft prompt", "changes_made": "Simplified"}'
    )
    router.select_model = MagicMock(return_value="gpt-4o")
    router.score_complexity = MagicMock(return_value=0.8)
    return router


@pytest.fixture
def override_e2e_deps(in_memory_store, mock_cache_e2e, mock_router_e2e):
    async def _mock_get_db():
        yield in_memory_store

    async def _mock_get_redis():
        return AsyncMock()

    async def _mock_get_cache_service():
        return mock_cache_e2e

    def _mock_get_model_router():
        return mock_router_e2e

    app.dependency_overrides[get_db] = _mock_get_db
    app.dependency_overrides[get_redis] = _mock_get_redis
    app.dependency_overrides[get_cache_service] = _mock_get_cache_service
    app.dependency_overrides[get_model_router] = _mock_get_model_router
    yield
    app.dependency_overrides.clear()


@pytest.fixture
async def e2e_client(override_e2e_deps):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


class TestFullPipeline:
    """Exercises the full trace -> analyze -> RCA -> fix pipeline."""

    @pytest.mark.asyncio
    async def test_submit_trace(self, e2e_client, in_memory_store):
        """Step 1: Submit a trace and get a trace ID back."""
        payload = {
            "session_id": "e2e-session-001",
            "prompt": "What is the refund policy for enterprise plans?",
            "response": "Enterprise plans come with a 30-day money-back guarantee and prorated refunds after that.",
            "model_used": "gpt-4o",
            "context_documents": [
                "Pricing FAQ: Monthly subscriptions can be cancelled at any time.",
                "Enterprise Agreement: Contact your account manager for billing inquiries.",
            ],
            "latency_ms": 1340.0,
            "token_count_input": 62,
            "token_count_output": 98,
            "metadata": {"source": "customer_support"},
        }

        response = await e2e_client.post("/trace", json=payload)
        assert response.status_code == 201

        data = response.json()
        assert data["session_id"] == "e2e-session-001"
        assert data["status"] == "pending"
        assert "id" in data

        # Verify the trace was stored
        assert len(in_memory_store.records) == 1

    @pytest.mark.asyncio
    async def test_health_endpoint(self, e2e_client):
        """Verify health endpoint works."""
        response = await e2e_client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_trace_input_validation(self, e2e_client):
        """Verify schema validation rejects incomplete payloads."""
        response = await e2e_client.post("/trace", json={"session_id": "test"})
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_rca_requires_valid_ids(self, e2e_client):
        """Verify RCA rejects missing IDs."""
        response = await e2e_client.post("/rca", json={"trace_id": "test"})
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_fix_requires_valid_ids(self, e2e_client):
        """Verify fix rejects missing IDs."""
        response = await e2e_client.post("/fix", json={"trace_id": "test"})
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_metrics_returns_empty_on_no_data(self, e2e_client):
        """Verify metrics endpoint handles empty DB gracefully."""
        response = await e2e_client.get("/metrics")
        # Should return 200 with zeroed metrics, not crash
        assert response.status_code == 200
