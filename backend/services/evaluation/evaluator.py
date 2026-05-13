import json
import re
import uuid
from collections import Counter
from datetime import datetime, timezone
from typing import Any

import numpy as np
import structlog
from sentence_transformers import SentenceTransformer
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.models.schemas import (
    EvaluationRequest,
    EvaluationResponse,
    EvaluatorVerdict,
    EvaluatorType,
    FailureType,
    SeverityLevel,
)
from backend.storage.models import TraceRecord, EvaluationRecord
from backend.services.routing import ModelRouter, TaskType


logger = structlog.get_logger(__name__)


def _coerce_uuid(value: Any) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))


def _safe_failure_type(raw: str | None) -> FailureType:
    if not raw:
        return FailureType.none
    try:
        return FailureType(raw)
    except ValueError:
        return FailureType.none


REFUSAL_PATTERNS = [
    "i cannot", "i can't", "i'm unable", "i am unable",
    "i don't have access", "i apologize, but",
]


class LLMJudgeEvaluator:
    """Uses GPT-4o (or local fallback) as a judge to evaluate response quality."""

    def __init__(self, router: ModelRouter):
        self.router = router

    async def evaluate(
        self,
        prompt: str,
        response: str,
        context_documents: list[str],
        reference: str | None = None,
    ) -> EvaluatorVerdict:
        system_prompt = (
            "You are an expert evaluator for AI system outputs. "
            "Assess the response for: factual accuracy, relevance to the prompt, "
            "proper use of provided context, completeness, and coherence. "
            "Return a JSON object with: "
            '{"passed": true/false, "score": 0.0-1.0, "reasoning": "...", '
            '"failure_type": "none|hallucination|retrieval_failure|context_loss|reasoning_failure|prompt_failure"}'
        )

        eval_prompt = f"Prompt: {prompt}\n\nResponse: {response}\n"
        if context_documents:
            eval_prompt += f"\nContext provided: {json.dumps(context_documents[:5])}\n"
        if reference:
            eval_prompt += f"\nReference answer: {reference}\n"

        eval_prompt += "\nEvaluate the response. Return JSON only."

        result_text = ""
        try:
            result_text, _ = await self.router.route_and_call(
                eval_prompt,
                TaskType.evaluation,
                system_prompt=system_prompt,
                temperature=0.0,
            )
            parsed = json.loads(_extract_json(result_text))
            return EvaluatorVerdict(
                evaluator_type=EvaluatorType.llm_judge,
                passed=bool(parsed.get("passed", False)),
                score=max(0.0, min(1.0, float(parsed.get("score", 0.0)))),
                reasoning=str(parsed.get("reasoning", "")),
                failure_type=_safe_failure_type(parsed.get("failure_type")),
            )
        except (json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
            logger.warning("llm_judge_parse_error", error=str(e), raw=result_text[:200])
            # Conservative degraded verdict
            return EvaluatorVerdict(
                evaluator_type=EvaluatorType.llm_judge,
                passed=False,
                score=0.0,
                reasoning=f"Failed to parse LLM judge response: {e}",
                failure_type=FailureType.none,
            )


def _extract_json(text: str) -> str:
    """Extract the first JSON object/array substring from a model response."""
    text = text.strip()
    if text.startswith("```"):
        # Strip code fences
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    # If still wrapped, find first { or [
    match = re.search(r"[\{\[].*[\}\]]", text, re.DOTALL)
    return match.group(0) if match else text


class EmbeddingSimilarityEvaluator:
    """Evaluates response quality using embedding similarity."""

    def __init__(self, model: SentenceTransformer | None = None):
        self.model = model or SentenceTransformer("all-MiniLM-L6-v2")
        self.threshold = settings.similarity_threshold

    def evaluate(
        self,
        prompt: str,
        response: str,
        context_documents: list[str],
        reference: str | None = None,
    ) -> EvaluatorVerdict:
        scores = []

        prompt_emb = self.model.encode([prompt])[0]
        response_emb = self.model.encode([response])[0]
        relevance = float(np.dot(prompt_emb, response_emb) / (
            np.linalg.norm(prompt_emb) * np.linalg.norm(response_emb)
        ))
        scores.append(relevance)

        grounding = None
        if context_documents:
            context_text = " ".join(context_documents[:5])
            context_emb = self.model.encode([context_text])[0]
            grounding = float(np.dot(context_emb, response_emb) / (
                np.linalg.norm(context_emb) * np.linalg.norm(response_emb)
            ))
            scores.append(grounding)

        accuracy = None
        if reference:
            ref_emb = self.model.encode([reference])[0]
            accuracy = float(np.dot(ref_emb, response_emb) / (
                np.linalg.norm(ref_emb) * np.linalg.norm(response_emb)
            ))
            scores.append(accuracy)

        avg_score = sum(scores) / len(scores) if scores else 0.0
        passed = avg_score >= self.threshold

        # Heuristic failure_type from similarity signals
        failure_type = FailureType.none
        if not passed:
            if grounding is not None and grounding < 0.4 and len(context_documents) > 0:
                failure_type = FailureType.context_loss
            elif relevance < 0.3:
                failure_type = FailureType.prompt_failure
            else:
                failure_type = FailureType.hallucination

        reasoning = (
            f"Average embedding similarity: {avg_score:.4f} "
            f"(threshold: {self.threshold}). "
            f"Relevance: {relevance:.4f}"
            + (f", Grounding: {grounding:.4f}" if grounding is not None else "")
            + (f", Accuracy: {accuracy:.4f}" if accuracy is not None else "")
        )

        return EvaluatorVerdict(
            evaluator_type=EvaluatorType.embedding_similarity,
            passed=passed,
            score=round(avg_score, 4),
            reasoning=reasoning,
            failure_type=failure_type,
        )


class RuleBasedEvaluator:
    """Applies deterministic rules to catch common failure patterns."""

    def evaluate(
        self,
        prompt: str,
        response: str,
        context_documents: list[str],
    ) -> EvaluatorVerdict:
        issues: list[str] = []
        score = 1.0
        failure_type = FailureType.none

        # Rule 1: Empty / very short response
        if len(response.strip()) < 10:
            issues.append("Response is too short or empty")
            score -= 0.5
            failure_type = FailureType.prompt_failure

        # Rule 2: Refusal patterns
        response_lower = response.lower()
        if any(pattern in response_lower for pattern in REFUSAL_PATTERNS):
            issues.append("Response contains refusal/deflection patterns")
            score -= 0.3
            failure_type = FailureType.prompt_failure

        # Rule 3: Hallucination indicators (numeric facts not in context)
        if context_documents:
            context_text = " ".join(context_documents).lower()
            response_numbers = set(re.findall(r"\b\d{3,}\b", response))
            context_numbers = set(re.findall(r"\b\d{3,}\b", context_text))
            unsupported_numbers = response_numbers - context_numbers
            if len(unsupported_numbers) > 2:
                issues.append(
                    f"Response contains {len(unsupported_numbers)} numeric claims "
                    f"not found in context"
                )
                score -= 0.3
                failure_type = FailureType.hallucination

        # Rule 4: Repetition detection
        sentences = [s.strip() for s in response.split(".") if s.strip()]
        if len(sentences) > 3:
            unique_ratio = len(set(s.lower() for s in sentences)) / len(sentences)
            if unique_ratio < 0.5:
                issues.append(f"High repetition detected (unique ratio: {unique_ratio:.2f})")
                score -= 0.3

        # Rule 5: Response length proportionality
        if len(prompt.split()) > 20 and len(response.split()) < 5:
            issues.append("Response disproportionately short for the prompt")
            score -= 0.2

        score = max(0.0, score)
        passed = score >= 0.5 and len(issues) == 0

        return EvaluatorVerdict(
            evaluator_type=EvaluatorType.rule_based,
            passed=passed,
            score=round(score, 4),
            reasoning="; ".join(issues) if issues else "All rule checks passed",
            failure_type=failure_type if not passed else FailureType.none,
        )


# --- Aggregate evaluation result (used in-process by healing for re-evaluation) ---

class EnsembleResult:
    """Lightweight in-memory bundle returned by the in-process evaluator."""

    def __init__(
        self,
        verdicts: list[EvaluatorVerdict],
        passed: bool,
        overall_score: float,
        agreement_count: int,
        failure_type: FailureType,
        severity: SeverityLevel,
        low_confidence: bool,
    ):
        self.verdicts = verdicts
        self.passed = passed
        self.overall_score = overall_score
        self.agreement_count = agreement_count
        self.failure_type = failure_type
        self.severity = severity
        self.low_confidence = low_confidence


class EvaluationService:
    """Ensemble evaluation engine combining three evaluators with majority agreement."""

    def __init__(self, db: AsyncSession, router: ModelRouter):
        self.db = db
        self.llm_judge = LLMJudgeEvaluator(router)
        self.embedding_eval = EmbeddingSimilarityEvaluator()
        self.rule_eval = RuleBasedEvaluator()
        self.agreement_threshold = settings.ensemble_agreement_threshold

    async def evaluate_response(
        self,
        prompt: str,
        response: str,
        context_documents: list[str] | None = None,
        reference_response: str | None = None,
    ) -> EnsembleResult:
        """Run the ensemble against an arbitrary prompt/response (no DB writes)."""
        ctx = context_documents or []

        llm_verdict = await self.llm_judge.evaluate(prompt, response, ctx, reference_response)
        embedding_verdict = self.embedding_eval.evaluate(prompt, response, ctx, reference_response)
        rule_verdict = self.rule_eval.evaluate(prompt, response, ctx)

        verdicts = [llm_verdict, embedding_verdict, rule_verdict]
        pass_count = sum(1 for v in verdicts if v.passed)
        fail_count = len(verdicts) - pass_count
        passed = pass_count >= self.agreement_threshold

        overall_score = (
            llm_verdict.score * 0.5
            + embedding_verdict.score * 0.3
            + rule_verdict.score * 0.2
        )

        # Pick majority failure_type from non-none verdicts
        non_none = [v.failure_type for v in verdicts if v.failure_type != FailureType.none]
        if not passed and non_none:
            failure_type = Counter(non_none).most_common(1)[0][0]
        else:
            failure_type = FailureType.none

        severity = _classify_severity(overall_score, verdicts)
        low_confidence = overall_score < 0.6

        return EnsembleResult(
            verdicts=verdicts,
            passed=passed,
            overall_score=round(overall_score, 4),
            agreement_count=max(pass_count, fail_count),
            failure_type=failure_type,
            severity=severity,
            low_confidence=low_confidence,
        )

    async def evaluate_trace(self, request: EvaluationRequest) -> EvaluationResponse:
        """Run all three evaluators against a stored trace and persist."""
        trace = await self.db.get(TraceRecord, _coerce_uuid(request.trace_id))
        if trace is None:
            raise ValueError(f"Trace {request.trace_id} not found")

        result = await self.evaluate_response(
            trace.prompt,
            trace.response,
            trace.context_documents or [],
            request.reference_response,
        )

        eval_id = uuid.uuid4()
        record = EvaluationRecord(
            id=eval_id,
            trace_id=trace.id,
            passed=result.passed,
            overall_score=result.overall_score,
            verdicts=[v.model_dump() for v in result.verdicts],
            agreement_count=result.agreement_count,
            failure_detected=not result.passed,
            failure_type=result.failure_type.value,
            severity=result.severity.value,
            low_confidence=result.low_confidence,
        )
        self.db.add(record)

        # Update trace status
        if result.passed:
            trace.status = "analyzed"
        elif trace.risk_tier and trace.risk_tier != "general":
            trace.status = "awaiting_review"
        else:
            trace.status = "failed"
        await self.db.flush()

        # Auto-enqueue low-confidence or high-risk traces for human review
        if result.low_confidence or (trace.risk_tier and trace.risk_tier != "general"):
            from backend.storage.models import HumanReviewRecord  # local import avoids cycle
            reason = "high_risk" if trace.risk_tier and trace.risk_tier != "general" else "low_confidence"
            review = HumanReviewRecord(
                id=uuid.uuid4(),
                trace_id=trace.id,
                evaluation_id=eval_id,
                reason=reason,
                severity=result.severity.value,
                risk_tier=trace.risk_tier or "general",
            )
            self.db.add(review)
            await self.db.flush()

        logger.info(
            "evaluation_completed",
            trace_id=str(trace.id),
            passed=result.passed,
            failure_type=result.failure_type.value,
            severity=result.severity.value,
            low_confidence=result.low_confidence,
        )

        return EvaluationResponse(
            id=str(eval_id),
            trace_id=str(trace.id),
            passed=result.passed,
            overall_score=result.overall_score,
            verdicts=result.verdicts,
            agreement_count=result.agreement_count,
            failure_detected=not result.passed,
            failure_type=result.failure_type,
            severity=result.severity,
            low_confidence=result.low_confidence,
            created_at=record.created_at or datetime.now(timezone.utc),
        )


def _classify_severity(
    overall_score: float,
    verdicts: list[EvaluatorVerdict],
) -> SeverityLevel:
    """Classify failure severity based on scores and agreement."""
    if overall_score >= 0.7:
        return SeverityLevel.low
    if overall_score >= 0.4:
        all_failed = all(not v.passed for v in verdicts)
        return SeverityLevel.high if all_failed else SeverityLevel.medium
    all_failed = all(not v.passed for v in verdicts)
    return SeverityLevel.critical if all_failed else SeverityLevel.high
