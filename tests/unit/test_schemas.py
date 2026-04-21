import pytest
from pydantic import ValidationError

from backend.models.schemas import (
    TraceCreate,
    EvaluatorVerdict,
    EvaluatorType,
    RCAFinding,
    FailureSource,
    MetricsQuery,
)


class TestTraceCreateValidation:
    """Tests for TraceCreate schema validation."""

    def test_valid_trace_create(self):
        trace = TraceCreate(
            session_id="sess-001",
            prompt="Hello",
            response="World",
            model_used="gpt-4o",
            latency_ms=100.0,
            token_count_input=5,
            token_count_output=3,
        )
        assert trace.session_id == "sess-001"
        assert trace.context_documents == []
        assert trace.metadata == {}

    def test_negative_latency_rejected(self):
        with pytest.raises(ValidationError):
            TraceCreate(
                session_id="sess-001",
                prompt="Hello",
                response="World",
                model_used="gpt-4o",
                latency_ms=-1.0,
                token_count_input=5,
                token_count_output=3,
            )

    def test_negative_token_count_rejected(self):
        with pytest.raises(ValidationError):
            TraceCreate(
                session_id="sess-001",
                prompt="Hello",
                response="World",
                model_used="gpt-4o",
                latency_ms=100.0,
                token_count_input=-1,
                token_count_output=3,
            )

    def test_missing_required_fields_rejected(self):
        with pytest.raises(ValidationError):
            TraceCreate(session_id="sess-001")


class TestEvaluatorVerdictValidation:
    """Tests for EvaluatorVerdict schema validation."""

    def test_valid_verdict(self):
        verdict = EvaluatorVerdict(
            evaluator_type=EvaluatorType.llm_judge,
            passed=True,
            score=0.85,
            reasoning="Good response",
        )
        assert verdict.score == 0.85

    def test_score_out_of_range_rejected(self):
        with pytest.raises(ValidationError):
            EvaluatorVerdict(
                evaluator_type=EvaluatorType.llm_judge,
                passed=True,
                score=1.5,
                reasoning="Test",
            )

    def test_score_below_zero_rejected(self):
        with pytest.raises(ValidationError):
            EvaluatorVerdict(
                evaluator_type=EvaluatorType.llm_judge,
                passed=True,
                score=-0.1,
                reasoning="Test",
            )


class TestRCAFindingValidation:
    """Tests for RCAFinding schema validation."""

    def test_valid_finding(self):
        finding = RCAFinding(
            source=FailureSource.retrieval,
            confidence=0.85,
            evidence="No context docs",
            suggested_action="Improve retrieval",
        )
        assert finding.source == FailureSource.retrieval

    def test_confidence_out_of_range_rejected(self):
        with pytest.raises(ValidationError):
            RCAFinding(
                source=FailureSource.model,
                confidence=2.0,
                evidence="Test",
                suggested_action="Test",
            )


class TestMetricsQueryValidation:
    """Tests for MetricsQuery schema validation."""

    def test_defaults(self):
        query = MetricsQuery()
        assert query.window_hours == 24
        assert query.start_time is None
        assert query.end_time is None

    def test_window_hours_min_boundary(self):
        query = MetricsQuery(window_hours=1)
        assert query.window_hours == 1

    def test_window_hours_max_boundary(self):
        query = MetricsQuery(window_hours=720)
        assert query.window_hours == 720

    def test_window_hours_below_min_rejected(self):
        with pytest.raises(ValidationError):
            MetricsQuery(window_hours=0)
