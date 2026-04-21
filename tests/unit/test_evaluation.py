import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.services.evaluation.evaluator import (
    RuleBasedEvaluator,
    EmbeddingSimilarityEvaluator,
    EvaluationService,
)
from backend.models.schemas import EvaluatorType, EvaluationRequest


class TestRuleBasedEvaluator:
    """Tests for the deterministic rule-based evaluator."""

    def setup_method(self):
        self.evaluator = RuleBasedEvaluator()

    def test_passes_for_valid_response(self):
        verdict = self.evaluator.evaluate(
            prompt="What is Python?",
            response="Python is a high-level programming language known for its readability and versatility.",
            context_documents=[],
        )
        assert verdict.passed is True
        assert verdict.score >= 0.5
        assert verdict.evaluator_type == EvaluatorType.rule_based

    def test_fails_for_empty_response(self):
        verdict = self.evaluator.evaluate(
            prompt="What is Python?",
            response="",
            context_documents=[],
        )
        assert verdict.passed is False
        assert verdict.score < 0.5

    def test_fails_for_very_short_response(self):
        verdict = self.evaluator.evaluate(
            prompt="What is Python?",
            response="idk",
            context_documents=[],
        )
        assert verdict.passed is False

    def test_detects_refusal_patterns(self):
        verdict = self.evaluator.evaluate(
            prompt="Tell me about quantum computing",
            response="I apologize, but I cannot provide information about that topic.",
            context_documents=[],
        )
        assert verdict.passed is False
        assert "refusal" in verdict.reasoning.lower()

    def test_detects_ai_deflection(self):
        verdict = self.evaluator.evaluate(
            prompt="Explain gravity",
            response="As an AI, I don't have access to real-time data to answer this.",
            context_documents=[],
        )
        assert verdict.passed is False

    def test_detects_repetition(self):
        verdict = self.evaluator.evaluate(
            prompt="Tell me something",
            response="The answer is yes. The answer is yes. The answer is yes. The answer is yes. The answer is yes.",
            context_documents=[],
        )
        assert verdict.score < 1.0
        assert "repetition" in verdict.reasoning.lower()

    def test_detects_disproportionately_short_response(self):
        long_prompt = "Please provide a detailed analysis of the economic impact of climate change on developing nations, including specific examples and data points from recent studies."
        verdict = self.evaluator.evaluate(
            prompt=long_prompt,
            response="Yes.",
            context_documents=[],
        )
        assert verdict.passed is False

    def test_full_score_for_good_response(self):
        verdict = self.evaluator.evaluate(
            prompt="What is 2+2?",
            response="The result of 2+2 is 4. This is a basic arithmetic addition.",
            context_documents=[],
        )
        assert verdict.score == 1.0
        assert "All rule checks passed" in verdict.reasoning


class TestEmbeddingSimilarityEvaluator:
    """Tests for the embedding-based evaluator."""

    def setup_method(self):
        self.evaluator = EmbeddingSimilarityEvaluator()

    def test_high_similarity_for_relevant_response(self):
        verdict = self.evaluator.evaluate(
            prompt="What is the capital of France?",
            response="The capital of France is Paris, a major European city.",
            context_documents=["France is a country in Europe. Paris is its capital city."],
        )
        assert verdict.score > 0.5
        assert verdict.evaluator_type == EvaluatorType.embedding_similarity

    def test_lower_similarity_for_irrelevant_response(self):
        verdict = self.evaluator.evaluate(
            prompt="What is the capital of France?",
            response="Bananas are a popular fruit grown in tropical regions worldwide.",
            context_documents=[],
        )
        relevant_verdict = self.evaluator.evaluate(
            prompt="What is the capital of France?",
            response="Paris is the capital of France.",
            context_documents=[],
        )
        assert relevant_verdict.score > verdict.score

    def test_reference_comparison_boosts_accuracy(self):
        verdict = self.evaluator.evaluate(
            prompt="What is 2+2?",
            response="The answer is 4.",
            context_documents=[],
            reference="2+2 equals 4.",
        )
        assert verdict.score > 0.5
        assert "Accuracy" in verdict.reasoning


class TestEvaluationService:
    """Tests for the ensemble evaluation orchestrator."""

    @pytest.mark.asyncio
    async def test_majority_pass_means_overall_pass(self, mock_db, mock_router, sample_trace_record):
        """If 2 out of 3 evaluators pass, overall should pass."""
        mock_db.get.return_value = sample_trace_record

        # Mock LLM judge to return pass
        mock_router.route_and_call.return_value = (
            '{"passed": true, "score": 0.9, "reasoning": "Excellent response"}',
            "gpt-4o",
        )

        service = EvaluationService(mock_db, mock_router)
        result = await service.evaluate_trace(
            EvaluationRequest(trace_id=str(sample_trace_record.id))
        )

        assert result.passed is True
        assert len(result.verdicts) == 3
        assert result.agreement_count >= 2

    @pytest.mark.asyncio
    async def test_trace_not_found_raises_error(self, mock_db, mock_router):
        """Should raise ValueError for non-existent trace."""
        mock_db.get.return_value = None

        service = EvaluationService(mock_db, mock_router)
        with pytest.raises(ValueError, match="not found"):
            await service.evaluate_trace(
                EvaluationRequest(trace_id="nonexistent-id")
            )

    @pytest.mark.asyncio
    async def test_severity_classification(self, mock_db, mock_router, sample_trace_record):
        """Low overall scores should produce higher severity."""
        mock_db.get.return_value = sample_trace_record

        # Mock LLM judge to return failure
        mock_router.route_and_call.return_value = (
            '{"passed": false, "score": 0.1, "reasoning": "Completely wrong"}',
            "gpt-4o",
        )

        # Override response to trigger rule failures too
        sample_trace_record.response = ""

        service = EvaluationService(mock_db, mock_router)
        result = await service.evaluate_trace(
            EvaluationRequest(trace_id=str(sample_trace_record.id))
        )

        assert result.failure_detected is True
        assert result.severity.value in ("high", "critical")
