import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import httpx
import openai
import structlog

from backend.core.config import settings

logger = structlog.get_logger(__name__)


class TaskType(str, Enum):
    evaluation = "evaluation"
    rca = "rca"
    prompt_repair = "prompt_repair"
    preprocessing = "preprocessing"
    filtering = "filtering"
    drift_aggregation = "drift_aggregation"
    generation = "generation"  # generic / re-generation


# Tasks that require high reasoning capability
HIGH_REASONING_TASKS = {
    TaskType.evaluation,
    TaskType.rca,
    TaskType.prompt_repair,
}

# Approximate per-token costs (USD). Values intentionally conservative.
OPENAI_INPUT_COST_PER_1K = 0.005   # gpt-4o input
OPENAI_OUTPUT_COST_PER_1K = 0.015  # gpt-4o output
LOCAL_COST_PER_1K = 0.0            # local model is free


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Rough USD cost estimate for an LLM call."""
    if model.startswith("gpt"):
        return (
            (input_tokens / 1000.0) * OPENAI_INPUT_COST_PER_1K
            + (output_tokens / 1000.0) * OPENAI_OUTPUT_COST_PER_1K
        )
    return (input_tokens + output_tokens) / 1000.0 * LOCAL_COST_PER_1K


@dataclass
class RoutingResult:
    """Outcome of a router call."""
    content: str
    model_used: str
    task_type: str
    complexity_score: float
    fallback: bool = False
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: float = 0.0
    error: Optional[str] = None


class ModelRouter:
    """Routes tasks to the appropriate model based on complexity scoring.

    High-reasoning tasks (evaluation, RCA, prompt repair) -> OpenAI GPT-4o
    Lightweight tasks (preprocessing, filtering, drift) -> Llama 3.2 (local)
    """

    def __init__(self):
        self.openai_client = (
            openai.AsyncOpenAI(api_key=settings.openai_api_key)
            if settings.openai_api_key
            else None
        )
        self.local_endpoint = settings.local_model_endpoint
        self.local_model = settings.local_model_name
        self.complexity_threshold = settings.complexity_threshold

    def score_complexity(self, prompt: str, task_type: TaskType) -> float:
        """Score the complexity of a task from 0.0 (trivial) to 1.0 (complex)."""
        if task_type in HIGH_REASONING_TASKS:
            base_score = 0.8
        else:
            base_score = 0.3

        word_count = len(prompt.split())
        length_modifier = min(word_count / 500, 0.2)

        reasoning_keywords = [
            "analyze", "evaluate", "diagnose", "compare", "explain why",
            "root cause", "reasoning", "trade-off", "recommend",
        ]
        keyword_hits = sum(1 for kw in reasoning_keywords if kw in prompt.lower())
        keyword_modifier = min(keyword_hits * 0.05, 0.15)

        return min(base_score + length_modifier + keyword_modifier, 1.0)

    def select_model(self, prompt: str, task_type: TaskType) -> str:
        """Determine which model to use for a given task."""
        complexity = self.score_complexity(prompt, task_type)
        model = (
            settings.openai_model
            if complexity >= self.complexity_threshold
            else self.local_model
        )
        logger.info(
            "model_selected",
            task_type=task_type.value,
            complexity_score=round(complexity, 3),
            threshold=self.complexity_threshold,
            selected_model=model,
        )
        return model

    async def call_openai(
        self,
        prompt: str,
        system_prompt: str = "",
        temperature: float = 0.0,
        max_tokens: int = 2048,
    ) -> str:
        """Call OpenAI GPT-4o for high-reasoning tasks. Returns plain content (legacy)."""
        result = await self._call_openai_full(prompt, system_prompt, temperature, max_tokens)
        return result.content

    async def _call_openai_full(
        self,
        prompt: str,
        system_prompt: str,
        temperature: float,
        max_tokens: int,
    ) -> RoutingResult:
        if self.openai_client is None:
            raise RuntimeError("OpenAI client unavailable: ASD_OPENAI_API_KEY is not set")

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        t0 = time.perf_counter()
        response = await self.openai_client.chat.completions.create(
            model=settings.openai_model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        usage = response.usage
        input_tokens = getattr(usage, "prompt_tokens", 0) if usage else 0
        output_tokens = getattr(usage, "completion_tokens", 0) if usage else 0
        return RoutingResult(
            content=response.choices[0].message.content or "",
            model_used=settings.openai_model,
            task_type="",
            complexity_score=0.0,
            fallback=False,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=estimate_cost(settings.openai_model, input_tokens, output_tokens),
            latency_ms=elapsed_ms,
        )

    async def call_local(
        self,
        prompt: str,
        system_prompt: str = "",
    ) -> str:
        """Call local Llama via Ollama. Returns plain content (legacy)."""
        result = await self._call_local_full(prompt, system_prompt)
        return result.content

    async def _call_local_full(
        self,
        prompt: str,
        system_prompt: str,
    ) -> RoutingResult:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        t0 = time.perf_counter()
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{self.local_endpoint}/api/chat",
                json={
                    "model": self.local_model,
                    "messages": messages,
                    "stream": False,
                },
            )
            response.raise_for_status()
            payload = response.json()

        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        content = payload.get("message", {}).get("content", "")
        # Ollama returns prompt_eval_count and eval_count
        input_tokens = payload.get("prompt_eval_count", 0)
        output_tokens = payload.get("eval_count", 0)
        return RoutingResult(
            content=content,
            model_used=self.local_model,
            task_type="",
            complexity_score=0.0,
            fallback=False,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=estimate_cost(self.local_model, input_tokens, output_tokens),
            latency_ms=elapsed_ms,
        )

    async def route_and_call(
        self,
        prompt: str,
        task_type: TaskType,
        system_prompt: str = "",
        temperature: float = 0.0,
        max_tokens: int = 2048,
    ) -> tuple[str, str]:
        """Backwards-compat helper: returns (content, model_used)."""
        result = await self.route_and_call_full(
            prompt, task_type, system_prompt, temperature, max_tokens
        )
        return result.content, result.model_used

    async def route_and_call_full(
        self,
        prompt: str,
        task_type: TaskType,
        system_prompt: str = "",
        temperature: float = 0.0,
        max_tokens: int = 2048,
    ) -> RoutingResult:
        """Route to the appropriate model and return a typed RoutingResult.

        Falls back to local on OpenAI failure with `fallback=True`.
        """
        complexity = self.score_complexity(prompt, task_type)
        primary = self.select_model(prompt, task_type)

        if primary == settings.openai_model and self.openai_client is not None:
            try:
                result = await self._call_openai_full(
                    prompt, system_prompt, temperature, max_tokens
                )
                result.task_type = task_type.value
                result.complexity_score = complexity
                return result
            except Exception as e:
                logger.error("openai_call_failed", error=str(e))
                logger.warning("falling_back_to_local_model")
                try:
                    fallback_result = await self._call_local_full(prompt, system_prompt)
                    fallback_result.task_type = task_type.value
                    fallback_result.complexity_score = complexity
                    fallback_result.fallback = True
                    fallback_result.error = str(e)
                    return fallback_result
                except Exception as inner:
                    logger.error("local_fallback_failed", error=str(inner))
                    return RoutingResult(
                        content="",
                        model_used=settings.openai_model,
                        task_type=task_type.value,
                        complexity_score=complexity,
                        fallback=True,
                        error=f"openai={e}; local={inner}",
                    )

        # Primary is local (or OpenAI key missing)
        try:
            result = await self._call_local_full(prompt, system_prompt)
            result.task_type = task_type.value
            result.complexity_score = complexity
            return result
        except Exception as e:
            logger.error("local_model_call_failed", error=str(e))
            return RoutingResult(
                content="",
                model_used=self.local_model,
                task_type=task_type.value,
                complexity_score=complexity,
                fallback=False,
                error=str(e),
            )
