import pytest


class TestHealthEndpoint:
    """Tests for the /health endpoint."""

    @pytest.mark.asyncio
    async def test_health_returns_200(self, client):
        response = await client.get("/health")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_health_returns_status_and_version(self, client):
        response = await client.get("/health")
        data = response.json()
        assert data["status"] == "healthy"
        assert "version" in data
        assert data["version"] == "0.1.0"
