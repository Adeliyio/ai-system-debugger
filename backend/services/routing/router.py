from enum import Enum

import structlog
import openai
import httpx

from backend.core.config import settings

logger = structlog.get_logger(__name__)


class TaskType(str, Enum):
    evaluation = "evaluation"
    rca = "rca"
    prompt_repair = "prompt_repair"
    preprocessing = "preprocessing"
    filtering = "filtering"
    drift_aggregation = "drift_aggregation"


# Tasks that require high reasoning capability
HIGH_REASONING_TASKS = {
    TaskType.evaluation,
    TaskType.rca,
    TaskType.prompt_repair,
}


class ModelRouter:
    """Routes tasks to the appropriate model based on complexity scoring.

    High-reasoning tasks (evaluation, RCA, prompt repair) -> OpenAI GPT-4o
    Lightweight tasks (preprocessing, filtering, drift) -> Llama 3.2 (local)
    """

    def __init__(self):
        self.openai_client = openai.AsyncOpenAI(api_key=settings.openai_api_key)
        self.local_endpoint = settings.local_model_endpoint
        self.local_model = settings.local_model_name
        self.complexity_threshold = settings.complexity_threshold

    def score_complexity(self, prompt: str, task_type: TaskType) -> float:
        """Score the complexity of a task from 0.0 (trivial) to 1.0 (complex).

        Uses a combination of task type classification and prompt heuristics.
        """
        # Base score from task type
        if task_type in HIGH_REASONING_TASKS:
            base_score = 0.8
        else:
            base_score = 0.3

        # Adjust based on prompt characteristics
        word_count = len(prompt.split())
        length_modifier = min(word_count / 500, 0.2)  # Up to +0.2 for long prompts

        # Check for reasoning indicators
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

        if complexity >= self.complexity_threshold:
            model = settings.openai_model
        else:
            model = self.local_model

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
        """Call OpenAI GPT-4o for high-reasoning tasks."""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        try:
            response = await self.openai_client.chat.completions.create(
                model=settings.openai_model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error("openai_call_failed", error=str(e))
            # Fallback to local model
            logger.warning("falling_back_to_local_model")
            return await self.call_local(prompt, system_prompt)

    async def call_local(
        self,
        prompt: str,
        system_prompt: str = "",
    ) -> str:
        """Call local Llama model via Ollama API for lightweight tasks."""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        try:
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
                return response.json()["message"]["content"]
        except Exception as e:
            logger.error("local_model_call_failed", error=str(e))
            raise

    async def route_and_call(
        self,
        prompt: str,
        task_type: TaskType,
        system_prompt: str = "",
        temperature: float = 0.0,
        max_tokens: int = 2048,
    ) -> tuple[str, str]:
        """Route to the appropriate model and return (response, model_used)."""
        model = self.select_model(prompt, task_type)

        if model == settings.openai_model:
            response = await self.call_openai(
                prompt, system_prompt, temperature, max_tokens
            )
        else:
            response = await self.call_local(prompt, system_prompt)

        return response, model
