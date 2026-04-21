import pytest
from unittest.mock import AsyncMock, MagicMock

from backend.services.rca.analyzer import RCAService
from backend.models.schemas import RCARequest, FailureSource


class TestRCAHeuristicAnalysis:
    """Tests for the heuristic signal detection in RCA."""

    def setup_method(self):
        self.service = RCAService(db=AsyncMock(), router=AsyncMock())

    def test_detects_retrieval_failure_when_no_context(self):
        trace = MagicMock()
        trace.context_documents = []
        trace.prompt = "What is X?"
        trace.response = "I don't know."

        evaluation = MagicMock()
        evaluation.verdicts = [
            {"reasoning": "No supporting evidence found in context"}
        ]

        findings = self.service._heuristic_analysis(trace, evaluation)

        retrieval_findings = [f for f in findings if f.source == FailureSource.retrieval]
        assert len(retrieval_findings) > 0
        assert retrieval_findings[0].confidence >= 0.7

    def test_detects_prompt_signals(self):
        trace = MagicMock()
        trace.context_documents = ["some context"]
        trace.prompt = "Tell me stuff"
        trace.response = "Here is some stuff."

        evaluation = MagicMock()
        evaluation.verdicts = [
            {"reasoning": "ambiguous question with unclear instruction and missing constraints"}
        ]

        findings = self.service._heuristic_analysis(trace, evaluation)

        prompt_findings = [f for f in findings if f.source == FailureSource.prompt]
        assert len(prompt_findings) > 0

    def test_detects_model_hallucination_signals(self):
        trace = MagicMock()
        trace.context_documents = ["Valid context here"]
        trace.prompt = "What happened?"
        trace.response = "Something happened."

        evaluation = MagicMock()
        evaluation.verdicts = [
            {"reasoning": "hallucination detected, fabricated information, confident but wrong"}
        ]

        findings = self.service._heuristic_analysis(trace, evaluation)

        model_findings = [f for f in findings if f.source == FailureSource.model]
        assert len(model_findings) > 0

    def test_detects_context_insufficiency(self):
        trace = MagicMock()
        trace.context_documents = ["short"]
        trace.prompt = "Detailed question about a complex topic"
        trace.response = "Brief answer."

        evaluation = MagicMock()
        evaluation.verdicts = [
            {"reasoning": "insufficient context, context too short, missing key details"}
        ]

        findings = self.service._heuristic_analysis(trace, evaluation)

        context_findings = [f for f in findings if f.source == FailureSource.context]
        assert len(context_findings) > 0

    def test_no_findings_for_clean_evaluation(self):
        trace = MagicMock()
        trace.context_documents = ["Relevant context document with details."]
        trace.prompt = "What is X?"
        trace.response = "X is a well-known concept."

        evaluation = MagicMock()
        evaluation.verdicts = [
            {"reasoning": "Good response, accurate and well-grounded."}
        ]

        findings = self.service._heuristic_analysis(trace, evaluation)

        # Should have no or very few findings
        high_confidence = [f for f in findings if f.confidence > 0.5]
        assert len(high_confidence) == 0


class TestRCAPrimarySourceDetermination:
    """Tests for determining the primary failure source."""

    def setup_method(self):
        self.service = RCAService(db=AsyncMock(), router=AsyncMock())

    def test_highest_aggregate_confidence_wins(self):
        from backend.models.schemas import RCAFinding

        findings = [
            RCAFinding(source=FailureSource.retrieval, confidence=0.9, evidence="test", suggested_action="fix"),
            RCAFinding(source=FailureSource.prompt, confidence=0.3, evidence="test", suggested_action="fix"),
            RCAFinding(source=FailureSource.retrieval, confidence=0.5, evidence="test", suggested_action="fix"),
        ]

        primary = self.service._determine_primary_source(findings)
        assert primary == FailureSource.retrieval

    def test_returns_unknown_for_empty_findings(self):
        primary = self.service._determine_primary_source([])
        assert primary == FailureSource.unknown


class TestRCAFullPipeline:
    """Integration-style tests for the full RCA flow."""

    @pytest.mark.asyncio
    async def test_analyze_returns_complete_report(
        self, mock_db, mock_router, sample_trace_record, sample_evaluation_record
    ):
        mock_db.get.side_effect = [sample_trace_record, sample_evaluation_record]

        # Mock LLM analysis response
        mock_router.route_and_call.side_effect = [
            ('[{"source": "retrieval", "confidence": 0.8, "evidence": "Missing docs", "suggested_action": "Add more docs"}]', "gpt-4o"),
            ("Primary failure is due to missing retrieval context.", "llama3.2"),
        ]

        service = RCAService(mock_db, mock_router)
        result = await service.analyze(
            RCARequest(
                trace_id=str(sample_trace_record.id),
                evaluation_id=str(sample_evaluation_record.id),
            )
        )

        assert result.primary_source is not None
        assert len(result.findings) > 0
        assert result.analysis_summary != ""
        mock_db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_analyze_raises_for_missing_trace(self, mock_db, mock_router):
        mock_db.get.return_value = None

        service = RCAService(mock_db, mock_router)
        with pytest.raises(ValueError, match="Trace"):
            await service.analyze(
                RCARequest(trace_id="missing", evaluation_id="missing")
            )
