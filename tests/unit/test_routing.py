import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from backend.services.routing.router import ModelRouter, TaskType


class TestComplexityScoring:
    """Tests for the complexity scoring algorithm."""

    def setup_method(self):
        with patch("backend.services.routing.router.openai"):
            self.router = ModelRouter()

    def test_high_reasoning_task_gets_high_base_score(self):
        score = self.router.score_complexity("simple prompt", TaskType.evaluation)
        assert score >= 0.8

    def test_lightweight_task_gets_low_base_score(self):
        score = self.router.score_complexity("simple prompt", TaskType.preprocessing)
        assert score <= 0.5

    def test_rca_task_is_high_reasoning(self):
        score = self.router.score_complexity("analyze this", TaskType.rca)
        assert score >= 0.8

    def test_prompt_repair_is_high_reasoning(self):
        score = self.router.score_complexity("fix this", TaskType.prompt_repair)
        assert score >= 0.8

    def test_long_prompt_increases_score(self):
        short_score = self.router.score_complexity("hello", TaskType.preprocessing)
        long_prompt = "analyze " * 200
        long_score = self.router.score_complexity(long_prompt, TaskType.preprocessing)
        assert long_score > short_score

    def test_reasoning_keywords_increase_score(self):
        plain_score = self.router.score_complexity("do something", TaskType.preprocessing)
        reasoning_score = self.router.score_complexity(
            "analyze and evaluate the root cause, explain why this trade-off matters",
            TaskType.preprocessing,
        )
        assert reasoning_score > plain_score

    def test_score_never_exceeds_one(self):
        long_prompt = "analyze evaluate diagnose compare explain why root cause reasoning trade-off recommend " * 50
        score = self.router.score_complexity(long_prompt, TaskType.evaluation)
        assert score <= 1.0

    def test_score_is_always_non_negative(self):
        score = self.router.score_complexity("", TaskType.filtering)
        assert score >= 0.0


class TestModelSelection:
    """Tests for model selection based on complexity."""

    def setup_method(self):
        with patch("backend.services.routing.router.openai"):
            self.router = ModelRouter()

    def test_high_complexity_routes_to_openai(self):
        model = self.router.select_model("analyze this complex issue", TaskType.evaluation)
        assert model == "gpt-4o"

    def test_low_complexity_routes_to_local(self):
        model = self.router.select_model("filter this", TaskType.filtering)
        assert model == "llama3.2"

    def test_rca_always_routes_to_openai(self):
        model = self.router.select_model("why did this fail", TaskType.rca)
        assert model == "gpt-4o"


class TestModelCalls:
    """Tests for API calls to models."""

    def setup_method(self):
        with patch("backend.services.routing.router.openai"):
            self.router = ModelRouter()

    @pytest.mark.asyncio
    async def test_openai_fallback_on_error(self):
        """When OpenAI fails, should fall back to local model."""
        self.router.openai_client.chat.completions.create = AsyncMock(
            side_effect=Exception("API error")
        )
        self.router.call_local = AsyncMock(return_value="fallback response")

        result = await self.router.call_openai("test prompt")
        assert result == "fallback response"
        self.router.call_local.assert_called_once()

    @pytest.mark.asyncio
    async def test_route_and_call_returns_tuple(self):
        """route_and_call should return (response, model_used)."""
        self.router.call_openai = AsyncMock(return_value="openai response")

        response, model = await self.router.route_and_call(
            "analyze this", TaskType.evaluation
        )
        assert response == "openai response"
        assert model == "gpt-4o"
