import pytest


class TestAnalysisEndpoint:
    """Tests for the /analyze endpoint."""

    @pytest.mark.asyncio
    async def test_analyze_validates_input(self, client):
        response = await client.post("/analyze", json={})
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_analyze_requires_trace_id(self, client):
        response = await client.post("/analyze", json={"reference_response": "test"})
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_analyze_not_found_for_bad_trace(self, client):
        response = await client.post(
            "/analyze",
            json={"trace_id": "nonexistent-trace-id"},
        )
        assert response.status_code == 404


class TestHealingEndpoints:
    """Tests for the /rca, /fix, and /compare endpoints."""

    @pytest.mark.asyncio
    async def test_rca_validates_input(self, client):
        response = await client.post("/rca", json={})
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_rca_requires_both_ids(self, client):
        response = await client.post(
            "/rca",
            json={"trace_id": "test"},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_fix_validates_input(self, client):
        response = await client.post("/fix", json={})
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_compare_validates_input(self, client):
        response = await client.post("/compare", json={})
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_compare_not_found_for_bad_trace(self, client):
        response = await client.post(
            "/compare",
            json={"trace_id": "bad-id", "healing_id": "bad-id"},
        )
        assert response.status_code == 404
