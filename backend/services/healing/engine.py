import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import faiss
import numpy as np
import structlog
from langgraph.graph import StateGraph, END
from sentence_transformers import SentenceTransformer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.models.schemas import (
    FailureSource,
    FailureType,
    HealingRequest,
    HealingResponse,
    HealingStrategy,
    RegressionResult,
    RiskTier,
)
from backend.services.evaluation.evaluator import EvaluationService
from backend.services.rca.analyzer import prompt_fingerprint
from backend.services.routing import ModelRouter, TaskType
from backend.storage.models import (
    EvaluationRecord,
    FailureClusterRecord,
    FixOutcomeRecord,
    HealingRecord,
    HumanReviewRecord,
    RCARecord,
    TraceRecord,
)

logger = structlog.get_logger(__name__)

DATA_DIR = Path(__file__).resolve().parents[3] / "data"
FIX_INDEX_PATH = DATA_DIR / "fix_index.faiss"
FIX_RECORDS_PATH = DATA_DIR / "fix_records.json"


def _coerce_uuid(value: Any) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))


# --- Repair Strategy Implementations ---

class PromptRepairer:
    """Two-stage prompt repair: Llama drafts; judge validates; escalate to GPT-4o on failure."""

    def __init__(self, router: ModelRouter, evaluator: EvaluationService):
        self.router = router
        self.evaluator = evaluator

    async def repair(
        self,
        original_prompt: str,
        rca_summary: str,
        context_documents: list[str],
    ) -> tuple[str, str, bool]:
        """Returns (repaired_response, repair_prompt_used, escalated_to_openai)."""
        system_prompt = (
            "You are an expert prompt engineer. Given a prompt that led to a failed AI response, "
            "rewrite it to be clearer, more specific, and better constrained. "
            'Return JSON: {"repaired_prompt": "...", "changes_made": "..."}'
        )
        repair_input = (
            f"Original prompt that failed: {original_prompt}\n\n"
            f"Root cause analysis: {rca_summary}\n\n"
            f"Rewrite this prompt to fix the identified issues. Return JSON only."
        )

        # Stage 1: draft locally on Llama
        try:
            draft_text = await self.router.call_local(repair_input, system_prompt)
            draft_prompt = _safe_extract_repaired_prompt(draft_text, original_prompt)
        except Exception as e:
            logger.warning("local_draft_failed", error=str(e))
            draft_prompt = original_prompt

        # Generate response with the local-drafted prompt
        try:
            draft_response = await self.router.call_local(draft_prompt)
        except Exception as e:
            logger.warning("local_draft_response_failed", error=str(e))
            draft_response = ""

        # Validate via the ensemble evaluator
        validation = await self.evaluator.evaluate_response(
            draft_prompt, draft_response, context_documents,
        )
        if validation.passed:
            logger.info("prompt_repair_local_succeeded")
            return draft_response, draft_prompt, False

        # Stage 2: escalate to OpenAI with failed-attempt context
        if self.router.openai_client is None:
            # Cannot escalate; return the local draft anyway
            return draft_response, draft_prompt, False

        escalate_input = (
            f"{repair_input}\n\n"
            f"A previous local rewrite produced this prompt: {draft_prompt}\n"
            f"And this response: {draft_response}\n"
            f"That attempt was rejected by the evaluator (reason: {validation.failure_type.value}). "
            f"Produce a stronger rewrite."
        )
        try:
            escalated_text = await self.router.call_openai(
                escalate_input, system_prompt, temperature=0.0,
            )
            escalated_prompt = _safe_extract_repaired_prompt(escalated_text, original_prompt)
            escalated_response = await self.router.call_openai(
                escalated_prompt,
                system_prompt="Provide a thorough, accurate, and well-reasoned response.",
            )
            return escalated_response, escalated_prompt, True
        except Exception as e:
            logger.error("openai_escalation_failed", error=str(e))
            return draft_response, draft_prompt, False


def _safe_extract_repaired_prompt(text: str, fallback: str) -> str:
    """Best-effort JSON extraction; otherwise return fallback."""
    try:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            if cleaned.lower().startswith("json"):
                cleaned = cleaned[4:].lstrip()
        parsed = json.loads(cleaned)
        return parsed.get("repaired_prompt") or fallback
    except (json.JSONDecodeError, AttributeError, ValueError):
        return fallback


class RetrievalCorrector:
    def __init__(self, router: ModelRouter):
        self.router = router

    async def repair(
        self,
        original_prompt: str,
        context_documents: list[str],
        rca_summary: str,
    ) -> tuple[str, str]:
        system_prompt = (
            "You are a retrieval optimization expert. The original query did not retrieve "
            "relevant context. Reformulate the query and identify what information is missing. "
            'Return JSON: {"reformulated_query": "...", "missing_info": "..."}'
        )
        repair_input = (
            f"Original query: {original_prompt}\n\n"
            f"Retrieved context (possibly irrelevant): {json.dumps(context_documents[:3])}\n\n"
            f"RCA: {rca_summary}\n\n"
            f"Reformulate the query. Return JSON only."
        )

        try:
            result, _ = await self.router.route_and_call(
                repair_input, TaskType.prompt_repair, system_prompt=system_prompt,
            )
            try:
                parsed = json.loads(result)
                reformulated = parsed.get("reformulated_query", original_prompt)
            except (json.JSONDecodeError, KeyError):
                reformulated = original_prompt
        except Exception as e:
            logger.warning("retrieval_reformulate_failed", error=str(e))
            reformulated = original_prompt

        try:
            response, _ = await self.router.route_and_call(
                reformulated, TaskType.generation, temperature=0.0,
            )
        except Exception as e:
            logger.warning("retrieval_regenerate_failed", error=str(e))
            response = ""
        return response, reformulated


class ModelRerouter:
    def __init__(self, router: ModelRouter):
        self.router = router

    async def repair(self, original_prompt: str) -> tuple[str, Optional[str]]:
        try:
            response = await self.router.call_openai(
                original_prompt,
                system_prompt="Provide a thorough, accurate, and well-reasoned response.",
                temperature=0.0,
                max_tokens=2048,
            )
        except Exception as e:
            logger.warning("model_reroute_openai_failed", error=str(e))
            response = ""
        return response, None


class ContextEnricher:
    def __init__(self, router: ModelRouter):
        self.router = router

    async def repair(
        self,
        original_prompt: str,
        context_documents: list[str],
        rca_summary: str,
    ) -> tuple[str, str]:
        system_prompt = (
            "The AI system failed because the provided context was insufficient. "
            "Based on the prompt and available context, identify what additional "
            "information would be needed and synthesize the best possible response "
            "using the available information. Be explicit about what you know vs. "
            "what would need to be verified."
        )
        enriched_prompt = (
            f"Question: {original_prompt}\n\n"
            f"Available context: {json.dumps(context_documents[:5])}\n\n"
            f"Known issue: {rca_summary}\n\n"
            f"Provide the best response with available information."
        )
        try:
            response, _ = await self.router.route_and_call(
                enriched_prompt, TaskType.prompt_repair,
                system_prompt=system_prompt, temperature=0.0,
            )
        except Exception as e:
            logger.warning("context_enrich_failed", error=str(e))
            response = ""
        return response, enriched_prompt


# --- FAISS-Based Persistent Fix Repository ---

class FixRepository:
    """Persistent store of past successful fixes; FAISS-backed similarity search."""

    DIMENSION = 384  # all-MiniLM-L6-v2

    def __init__(self, embedding_model: SentenceTransformer):
        self.embedding_model = embedding_model
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.index = self._load_index()
        self.fix_records: list[dict] = self._load_records()

    def _load_index(self) -> faiss.Index:
        if FIX_INDEX_PATH.exists():
            try:
                return faiss.read_index(str(FIX_INDEX_PATH))
            except Exception as e:
                logger.warning("faiss_load_failed", error=str(e))
        return faiss.IndexFlatIP(self.DIMENSION)

    def _load_records(self) -> list[dict]:
        if FIX_RECORDS_PATH.exists():
            try:
                return json.loads(FIX_RECORDS_PATH.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning("fix_records_load_failed", error=str(e))
        return []

    def _persist(self) -> None:
        try:
            faiss.write_index(self.index, str(FIX_INDEX_PATH))
            FIX_RECORDS_PATH.write_text(
                json.dumps(self.fix_records, indent=2), encoding="utf-8"
            )
        except Exception as e:
            logger.warning("fix_repository_persist_failed", error=str(e))

    def add_fix(self, prompt: str, strategy: str, improvement: float) -> None:
        embedding = self.embedding_model.encode([prompt])[0]
        normalized = embedding / (np.linalg.norm(embedding) + 1e-9)
        self.index.add(np.array([normalized], dtype=np.float32))
        self.fix_records.append({
            "prompt": prompt,
            "strategy": strategy,
            "improvement": improvement,
            "added_at": datetime.now(timezone.utc).isoformat(),
        })
        self._persist()

    def find_similar_fixes(self, prompt: str, k: int = 3) -> list[dict]:
        if self.index.ntotal == 0:
            return []
        embedding = self.embedding_model.encode([prompt])[0]
        normalized = embedding / (np.linalg.norm(embedding) + 1e-9)
        k = min(k, self.index.ntotal)
        scores, indices = self.index.search(
            np.array([normalized], dtype=np.float32), k
        )
        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx >= 0 and score > 0.7 and idx < len(self.fix_records):
                record = self.fix_records[idx].copy()
                record["similarity"] = float(score)
                results.append(record)
        return results


# --- Regression Testing ---

class RegressionTester:
    def __init__(self, embedding_model: SentenceTransformer):
        self.embedding_model = embedding_model

    async def run_regression(
        self,
        repaired_response: str,
        original_response: str,
        test_cases: list[dict],
    ) -> list[RegressionResult]:
        results = []
        for i, test_case in enumerate(test_cases[: settings.regression_suite_size]):
            original_emb = self.embedding_model.encode([original_response])[0]
            repaired_emb = self.embedding_model.encode([repaired_response])[0]

            if "expected" in test_case:
                expected_emb = self.embedding_model.encode([test_case["expected"]])[0]
                original_score = float(np.dot(original_emb, expected_emb) / (
                    (np.linalg.norm(original_emb) * np.linalg.norm(expected_emb)) + 1e-9
                ))
                repaired_score = float(np.dot(repaired_emb, expected_emb) / (
                    (np.linalg.norm(repaired_emb) * np.linalg.norm(expected_emb)) + 1e-9
                ))
            else:
                original_score = 0.5
                repaired_score = 0.5

            degradation = max(0.0, original_score - repaired_score)
            passed = degradation <= settings.relevance_degradation_limit

            results.append(RegressionResult(
                test_case_id=test_case.get("id", f"tc_{i}"),
                passed=passed,
                original_score=round(original_score, 4),
                repaired_score=round(repaired_score, 4),
                degradation=round(degradation, 4),
            ))
        return results


# --- LangGraph state ---

from typing import TypedDict, Any, Annotated


class HealingState(TypedDict, total=False):
    """Typed state flowing through the LangGraph healing pipeline."""
    trace: Any
    rca: Any
    strategy_override: Any
    strategy: Any
    similar_fixes: list
    attempt: int
    test_cases: list
    original_failure_type: Any
    repaired_response: str
    repair_prompt: str
    escalated_to_openai: bool
    regression_results: list
    regression_passed: bool
    improvement_score: float
    post_repair_failure_type: Any
    post_repair_passed: bool
    finalized: bool


# --- Main Service ---

SAFETY_TIERS = {RiskTier.financial.value, RiskTier.legal.value, RiskTier.medical.value}


class HealingService:
    """Self-healing engine using LangGraph to orchestrate repair pipelines."""

    def __init__(self, db: AsyncSession, router: ModelRouter):
        self.db = db
        self.router = router
        self.embedding_model = SentenceTransformer("all-MiniLM-L6-v2")
        self.evaluator = EvaluationService(db, router)
        self.prompt_repairer = PromptRepairer(router, self.evaluator)
        self.retrieval_corrector = RetrievalCorrector(router)
        self.model_rerouter = ModelRerouter(router)
        self.context_enricher = ContextEnricher(router)
        self.fix_repo = FixRepository(self.embedding_model)
        self.regression_tester = RegressionTester(self.embedding_model)
        self._graph = self._build_graph()

    # -- Graph wiring --
    def _build_graph(self):
        graph = StateGraph(HealingState)
        graph.add_node("select_strategy", self._select_strategy_node)
        graph.add_node("apply_repair", self._apply_repair_node)
        graph.add_node("regression_test", self._regression_test_node)
        graph.add_node("finalize", self._finalize_node)

        graph.set_entry_point("select_strategy")
        graph.add_edge("select_strategy", "apply_repair")
        graph.add_edge("apply_repair", "regression_test")
        graph.add_conditional_edges(
            "regression_test",
            self._should_retry,
            {"retry": "apply_repair", "accept": "finalize"},
        )
        graph.add_edge("finalize", END)
        return graph.compile()

    # -- Bayesian strategy selection --
    async def _bayesian_strategy(self, source: FailureSource) -> HealingStrategy:
        """Pick the strategy with the highest posterior mean (success / total)
        given the failure source. Returns the static-map default if no priors exist."""
        default_map = {
            FailureSource.prompt: HealingStrategy.prompt_repair,
            FailureSource.retrieval: HealingStrategy.retrieval_correction,
            FailureSource.model: HealingStrategy.model_reroute,
            FailureSource.context: HealingStrategy.context_enrichment,
            FailureSource.unknown: HealingStrategy.prompt_repair,
        }
        result = await self.db.execute(
            select(FixOutcomeRecord).where(FixOutcomeRecord.failure_source == source.value)
        )
        rows = result.scalars().all()
        if not rows:
            return default_map[source]

        best_strategy = default_map[source]
        best_mean = -1.0
        for row in rows:
            if row.strategy == HealingStrategy.manual_review.value:
                continue
            total = row.success_count + row.failure_count
            mean = (row.success_count / total) if total else 0.5
            if mean > best_mean:
                best_mean = mean
                try:
                    best_strategy = HealingStrategy(row.strategy)
                except ValueError:
                    continue
        logger.info(
            "bayesian_strategy_selected",
            source=source.value, strategy=best_strategy.value,
            posterior_mean=round(best_mean, 3),
        )
        return best_strategy

    async def _record_outcome(
        self, source: FailureSource, strategy: HealingStrategy, success: bool,
    ) -> None:
        """Increment Beta counts for (source, strategy)."""
        result = await self.db.execute(
            select(FixOutcomeRecord).where(
                (FixOutcomeRecord.failure_source == source.value)
                & (FixOutcomeRecord.strategy == strategy.value)
            )
        )
        record = result.scalar_one_or_none()
        if record is None:
            record = FixOutcomeRecord(
                id=uuid.uuid4(),
                failure_source=source.value,
                strategy=strategy.value,
                success_count=2 if success else 1,
                failure_count=1 if success else 2,
            )
            self.db.add(record)
        else:
            if success:
                record.success_count += 1
            else:
                record.failure_count += 1
            record.last_updated = datetime.now(timezone.utc)
        await self.db.flush()

    # -- LangGraph nodes --
    async def _select_strategy_node(self, state: HealingState) -> dict:
        rca = state["rca"]
        override = state.get("strategy_override")

        if override:
            strategy = override
        else:
            strategy = await self._bayesian_strategy(FailureSource(rca.primary_source))

        # Override based on past similar fixes
        similar_fixes = self.fix_repo.find_similar_fixes(state["trace"].prompt)
        if similar_fixes and similar_fixes[0]["improvement"] > 0.2:
            try:
                strategy = HealingStrategy(similar_fixes[0]["strategy"])
                logger.info(
                    "using_similar_fix_strategy",
                    strategy=strategy.value,
                    similarity=similar_fixes[0]["similarity"],
                )
            except ValueError:
                pass
        return {"strategy": strategy, "similar_fixes": similar_fixes}

    async def _apply_repair_node(self, state: HealingState) -> dict:
        trace = state["trace"]
        rca = state["rca"]
        strategy = state["strategy"]
        attempt = state.get("attempt", 0) + 1
        escalated = False

        if strategy == HealingStrategy.prompt_repair:
            repaired_response, repair_prompt, escalated = await self.prompt_repairer.repair(
                trace.prompt, rca.analysis_summary, trace.context_documents or [],
            )
        elif strategy == HealingStrategy.retrieval_correction:
            repaired_response, repair_prompt = await self.retrieval_corrector.repair(
                trace.prompt, trace.context_documents or [], rca.analysis_summary,
            )
        elif strategy == HealingStrategy.model_reroute:
            repaired_response, repair_prompt = await self.model_rerouter.repair(trace.prompt)
            escalated = True
        elif strategy == HealingStrategy.context_enrichment:
            repaired_response, repair_prompt = await self.context_enricher.repair(
                trace.prompt, trace.context_documents or [], rca.analysis_summary,
            )
        else:
            raise ValueError(f"Unknown strategy: {strategy}")

        return {
            "repaired_response": repaired_response,
            "repair_prompt": repair_prompt,
            "attempt": attempt,
            "escalated_to_openai": escalated,
        }

    async def _regression_test_node(self, state: HealingState) -> dict:
        trace = state["trace"]
        original_failure_type: FailureType = state["original_failure_type"]
        repaired_response: str = state["repaired_response"]

        # 1. Re-evaluate the repaired response on the same prompt+context
        ensemble = await self.evaluator.evaluate_response(
            trace.prompt, repaired_response, trace.context_documents or [],
        )
        original_failure_resolved = (
            ensemble.passed or ensemble.failure_type != original_failure_type
        )
        introduced_new_failure = (
            (not ensemble.passed)
            and ensemble.failure_type != FailureType.none
            and ensemble.failure_type != original_failure_type
        )

        # 2. Embedding-based test cases (defaults -> consistency on repaired)
        test_cases = state.get("test_cases", [{"id": "default"}])
        regression_results = await self.regression_tester.run_regression(
            repaired_response, trace.response, test_cases,
        )
        embedding_pass = all(r.passed for r in regression_results)

        regression_passed = (
            ensemble.passed
            and original_failure_resolved
            and not introduced_new_failure
            and embedding_pass
        )

        # Improvement = repaired_overall - original_overall
        original_eval = await self.evaluator.evaluate_response(
            trace.prompt, trace.response, trace.context_documents or [],
        )
        improvement = ensemble.overall_score - original_eval.overall_score

        return {
            "regression_results": regression_results,
            "regression_passed": regression_passed,
            "improvement_score": round(improvement, 4),
            "post_repair_failure_type": ensemble.failure_type,
            "post_repair_passed": ensemble.passed,
        }

    def _should_retry(self, state: HealingState) -> str:
        if state.get("regression_passed", False):
            return "accept"
        if state.get("attempt", 0) >= settings.max_repair_attempts:
            return "accept"
        return "retry"

    async def _finalize_node(self, state: HealingState) -> dict:
        return {"finalized": True}

    # -- Public API --

    async def heal(self, request: HealingRequest) -> HealingResponse:
        trace = await self.db.get(TraceRecord, _coerce_uuid(request.trace_id))
        if trace is None:
            raise ValueError(f"Trace {request.trace_id} not found")

        rca = await self.db.get(RCARecord, _coerce_uuid(request.rca_id))
        if rca is None:
            raise ValueError(f"RCA report {request.rca_id} not found")

        # ---- Safety boundary ----
        if (trace.risk_tier or "general") in SAFETY_TIERS:
            return await self._enqueue_manual_review(trace, rca)

        # Pull the latest evaluation's failure_type as the "original" failure
        eval_result = await self.db.execute(
            select(EvaluationRecord)
            .where(EvaluationRecord.trace_id == trace.id)
            .order_by(EvaluationRecord.created_at.desc())
            .limit(1)
        )
        latest_eval = eval_result.scalar_one_or_none()
        original_failure_type = (
            FailureType(latest_eval.failure_type) if latest_eval else FailureType.none
        )

        initial_state = HealingState({
            "trace": trace,
            "rca": rca,
            "strategy_override": request.strategy,
            "attempt": 0,
            "test_cases": [{"id": "default"}],
            "original_failure_type": original_failure_type,
        })

        final_state = await self._graph.ainvoke(initial_state)

        healing_id = uuid.uuid4()
        record = HealingRecord(
            id=healing_id,
            trace_id=trace.id,
            rca_id=rca.id,
            strategy=final_state["strategy"].value,
            original_response=trace.response,
            repaired_response=final_state["repaired_response"],
            repair_prompt=final_state.get("repair_prompt"),
            attempt_number=final_state.get("attempt", 1),
            regression_passed=bool(final_state.get("regression_passed", False)),
            regression_results=[
                r.model_dump() for r in final_state.get("regression_results", [])
            ],
            improvement_score=float(final_state.get("improvement_score", 0.0)),
            escalated_to_openai=bool(final_state.get("escalated_to_openai", False)),
        )
        self.db.add(record)

        if final_state.get("regression_passed", False):
            trace.status = "healed"
        await self.db.flush()

        # Update Bayesian counts and persistent fix repo
        await self._record_outcome(
            FailureSource(rca.primary_source),
            final_state["strategy"],
            bool(final_state.get("regression_passed", False)),
        )
        if final_state.get("regression_passed", False):
            self.fix_repo.add_fix(
                trace.prompt,
                final_state["strategy"].value,
                final_state.get("improvement_score", 0.0),
            )

        # Update structural failure cluster regardless of healing success
        await self._upsert_failure_cluster(trace, rca, original_failure_type)

        logger.info(
            "healing_completed",
            trace_id=str(trace.id),
            strategy=final_state["strategy"].value,
            attempt=final_state.get("attempt", 1),
            regression_passed=final_state.get("regression_passed", False),
            improvement=final_state.get("improvement_score", 0.0),
            escalated_to_openai=final_state.get("escalated_to_openai", False),
        )

        return HealingResponse(
            id=str(healing_id),
            trace_id=str(trace.id),
            rca_id=str(rca.id),
            strategy=final_state["strategy"],
            original_response=trace.response,
            repaired_response=final_state["repaired_response"],
            repair_prompt=final_state.get("repair_prompt"),
            attempt_number=final_state.get("attempt", 1),
            regression_passed=bool(final_state.get("regression_passed", False)),
            regression_results=final_state.get("regression_results", []),
            improvement_score=float(final_state.get("improvement_score", 0.0)),
            escalated_to_openai=bool(final_state.get("escalated_to_openai", False)),
            created_at=record.created_at or datetime.now(timezone.utc),
        )

    async def _enqueue_manual_review(
        self, trace: TraceRecord, rca: RCARecord,
    ) -> HealingResponse:
        """High-risk traces never auto-heal; route to a human queue."""
        review = HumanReviewRecord(
            id=uuid.uuid4(),
            trace_id=trace.id,
            evaluation_id=rca.evaluation_id,
            reason="high_risk",
            severity="high",
            risk_tier=trace.risk_tier or "general",
        )
        self.db.add(review)
        trace.status = "awaiting_review"

        healing_id = uuid.uuid4()
        record = HealingRecord(
            id=healing_id,
            trace_id=trace.id,
            rca_id=rca.id,
            strategy=HealingStrategy.manual_review.value,
            original_response=trace.response,
            repaired_response=trace.response,  # unchanged
            repair_prompt=None,
            attempt_number=0,
            regression_passed=False,
            regression_results=[],
            improvement_score=0.0,
            escalated_to_openai=False,
        )
        self.db.add(record)
        await self.db.flush()

        logger.info(
            "healing_skipped_manual_review",
            trace_id=str(trace.id),
            risk_tier=trace.risk_tier,
        )
        return HealingResponse(
            id=str(healing_id),
            trace_id=str(trace.id),
            rca_id=str(rca.id),
            strategy=HealingStrategy.manual_review,
            original_response=trace.response,
            repaired_response=trace.response,
            repair_prompt=None,
            attempt_number=0,
            regression_passed=False,
            regression_results=[],
            improvement_score=0.0,
            escalated_to_openai=False,
            created_at=record.created_at or datetime.now(timezone.utc),
        )

    async def _upsert_failure_cluster(
        self,
        trace: TraceRecord,
        rca: RCARecord,
        failure_type: FailureType,
    ) -> None:
        if failure_type == FailureType.none:
            return
        fp = prompt_fingerprint(trace.prompt)
        result = await self.db.execute(
            select(FailureClusterRecord).where(
                (FailureClusterRecord.failure_type == failure_type.value)
                & (FailureClusterRecord.primary_source == rca.primary_source)
                & (FailureClusterRecord.prompt_fingerprint == fp)
            )
        )
        cluster = result.scalar_one_or_none()
        now = datetime.now(timezone.utc)
        if cluster is None:
            cluster = FailureClusterRecord(
                id=uuid.uuid4(),
                failure_type=failure_type.value,
                primary_source=rca.primary_source,
                prompt_fingerprint=fp,
                occurrence_count=1,
                sample_prompt=trace.prompt[:500],
                last_seen=now,
            )
            self.db.add(cluster)
        else:
            cluster.occurrence_count += 1
            cluster.last_seen = now
        await self.db.flush()
