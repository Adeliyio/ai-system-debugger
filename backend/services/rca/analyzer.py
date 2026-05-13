import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.schemas import (
    RCARequest,
    RCAResponse,
    RCAFinding,
    FailureSource,
)
from backend.storage.models import TraceRecord, EvaluationRecord, RCARecord
from backend.services.routing import ModelRouter, TaskType

logger = structlog.get_logger(__name__)


def _coerce_uuid(value: Any) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))


def prompt_fingerprint(prompt: str) -> str:
    """Stable short fingerprint of the first 80 normalized characters."""
    norm = re.sub(r"\s+", " ", prompt.strip().lower())[:80]
    return hashlib.md5(norm.encode("utf-8")).hexdigest()[:16]


def _extract_json(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    match = re.search(r"[\{\[].*[\}\]]", text, re.DOTALL)
    return match.group(0) if match else text


# Failure signal patterns mapped to root cause sources
RETRIEVAL_SIGNALS = [
    "context not relevant", "missing information", "no supporting evidence",
    "context doesn't address", "retrieved documents unrelated",
]

PROMPT_SIGNALS = [
    "ambiguous question", "unclear instruction", "contradictory requirements",
    "missing constraints", "prompt too vague", "refusal",
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
    """Root Cause Analysis engine that diagnoses why an AI system response failed."""

    def __init__(self, db: AsyncSession, router: ModelRouter):
        self.db = db
        self.router = router

    async def analyze(self, request: RCARequest) -> RCAResponse:
        trace = await self.db.get(TraceRecord, _coerce_uuid(request.trace_id))
        if trace is None:
            raise ValueError(f"Trace {request.trace_id} not found")

        evaluation = await self.db.get(EvaluationRecord, _coerce_uuid(request.evaluation_id))
        if evaluation is None:
            raise ValueError(f"Evaluation {request.evaluation_id} not found")

        heuristic_findings = self._heuristic_analysis(trace, evaluation)
        llm_findings = await self._llm_analysis(trace, evaluation)

        all_findings = heuristic_findings + llm_findings
        all_findings.sort(key=lambda f: f.confidence, reverse=True)

        primary_source = self._determine_primary_source(all_findings)
        summary = await self._generate_summary(trace, all_findings, primary_source)

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
        findings = []
        verdicts = evaluation.verdicts or []
        all_reasoning = " ".join(v.get("reasoning", "") for v in verdicts).lower()

        # Use the failure_type from the evaluator as a strong prior
        eval_ft = (evaluation.failure_type or "none").lower()

        retrieval_hits = sum(1 for s in RETRIEVAL_SIGNALS if s in all_reasoning)
        if retrieval_hits or not trace.context_documents or eval_ft == "retrieval_failure":
            confidence = min(0.4 + retrieval_hits * 0.15, 0.85)
            if not trace.context_documents:
                confidence = max(confidence, 0.7)
            if eval_ft == "retrieval_failure":
                confidence = max(confidence, 0.8)
            findings.append(RCAFinding(
                source=FailureSource.retrieval,
                confidence=round(confidence, 2),
                evidence=(
                    f"Retrieval signals: {retrieval_hits} pattern matches; "
                    f"docs provided: {len(trace.context_documents or [])}; "
                    f"evaluator failure_type: {eval_ft}"
                ),
                suggested_action="Improve retrieval query, expand corpus, or adjust similarity threshold",
            ))

        prompt_hits = sum(1 for s in PROMPT_SIGNALS if s in all_reasoning)
        if prompt_hits or eval_ft == "prompt_failure":
            confidence = min(0.3 + prompt_hits * 0.15, 0.8)
            if eval_ft == "prompt_failure":
                confidence = max(confidence, 0.75)
            findings.append(RCAFinding(
                source=FailureSource.prompt,
                confidence=round(confidence, 2),
                evidence=f"Prompt signals: {prompt_hits} matches; failure_type: {eval_ft}",
                suggested_action="Refine prompt template with clearer instructions and constraints",
            ))

        model_hits = sum(1 for s in MODEL_SIGNALS if s in all_reasoning)
        if model_hits or eval_ft in ("hallucination", "reasoning_failure"):
            confidence = min(0.3 + model_hits * 0.15, 0.8)
            if eval_ft in ("hallucination", "reasoning_failure"):
                confidence = max(confidence, 0.75)
            findings.append(RCAFinding(
                source=FailureSource.model,
                confidence=round(confidence, 2),
                evidence=f"Model signals: {model_hits} matches; failure_type: {eval_ft}",
                suggested_action="Route to a more capable model or adjust temperature",
            ))

        context_hits = sum(1 for s in CONTEXT_SIGNALS if s in all_reasoning)
        sparse = trace.context_documents and len(trace.context_documents) < 2
        if context_hits or sparse or eval_ft == "context_loss":
            confidence = min(0.3 + context_hits * 0.15, 0.8)
            if sparse:
                confidence = max(confidence, 0.5)
            if eval_ft == "context_loss":
                confidence = max(confidence, 0.75)
            findings.append(RCAFinding(
                source=FailureSource.context,
                confidence=round(confidence, 2),
                evidence=(
                    f"Context signals: {context_hits} matches; "
                    f"docs: {len(trace.context_documents or [])}; failure_type: {eval_ft}"
                ),
                suggested_action="Enrich context with additional relevant documents",
            ))

        return findings

    async def _llm_analysis(
        self,
        trace: TraceRecord,
        evaluation: EvaluationRecord,
    ) -> list[RCAFinding]:
        system_prompt = (
            "You are a root cause analysis expert for AI systems. "
            "Given a failed AI interaction, identify the most likely root cause. "
            "Classify into: retrieval, prompt, model, or context. "
            "Return a JSON array of findings: "
            '[{"source": "...", "confidence": 0.0-1.0, "evidence": "...", "suggested_action": "..."}]'
        )

        analysis_prompt = (
            f"Failed AI interaction analysis:\n\n"
            f"Prompt: {trace.prompt[:1000]}\n\n"
            f"Response: {trace.response[:1000]}\n\n"
            f"Context documents: {len(trace.context_documents or [])} provided\n\n"
            f"Evaluator failure_type: {evaluation.failure_type}\n\n"
            f"Evaluation verdicts: {json.dumps(evaluation.verdicts, indent=2)[:1500]}\n\n"
            f"Identify root causes. Return JSON array only."
        )

        result_text = ""
        try:
            result_text, _ = await self.router.route_and_call(
                analysis_prompt,
                TaskType.rca,
                system_prompt=system_prompt,
                temperature=0.0,
            )
            parsed = json.loads(_extract_json(result_text))
            findings = []
            for item in parsed:
                source = item.get("source", "unknown")
                if source not in [e.value for e in FailureSource]:
                    source = "unknown"
                findings.append(RCAFinding(
                    source=FailureSource(source),
                    confidence=max(0.0, min(1.0, float(item.get("confidence", 0.5)))),
                    evidence=item.get("evidence", "LLM analysis"),
                    suggested_action=item.get("suggested_action", "Review manually"),
                ))
            return findings
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
            logger.warning("llm_rca_parse_error", error=str(e), raw=result_text[:200])
            return [RCAFinding(
                source=FailureSource.unknown,
                confidence=0.3,
                evidence=f"LLM analysis could not be parsed: {e}",
                suggested_action="Manual review recommended",
            )]

    def _determine_primary_source(self, findings: list[RCAFinding]) -> FailureSource:
        if not findings:
            return FailureSource.unknown
        source_scores: dict[FailureSource, float] = {}
        for f in findings:
            source_scores[f.source] = source_scores.get(f.source, 0) + f.confidence
        return max(source_scores, key=source_scores.get)

    async def _generate_summary(
        self,
        trace: TraceRecord,
        findings: list[RCAFinding],
        primary_source: FailureSource,
    ) -> str:
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
            return (
                f"Primary failure source: {primary_source.value}. "
                f"{len(findings)} findings identified. "
                f"Top finding: {findings[0].evidence if findings else 'None'}"
            )
