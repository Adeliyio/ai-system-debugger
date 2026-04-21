import uuid
import json
from datetime import datetime, timezone

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
    SeverityLevel,
    TraceStatus,
)
from backend.storage.models import TraceRecord, EvaluationRecord
from backend.services.routing import ModelRouter, TaskType

logger = structlog.get_logger(__name__)


class LLMJudgeEvaluator:
    """Uses GPT-4o as a judge to evaluate response quality."""

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
            '{"passed": true/false, "score": 0.0-1.0, "reasoning": "..."}'
        )

        eval_prompt = f"Prompt: {prompt}\n\nResponse: {response}\n"
        if context_documents:
            eval_prompt += f"\nContext provided: {json.dumps(context_documents[:5])}\n"
        if reference:
            eval_prompt += f"\nReference answer: {reference}\n"

        eval_prompt += "\nEvaluate the response quality. Return JSON only."

        try:
            result, _ = await self.router.route_and_call(
                eval_prompt,
                TaskType.evaluation,
                system_prompt=system_prompt,
                temperature=0.0,
            )

            parsed = json.loads(result)
            return EvaluatorVerdict(
                evaluator_type=EvaluatorType.llm_judge,
                passed=parsed["passed"],
                score=max(0.0, min(1.0, parsed["score"])),
                reasoning=parsed["reasoning"],
            )
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning("llm_judge_parse_error", error=str(e), raw_result=result)
            return EvaluatorVerdict(
                evaluator_type=EvaluatorType.llm_judge,
                passed=False,
                score=0.0,
                reasoning=f"Failed to parse LLM judge response: {e}",
            )


class EmbeddingSimilarityEvaluator:
    """Evaluates response quality using embedding similarity."""

    def __init__(self):
        self.model = SentenceTransformer("all-MiniLM-L6-v2")
        self.threshold = settings.similarity_threshold

    def evaluate(
        self,
        prompt: str,
        response: str,
        context_documents: list[str],
        reference: str | None = None,
    ) -> EvaluatorVerdict:
        scores = []

        # Similarity between prompt and response (relevance)
        prompt_emb = self.model.encode([prompt])[0]
        response_emb = self.model.encode([response])[0]
        relevance = float(np.dot(prompt_emb, response_emb) / (
            np.linalg.norm(prompt_emb) * np.linalg.norm(response_emb)
        ))
        scores.append(relevance)

        # Similarity between context and response (grounding)
        if context_documents:
            context_text = " ".join(context_documents[:5])
            context_emb = self.model.encode([context_text])[0]
            grounding = float(np.dot(context_emb, response_emb) / (
                np.linalg.norm(context_emb) * np.linalg.norm(response_emb)
            ))
            scores.append(grounding)

        # Similarity to reference if available
        if reference:
            ref_emb = self.model.encode([reference])[0]
            accuracy = float(np.dot(ref_emb, response_emb) / (
                np.linalg.norm(ref_emb) * np.linalg.norm(response_emb)
            ))
            scores.append(accuracy)

        avg_score = sum(scores) / len(scores) if scores else 0.0
        passed = avg_score >= self.threshold

        return EvaluatorVerdict(
            evaluator_type=EvaluatorType.embedding_similarity,
            passed=passed,
            score=round(avg_score, 4),
            reasoning=(
                f"Average embedding similarity: {avg_score:.4f} "
                f"(threshold: {self.threshold}). "
                f"Relevance: {scores[0]:.4f}"
                + (f", Grounding: {scores[1]:.4f}" if len(scores) > 1 else "")
                + (f", Accuracy: {scores[2]:.4f}" if len(scores) > 2 else "")
            ),
        )


class RuleBasedEvaluator:
    """Applies deterministic rules to catch common failure patterns."""

    def evaluate(
        self,
        prompt: str,
        response: str,
        context_documents: list[str],
    ) -> EvaluatorVerdict:
        issues = []
        score = 1.0

        # Rule 1: Empty or near-empty response
        if len(response.strip()) < 10:
            issues.append("Response is too short or empty")
            score -= 0.5

        # Rule 2: Refusal patterns
        refusal_patterns = [
            "i cannot", "i can't", "i'm unable", "i am unable",
            "as an ai", "i don't have access", "i apologize, but",
        ]
        response_lower = response.lower()
        if any(pattern in response_lower for pattern in refusal_patterns):
            issues.append("Response contains refusal/deflection patterns")
            score -= 0.3

        # Rule 3: Hallucination indicators (response mentions facts not in context)
        if context_documents and len(context_documents) > 0:
            context_text = " ".join(context_documents).lower()
            # Check if response makes specific claims with numbers not in context
            import re
            response_numbers = set(re.findall(r'\b\d{4,}\b', response))
            context_numbers = set(re.findall(r'\b\d{4,}\b', context_text))
            unsupported_numbers = response_numbers - context_numbers
            if len(unsupported_numbers) > 2:
                issues.append(
                    f"Response contains {len(unsupported_numbers)} numeric claims "
                    f"not found in context"
                )
                score -= 0.2

        # Rule 4: Repetition detection
        sentences = response.split(".")
        if len(sentences) > 3:
            unique_ratio = len(set(s.strip().lower() for s in sentences if s.strip())) / len(
                [s for s in sentences if s.strip()]
            )
            if unique_ratio < 0.5:
                issues.append(f"High repetition detected (unique ratio: {unique_ratio:.2f})")
                score -= 0.3

        # Rule 5: Response length proportionality
        prompt_words = len(prompt.split())
        response_words = len(response.split())
        if prompt_words > 20 and response_words < 5:
            issues.append("Response disproportionately short for the prompt")
            score -= 0.2

        score = max(0.0, score)
        passed = score >= 0.5 and len(issues) == 0

        return EvaluatorVerdict(
            evaluator_type=EvaluatorType.rule_based,
            passed=passed,
            score=round(score, 4),
            reasoning="; ".join(issues) if issues else "All rule checks passed",
        )


class EvaluationService:
    """Ensemble evaluation engine combining three evaluators with majority agreement."""

    def __init__(self, db: AsyncSession, router: ModelRouter):
        self.db = db
        self.llm_judge = LLMJudgeEvaluator(router)
        self.embedding_eval = EmbeddingSimilarityEvaluator()
        self.rule_eval = RuleBasedEvaluator()
        self.agreement_threshold = settings.ensemble_agreement_threshold

    async def evaluate_trace(self, request: EvaluationRequest) -> EvaluationResponse:
        """Run all three evaluators and determine outcome by majority agreement."""
        trace = await self.db.get(TraceRecord, request.trace_id)
        if trace is None:
            raise ValueError(f"Trace {request.trace_id} not found")

        # Run evaluators
        llm_verdict = await self.llm_judge.evaluate(
            trace.prompt,
            trace.response,
            trace.context_documents or [],
            request.reference_response,
        )

        embedding_verdict = self.embedding_eval.evaluate(
            trace.prompt,
            trace.response,
            trace.context_documents or [],
            request.reference_response,
        )

        rule_verdict = self.rule_eval.evaluate(
            trace.prompt,
            trace.response,
            trace.context_documents or [],
        )

        verdicts = [llm_verdict, embedding_verdict, rule_verdict]

        # Majority agreement
        pass_count = sum(1 for v in verdicts if v.passed)
        fail_count = len(verdicts) - pass_count
        passed = pass_count >= self.agreement_threshold
        failure_detected = not passed

        # Overall score (weighted average)
        overall_score = (
            llm_verdict.score * 0.5
            + embedding_verdict.score * 0.3
            + rule_verdict.score * 0.2
        )

        # Determine severity
        severity = self._classify_severity(overall_score, verdicts)

        # Persist evaluation
        eval_id = uuid.uuid4()
        record = EvaluationRecord(
            id=eval_id,
            trace_id=trace.id,
            passed=passed,
            overall_score=round(overall_score, 4),
            verdicts=[v.model_dump() for v in verdicts],
            agreement_count=max(pass_count, fail_count),
            failure_detected=failure_detected,
            severity=severity.value,
        )
        self.db.add(record)

        # Update trace status
        trace.status = "analyzed" if passed else "failed"
        await self.db.flush()

        logger.info(
            "evaluation_completed",
            trace_id=str(trace.id),
            passed=passed,
            overall_score=round(overall_score, 4),
            agreement=f"{max(pass_count, fail_count)}/3",
            severity=severity.value,
        )

        return EvaluationResponse(
            id=str(eval_id),
            trace_id=str(trace.id),
            passed=passed,
            overall_score=round(overall_score, 4),
            verdicts=verdicts,
            agreement_count=max(pass_count, fail_count),
            failure_detected=failure_detected,
            severity=severity,
            created_at=record.created_at or datetime.now(timezone.utc),
        )

    def _classify_severity(
        self,
        overall_score: float,
        verdicts: list[EvaluatorVerdict],
    ) -> SeverityLevel:
        """Classify failure severity based on scores and agreement."""
        if overall_score >= 0.7:
            return SeverityLevel.low
        elif overall_score >= 0.4:
            # Check if all evaluators agree on failure
            all_failed = all(not v.passed for v in verdicts)
            return SeverityLevel.high if all_failed else SeverityLevel.medium
        else:
            all_failed = all(not v.passed for v in verdicts)
            return SeverityLevel.critical if all_failed else SeverityLevel.high
