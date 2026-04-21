import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from backend.main import app
from backend.models.schemas import TraceCreate, TraceStatus
from backend.storage.database import get_db
from backend.storage.cache import get_redis, CacheService


# --- Mock database session ---

@pytest.fixture
def mock_db():
    """Provides a mock async database session."""
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.get = AsyncMock(return_value=None)
    session.execute = AsyncMock()
    return session


# --- Mock cache service ---

@pytest.fixture
def mock_cache():
    """Provides a mock cache service."""
    cache = AsyncMock(spec=CacheService)
    cache.get.return_value = None
    cache.get_pipeline_metrics.return_value = None
    cache.get_evaluator_health.return_value = None
    cache.get_trace.return_value = None
    return cache


# --- Mock model router ---

@pytest.fixture
def mock_router():
    """Provides a mock model router."""
    router = AsyncMock()
    router.route_and_call = AsyncMock(return_value=('{"passed": true, "score": 0.85, "reasoning": "Good response"}', "gpt-4o"))
    router.call_openai = AsyncMock(return_value="Repaired response text")
    router.call_local = AsyncMock(return_value="Local model response")
    router.select_model = MagicMock(return_value="gpt-4o")
    router.score_complexity = MagicMock(return_value=0.8)
    return router


# --- Sample data fixtures ---

@pytest.fixture
def sample_trace_create():
    """Provides a sample TraceCreate object."""
    return TraceCreate(
        session_id="test-session-001",
        prompt="What is the capital of France?",
        response="The capital of France is Paris.",
        model_used="gpt-4o",
        context_documents=["France is a country in Western Europe. Its capital is Paris."],
        latency_ms=245.5,
        token_count_input=12,
        token_count_output=8,
        metadata={"source": "test"},
    )


@pytest.fixture
def sample_trace_record():
    """Provides a mock trace database record."""
    record = MagicMock()
    record.id = uuid.uuid4()
    record.session_id = "test-session-001"
    record.prompt = "What is the capital of France?"
    record.response = "The capital of France is Paris."
    record.model_used = "gpt-4o"
    record.context_documents = ["France is a country in Western Europe. Its capital is Paris."]
    record.latency_ms = 245.5
    record.token_count_input = 12
    record.token_count_output = 8
    record.status = "pending"
    record.metadata_ = {"source": "test"}
    record.created_at = datetime.now(timezone.utc)
    return record


@pytest.fixture
def sample_evaluation_record():
    """Provides a mock evaluation database record."""
    record = MagicMock()
    record.id = uuid.uuid4()
    record.trace_id = uuid.uuid4()
    record.passed = False
    record.overall_score = 0.35
    record.verdicts = [
        {"evaluator_type": "llm_judge", "passed": False, "score": 0.3, "reasoning": "Hallucinated facts"},
        {"evaluator_type": "embedding_similarity", "passed": False, "score": 0.4, "reasoning": "Low similarity"},
        {"evaluator_type": "rule_based", "passed": True, "score": 0.8, "reasoning": "All rule checks passed"},
    ]
    record.agreement_count = 2
    record.failure_detected = True
    record.severity = "high"
    record.created_at = datetime.now(timezone.utc)
    return record


@pytest.fixture
def sample_rca_record():
    """Provides a mock RCA database record."""
    record = MagicMock()
    record.id = uuid.uuid4()
    record.trace_id = uuid.uuid4()
    record.evaluation_id = uuid.uuid4()
    record.primary_source = "retrieval"
    record.findings = [
        {
            "source": "retrieval",
            "confidence": 0.85,
            "evidence": "No context documents provided",
            "suggested_action": "Improve retrieval query",
        }
    ]
    record.analysis_summary = "Primary failure due to missing retrieval context."
    record.created_at = datetime.now(timezone.utc)
    return record


# --- Test client ---

@pytest.fixture
def override_deps(mock_db, mock_cache):
    """Override FastAPI dependencies for testing."""
    async def _mock_get_db():
        yield mock_db

    async def _mock_get_redis():
        return AsyncMock()

    app.dependency_overrides[get_db] = _mock_get_db
    yield
    app.dependency_overrides.clear()


@pytest.fixture
async def client(override_deps):
    """Provides an async test client for the FastAPI app."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
