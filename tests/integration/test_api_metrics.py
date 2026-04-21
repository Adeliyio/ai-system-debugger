import pytest


class TestMetricsEndpoints:
    """Tests for the /metrics, /evaluator-health, and /drift endpoints."""

    @pytest.mark.asyncio
    async def test_metrics_accepts_default_params(self, client):
        # Will fail due to mock DB not returning proper aggregates,
        # but should at least accept the request without validation errors
        response = await client.get("/metrics")
        # Could be 200 or 500 depending on mock behavior, but not 422
        assert response.status_code != 422

    @pytest.mark.asyncio
    async def test_metrics_accepts_window_hours_param(self, client):
        response = await client.get("/metrics?window_hours=48")
        assert response.status_code != 422

    @pytest.mark.asyncio
    async def test_metrics_rejects_invalid_window(self, client):
        response = await client.get("/metrics?window_hours=0")
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_metrics_rejects_too_large_window(self, client):
        response = await client.get("/metrics?window_hours=999")
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_evaluator_health_endpoint_exists(self, client):
        response = await client.get("/evaluator-health")
        assert response.status_code != 404

    @pytest.mark.asyncio
    async def test_drift_endpoint_exists(self, client):
        response = await client.get("/drift")
        assert response.status_code != 404
