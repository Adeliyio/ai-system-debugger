import pytest


class TestTraceEndpoints:
    """Tests for the /trace endpoints."""

    @pytest.mark.asyncio
    async def test_submit_trace_returns_201(self, client):
        payload = {
            "session_id": "test-session-001",
            "prompt": "What is Python?",
            "response": "Python is a programming language.",
            "model_used": "gpt-4o",
            "context_documents": ["Python documentation excerpt"],
            "latency_ms": 150.0,
            "token_count_input": 10,
            "token_count_output": 8,
            "metadata": {"test": True},
        }

        response = await client.post("/trace", json=payload)
        assert response.status_code == 201

        data = response.json()
        assert data["session_id"] == "test-session-001"
        assert data["prompt"] == "What is Python?"
        assert data["status"] == "pending"
        assert "id" in data
        assert "created_at" in data

    @pytest.mark.asyncio
    async def test_submit_trace_validates_input(self, client):
        payload = {
            "session_id": "test",
            # Missing required fields
        }

        response = await client.post("/trace", json=payload)
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_get_trace_not_found(self, client):
        response = await client.get("/trace/nonexistent-id")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_submit_trace_with_empty_context(self, client):
        payload = {
            "session_id": "test-session-002",
            "prompt": "Hello",
            "response": "Hi there",
            "model_used": "llama3.2",
            "latency_ms": 50.0,
            "token_count_input": 2,
            "token_count_output": 3,
        }

        response = await client.post("/trace", json=payload)
        assert response.status_code == 201

        data = response.json()
        assert data["context_documents"] == []
        assert data["metadata"] == {}
