import uuid
import json
from datetime import datetime, timezone
from typing import Any

import numpy as np
import structlog
import faiss
from sentence_transformers import SentenceTransformer
from langgraph.graph import StateGraph, END
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.core.config import settings
from backend.models.schemas import (
    HealingRequest,
    HealingResponse,
    HealingStrategy,
    RegressionResult,
    FailureSource,
    TraceStatus,
)
from backend.storage.models import TraceRecord, RCARecord, HealingRecord
from backend.services.routing import ModelRouter, TaskType

logger = structlog.get_logger(__name__)


# --- Repair Strategy Implementations ---

class PromptRepairer:
    """Repairs prompts that caused failures by adding clarity, constraints, or context."""

    def __init__(self, router: ModelRouter):
        self.router = router

    async def repair(self, original_prompt: str, rca_summary: str) -> tuple[str, str]:
        """Returns (repaired_response, repair_prompt_used)."""
        system_prompt = (
            "You are an expert prompt engineer. Given a prompt that led to a failed AI response, "
            "rewrite it to be clearer, more specific, and better constrained. "
            "Return a JSON object: {\"repaired_prompt\": \"...\", \"changes_made\": \"...\"}"
        )

        repair_input = (
            f"Original prompt that failed: {original_prompt}\n\n"
            f"Root cause analysis: {rca_summary}\n\n"
            f"Rewrite this prompt to fix the identified issues. Return JSON only."
        )

        result, _ = await self.router.route_and_call(
            repair_input,
            TaskType.prompt_repair,
            system_prompt=system_prompt,
            temperature=0.0,
        )

        try:
            parsed = json.loads(result)
            repaired_prompt = parsed["repaired_prompt"]
        except (json.JSONDecodeError, KeyError):
            repaired_prompt = original_prompt

        # Now run the repaired prompt to get a new response
        response, _ = await self.router.route_and_call(
            repaired_prompt,
            TaskType.evaluation,
            temperature=0.0,
        )

        return response, repaired_prompt


class RetrievalCorrector:
    """Corrects retrieval failures by reformulating queries and re-ranking."""

    def __init__(self, router: ModelRouter):
        self.router = router
        self.embedding_model = SentenceTransformer("all-MiniLM-L6-v2")

    async def repair(
        self,
        original_prompt: str,
        context_documents: list[str],
        rca_summary: str,
    ) -> tuple[str, str]:
        """Re-rank and supplement context, then re-generate response."""
        system_prompt = (
            "You are a retrieval optimization expert. "
            "The original query did not retrieve relevant context. "
            "Reformulate the query and identify what information is missing. "
            "Return JSON: {\"reformulated_query\": \"...\", \"missing_info\": \"...\"}"
        )

        repair_input = (
            f"Original query: {original_prompt}\n\n"
            f"Retrieved context (possibly irrelevant): {json.dumps(context_documents[:3])}\n\n"
            f"RCA: {rca_summary}\n\n"
            f"Reformulate the query. Return JSON only."
        )

        result, _ = await self.router.route_and_call(
            repair_input,
            TaskType.prompt_repair,
            system_prompt=system_prompt,
        )

        try:
            parsed = json.loads(result)
            reformulated = parsed.get("reformulated_query", original_prompt)
        except (json.JSONDecodeError, KeyError):
            reformulated = original_prompt

        # Re-generate with reformulated query
        response, _ = await self.router.route_and_call(
            reformulated,
            TaskType.evaluation,
            temperature=0.0,
        )

        return response, reformulated


class ModelRerouter:
    """Reroutes to a different/more capable model when current model fails."""

    def __init__(self, router: ModelRouter):
        self.router = router

    async def repair(self, original_prompt: str) -> tuple[str, str | None]:
        """Force routing to the high-capability model."""
        response = await self.router.call_openai(
            original_prompt,
            system_prompt="Provide a thorough, accurate, and well-reasoned response.",
            temperature=0.0,
            max_tokens=2048,
        )
        return response, None


class ContextEnricher:
    """Enriches context by extracting and adding missing information."""

    def __init__(self, router: ModelRouter):
        self.router = router

    async def repair(
        self,
        original_prompt: str,
        context_documents: list[str],
        rca_summary: str,
    ) -> tuple[str, str]:
        """Generate supplementary context and re-answer."""
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

        response, _ = await self.router.route_and_call(
            enriched_prompt,
            TaskType.prompt_repair,
            system_prompt=system_prompt,
            temperature=0.0,
        )

        return response, enriched_prompt


# --- FAISS-Based Similar Fix Retrieval ---

class FixRepository:
    """Stores and retrieves past successful fixes using FAISS similarity search."""

    def __init__(self):
        self.embedding_model = SentenceTransformer("all-MiniLM-L6-v2")
        self.dimension = 384  # all-MiniLM-L6-v2 output dimension
        self.index = faiss.IndexFlatIP(self.dimension)
        self.fix_records: list[dict] = []

    def add_fix(self, prompt: str, strategy: str, improvement: float) -> None:
        """Store a successful fix for future retrieval."""
        embedding = self.embedding_model.encode([prompt])[0]
        normalized = embedding / np.linalg.norm(embedding)
        self.index.add(np.array([normalized], dtype=np.float32))
        self.fix_records.append({
            "prompt": prompt,
            "strategy": strategy,
            "improvement": improvement,
        })

    def find_similar_fixes(self, prompt: str, k: int = 3) -> list[dict]:
        """Find past fixes for similar prompts."""
        if self.index.ntotal == 0:
            return []

        embedding = self.embedding_model.encode([prompt])[0]
        normalized = embedding / np.linalg.norm(embedding)
        k = min(k, self.index.ntotal)
        scores, indices = self.index.search(
            np.array([normalized], dtype=np.float32), k
        )

        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx >= 0 and score > 0.7:
                record = self.fix_records[idx].copy()
                record["similarity"] = float(score)
                results.append(record)

        return results


# --- Regression Testing ---

class RegressionTester:
    """Validates that a repair doesn't degrade quality on related test cases."""

    def __init__(self, router: ModelRouter, embedding_model: SentenceTransformer):
        self.router = router
        self.embedding_model = embedding_model

    async def run_regression(
        self,
        repaired_response: str,
        original_response: str,
        test_cases: list[dict],
    ) -> list[RegressionResult]:
        """Run regression tests comparing repaired vs original responses."""
        results = []

        for i, test_case in enumerate(test_cases[:settings.regression_suite_size]):
            original_emb = self.embedding_model.encode([original_response])[0]
            repaired_emb = self.embedding_model.encode([repaired_response])[0]

            if "expected" in test_case:
                expected_emb = self.embedding_model.encode([test_case["expected"]])[0]

                original_score = float(np.dot(original_emb, expected_emb) / (
                    np.linalg.norm(original_emb) * np.linalg.norm(expected_emb)
                ))
                repaired_score = float(np.dot(repaired_emb, expected_emb) / (
                    np.linalg.norm(repaired_emb) * np.linalg.norm(expected_emb)
                ))
            else:
                # Without expected answer, measure consistency
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


# --- LangGraph Healing Pipeline ---

class HealingState(dict):
    """State object for the LangGraph healing pipeline."""
    pass


class HealingService:
    """Self-healing engine using LangGraph to orchestrate repair pipelines.

    Pipeline: Select Strategy -> Apply Repair -> Regression Test -> Accept/Retry
    """

    def __init__(self, db: AsyncSession, router: ModelRouter):
        self.db = db
        self.router = router
        self.prompt_repairer = PromptRepairer(router)
        self.retrieval_corrector = RetrievalCorrector(router)
        self.model_rerouter = ModelRerouter(router)
        self.context_enricher = ContextEnricher(router)
        self.fix_repo = FixRepository()
        self.embedding_model = SentenceTransformer("all-MiniLM-L6-v2")
        self.regression_tester = RegressionTester(router, self.embedding_model)
        self._graph = self._build_graph()

    def _build_graph(self) -> StateGraph:
        """Build the LangGraph healing pipeline."""
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

    async def _select_strategy_node(self, state: HealingState) -> dict:
        """Select the best healing strategy based on RCA findings."""
        rca = state["rca"]
        override = state.get("strategy_override")

        if override:
            strategy = override
        else:
            # Map primary failure source to strategy
            source_to_strategy = {
                FailureSource.prompt: HealingStrategy.prompt_repair,
                FailureSource.retrieval: HealingStrategy.retrieval_correction,
                FailureSource.model: HealingStrategy.model_reroute,
                FailureSource.context: HealingStrategy.context_enrichment,
                FailureSource.unknown: HealingStrategy.prompt_repair,
            }
            strategy = source_to_strategy[FailureSource(rca.primary_source)]

        # Check if similar fixes exist
        similar_fixes = self.fix_repo.find_similar_fixes(state["trace"].prompt)
        if similar_fixes:
            best_fix = similar_fixes[0]
            if best_fix["improvement"] > 0.2:
                strategy = HealingStrategy(best_fix["strategy"])
                logger.info(
                    "using_similar_fix_strategy",
                    strategy=strategy.value,
                    similarity=best_fix["similarity"],
                )

        return {"strategy": strategy, "similar_fixes": similar_fixes}

    async def _apply_repair_node(self, state: HealingState) -> dict:
        """Apply the selected repair strategy."""
        trace = state["trace"]
        rca = state["rca"]
        strategy = state["strategy"]
        attempt = state.get("attempt", 0) + 1

        if strategy == HealingStrategy.prompt_repair:
            repaired_response, repair_prompt = await self.prompt_repairer.repair(
                trace.prompt, rca.analysis_summary
            )
        elif strategy == HealingStrategy.retrieval_correction:
            repaired_response, repair_prompt = await self.retrieval_corrector.repair(
                trace.prompt, trace.context_documents or [], rca.analysis_summary
            )
        elif strategy == HealingStrategy.model_reroute:
            repaired_response, repair_prompt = await self.model_rerouter.repair(
                trace.prompt
            )
        elif strategy == HealingStrategy.context_enrichment:
            repaired_response, repair_prompt = await self.context_enricher.repair(
                trace.prompt, trace.context_documents or [], rca.analysis_summary
            )
        else:
            raise ValueError(f"Unknown strategy: {strategy}")

        return {
            "repaired_response": repaired_response,
            "repair_prompt": repair_prompt,
            "attempt": attempt,
        }

    async def _regression_test_node(self, state: HealingState) -> dict:
        """Run regression tests on the repaired response."""
        test_cases = state.get("test_cases", [{"id": "default"}])

        results = await self.regression_tester.run_regression(
            state["repaired_response"],
            state["trace"].response,
            test_cases,
        )

        all_passed = all(r.passed for r in results)

        # Calculate improvement score
        original_emb = self.embedding_model.encode([state["trace"].prompt])[0]
        repaired_emb = self.embedding_model.encode([state["repaired_response"]])[0]
        original_resp_emb = self.embedding_model.encode([state["trace"].response])[0]

        original_relevance = float(np.dot(original_emb, original_resp_emb) / (
            np.linalg.norm(original_emb) * np.linalg.norm(original_resp_emb)
        ))
        repaired_relevance = float(np.dot(original_emb, repaired_emb) / (
            np.linalg.norm(original_emb) * np.linalg.norm(repaired_emb)
        ))
        improvement = repaired_relevance - original_relevance

        return {
            "regression_results": results,
            "regression_passed": all_passed,
            "improvement_score": round(improvement, 4),
        }

    def _should_retry(self, state: HealingState) -> str:
        """Decide whether to retry repair or accept the result."""
        if state.get("regression_passed", False):
            return "accept"
        if state.get("attempt", 0) >= settings.max_repair_attempts:
            return "accept"  # Accept best effort after max retries
        return "retry"

    async def _finalize_node(self, state: HealingState) -> dict:
        """Finalize the healing result."""
        return {"finalized": True}

    async def heal(self, request: HealingRequest) -> HealingResponse:
        """Execute the full healing pipeline for a failed trace."""
        trace = await self.db.get(TraceRecord, request.trace_id)
        if trace is None:
            raise ValueError(f"Trace {request.trace_id} not found")

        rca = await self.db.get(RCARecord, request.rca_id)
        if rca is None:
            raise ValueError(f"RCA report {request.rca_id} not found")

        # Build initial state
        initial_state = HealingState({
            "trace": trace,
            "rca": rca,
            "strategy_override": request.strategy,
            "attempt": 0,
            "test_cases": [{"id": "default"}],
        })

        # Run the LangGraph pipeline
        final_state = await self._graph.ainvoke(initial_state)

        # Persist healing record
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
            regression_passed=final_state.get("regression_passed", False),
            regression_results=[
                r.model_dump() for r in final_state.get("regression_results", [])
            ],
            improvement_score=final_state.get("improvement_score", 0.0),
        )
        self.db.add(record)

        # Update trace status
        if final_state.get("regression_passed", False):
            trace.status = "healed"
        await self.db.flush()

        # Store successful fix for future similarity matching
        if final_state.get("regression_passed", False):
            self.fix_repo.add_fix(
                trace.prompt,
                final_state["strategy"].value,
                final_state.get("improvement_score", 0.0),
            )

        logger.info(
            "healing_completed",
            trace_id=str(trace.id),
            strategy=final_state["strategy"].value,
            attempt=final_state.get("attempt", 1),
            regression_passed=final_state.get("regression_passed", False),
            improvement=final_state.get("improvement_score", 0.0),
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
            regression_passed=final_state.get("regression_passed", False),
            regression_results=final_state.get("regression_results", []),
            improvement_score=final_state.get("improvement_score", 0.0),
            created_at=record.created_at or datetime.now(timezone.utc),
        )
