import uuid
import json
from datetime import datetime, timezone

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.models.schemas import (
    RCARequest,
    RCAResponse,
    RCAFinding,
    FailureSource,
    EvaluatorType,
)
from backend.storage.models import TraceRecord, EvaluationRecord, RCARecord
from backend.services.routing import ModelRouter, TaskType

logger = structlog.get_logger(__name__)

# Failure signal patterns mapped to root cause sources
RETRIEVAL_SIGNALS = [
    "context not relevant", "missing information", "no supporting evidence",
    "context doesn't address", "retrieved documents unrelated",
]

PROMPT_SIGNALS = [
    "ambiguous question", "unclear instruction", "contradictory requirements",
    "missing constraints", "prompt too vague",
]

MODEL_SIGNALS = [
    "hallucination", "fabricated", "incorrect reasoning", "logical error",
    "confident but wrong", "unsupported claim",
]

CONTEXT_SIGNALS = [
    "insufficient context", "context too short", "missing key details",
    "outdated information", "context window exceeded",
]


class RCAService:
    """Root Cause Analysis engine that diagnoses why an AI system response failed.

    Uses a combination of heuristic signal detection and LLM-powered analysis
    to classify failures into: retrieval, prompt, model, or context issues.
    """

    def __init__(self, db: AsyncSession, router: ModelRouter):
        self.db = db
        self.router = router

    async def analyze(self, request: RCARequest) -> RCAResponse:
        """Perform root cause analysis on a failed trace."""
        trace = await self.db.get(TraceRecord, request.trace_id)
        if trace is None:
            raise ValueError(f"Trace {request.trace_id} not found")

        evaluation = await self.db.get(EvaluationRecord, request.evaluation_id)
        if evaluation is None:
            raise ValueError(f"Evaluation {request.evaluation_id} not found")

        # Step 1: Heuristic signal analysis
        heuristic_findings = self._heuristic_analysis(trace, evaluation)

        # Step 2: LLM-powered deep analysis
        llm_findings = await self._llm_analysis(trace, evaluation)

        # Step 3: Merge and rank findings
        all_findings = heuristic_findings + llm_findings
        all_findings.sort(key=lambda f: f.confidence, reverse=True)

        # Determine primary source
        primary_source = self._determine_primary_source(all_findings)

        # Generate analysis summary
        summary = await self._generate_summary(trace, all_findings, primary_source)

        # Persist RCA report
        rca_id = uuid.uuid4()
        record = RCARecord(
            id=rca_id,
            trace_id=trace.id,
            evaluation_id=evaluation.id,
            primary_source=primary_source.value,
            findings=[f.model_dump() for f in all_findings],
            analysis_summary=summary,
        )
        self.db.add(record)
        await self.db.flush()

        logger.info(
            "rca_completed",
            trace_id=str(trace.id),
            primary_source=primary_source.value,
            findings_count=len(all_findings),
        )

        return RCAResponse(
            id=str(rca_id),
            trace_id=str(trace.id),
            evaluation_id=str(evaluation.id),
            primary_source=primary_source,
            findings=all_findings,
            analysis_summary=summary,
            created_at=record.created_at or datetime.now(timezone.utc),
        )

    def _heuristic_analysis(
        self,
        trace: TraceRecord,
        evaluation: EvaluationRecord,
    ) -> list[RCAFinding]:
        """Apply heuristic rules to detect failure signals."""
        findings = []
        verdicts = evaluation.verdicts or []
        all_reasoning = " ".join(
            v.get("reasoning", "") for v in verdicts
        ).lower()

        # Check retrieval signals
        retrieval_hits = sum(
            1 for signal in RETRIEVAL_SIGNALS if signal in all_reasoning
        )
        if retrieval_hits > 0 or not trace.context_documents:
            confidence = min(0.4 + retrieval_hits * 0.15, 0.85)
            if not trace.context_documents:
                confidence = max(confidence, 0.7)
            findings.append(RCAFinding(
                source=FailureSource.retrieval,
                confidence=round(confidence, 2),
                evidence=(
                    f"Retrieval signals detected: {retrieval_hits} pattern matches. "
                    + ("No context documents provided." if not trace.context_documents else "")
                ),
                suggested_action="Improve retrieval query, expand document corpus, or adjust similarity threshold",
            ))

        # Check prompt signals
        prompt_hits = sum(
            1 for signal in PROMPT_SIGNALS if signal in all_reasoning
        )
        if prompt_hits > 0:
            findings.append(RCAFinding(
                source=FailureSource.prompt,
                confidence=round(min(0.3 + prompt_hits * 0.15, 0.8), 2),
                evidence=f"Prompt quality signals detected: {prompt_hits} pattern matches",
                suggested_action="Refine prompt template with clearer instructions and constraints",
            ))

        # Check model signals
        model_hits = sum(
            1 for signal in MODEL_SIGNALS if signal in all_reasoning
        )
        if model_hits > 0:
            findings.append(RCAFinding(
                source=FailureSource.model,
                confidence=round(min(0.3 + model_hits * 0.15, 0.8), 2),
                evidence=f"Model capability signals detected: {model_hits} pattern matches",
                suggested_action="Consider routing to a more capable model or adjusting temperature",
            ))

        # Check context signals
        context_hits = sum(
            1 for signal in CONTEXT_SIGNALS if signal in all_reasoning
        )
        if context_hits > 0 or (
            trace.context_documents and len(trace.context_documents) < 2
        ):
            confidence = min(0.3 + context_hits * 0.15, 0.8)
            if trace.context_documents and len(trace.context_documents) < 2:
                confidence = max(confidence, 0.5)
            findings.append(RCAFinding(
                source=FailureSource.context,
                confidence=round(confidence, 2),
                evidence=(
                    f"Context signals detected: {context_hits} pattern matches. "
                    f"Context docs provided: {len(trace.context_documents or [])}"
                ),
                suggested_action="Enrich context with additional relevant documents or metadata",
            ))

        return findings

    async def _llm_analysis(
        self,
        trace: TraceRecord,
        evaluation: EvaluationRecord,
    ) -> list[RCAFinding]:
        """Use LLM to perform deeper root cause analysis."""
        system_prompt = (
            "You are a root cause analysis expert for AI systems. "
            "Given a failed AI interaction, identify the most likely root cause. "
            "Classify into: retrieval (bad/missing context docs), prompt (unclear/ambiguous prompt), "
            "model (hallucination/reasoning error), or context (insufficient/outdated context). "
            "Return a JSON array of findings: "
            '[{"source": "...", "confidence": 0.0-1.0, "evidence": "...", "suggested_action": "..."}]'
        )

        analysis_prompt = (
            f"Failed AI interaction analysis:\n\n"
            f"Prompt: {trace.prompt[:1000]}\n\n"
            f"Response: {trace.response[:1000]}\n\n"
            f"Context documents: {len(trace.context_documents or [])} provided\n\n"
            f"Evaluation verdicts: {json.dumps(evaluation.verdicts, indent=2)[:1500]}\n\n"
            f"Identify root causes. Return JSON array only."
        )

        try:
            result, _ = await self.router.route_and_call(
                analysis_prompt,
                TaskType.rca,
                system_prompt=system_prompt,
                temperature=0.0,
            )

            parsed = json.loads(result)
            findings = []
            for item in parsed:
                source = item.get("source", "unknown")
                if source not in [e.value for e in FailureSource]:
                    source = "unknown"
                findings.append(RCAFinding(
                    source=FailureSource(source),
                    confidence=max(0.0, min(1.0, item.get("confidence", 0.5))),
                    evidence=item.get("evidence", "LLM analysis"),
                    suggested_action=item.get("suggested_action", "Review manually"),
                ))
            return findings

        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning("llm_rca_parse_error", error=str(e))
            return [RCAFinding(
                source=FailureSource.unknown,
                confidence=0.3,
                evidence=f"LLM analysis could not be parsed: {e}",
                suggested_action="Manual review recommended",
            )]

    def _determine_primary_source(self, findings: list[RCAFinding]) -> FailureSource:
        """Determine the primary failure source by aggregating confidence scores."""
        if not findings:
            return FailureSource.unknown

        # Aggregate confidence by source
        source_scores: dict[FailureSource, float] = {}
        for finding in findings:
            source_scores[finding.source] = (
                source_scores.get(finding.source, 0) + finding.confidence
            )

        return max(source_scores, key=source_scores.get)

    async def _generate_summary(
        self,
        trace: TraceRecord,
        findings: list[RCAFinding],
        primary_source: FailureSource,
    ) -> str:
        """Generate a human-readable summary of the RCA findings."""
        findings_text = "\n".join(
            f"- [{f.source.value}] (confidence: {f.confidence}): {f.evidence}"
            for f in findings[:5]
        )

        prompt = (
            f"Summarize this root cause analysis in 2-3 sentences:\n\n"
            f"Primary failure source: {primary_source.value}\n"
            f"Findings:\n{findings_text}\n\n"
            f"Write a concise, actionable summary."
        )

        try:
            summary, _ = await self.router.route_and_call(
                prompt,
                TaskType.preprocessing,
                temperature=0.0,
                max_tokens=256,
            )
            return summary.strip()
        except Exception:
            # Fallback to template summary
            return (
                f"Primary failure source: {primary_source.value}. "
                f"{len(findings)} findings identified. "
                f"Top finding: {findings[0].evidence if findings else 'None'}"
            )
