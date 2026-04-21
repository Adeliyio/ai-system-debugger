import json
from typing import Any, Optional

import redis.asyncio as redis

from backend.core.config import settings

_redis_pool: Optional[redis.Redis] = None


async def get_redis() -> redis.Redis:
    """Get or create the Redis connection pool."""
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = redis.from_url(
            settings.redis_url,
            decode_responses=True,
            max_connections=20,
        )
    return _redis_pool


async def close_redis() -> None:
    """Close the Redis connection pool."""
    global _redis_pool
    if _redis_pool is not None:
        await _redis_pool.close()
        _redis_pool = None


class CacheService:
    """Async Redis cache for metrics, traces, and frequently accessed data."""

    def __init__(self, client: redis.Redis):
        self.client = client
        self.default_ttl = 300  # 5 minutes

    async def get(self, key: str) -> Optional[Any]:
        """Get a cached value, returning None if not found."""
        value = await self.client.get(key)
        if value is None:
            return None
        return json.loads(value)

    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Cache a value with optional TTL override."""
        serialized = json.dumps(value, default=str)
        await self.client.set(key, serialized, ex=ttl or self.default_ttl)

    async def delete(self, key: str) -> None:
        """Remove a cached value."""
        await self.client.delete(key)

    async def invalidate_pattern(self, pattern: str) -> None:
        """Delete all keys matching a pattern."""
        cursor = 0
        while True:
            cursor, keys = await self.client.scan(cursor, match=pattern, count=100)
            if keys:
                await self.client.delete(*keys)
            if cursor == 0:
                break

    # --- Domain-specific cache methods ---

    async def get_pipeline_metrics(self, window_key: str) -> Optional[dict]:
        return await self.get(f"metrics:pipeline:{window_key}")

    async def set_pipeline_metrics(self, window_key: str, metrics: dict) -> None:
        await self.set(f"metrics:pipeline:{window_key}", metrics, ttl=60)

    async def get_trace(self, trace_id: str) -> Optional[dict]:
        return await self.get(f"trace:{trace_id}")

    async def set_trace(self, trace_id: str, trace_data: dict) -> None:
        await self.set(f"trace:{trace_id}", trace_data, ttl=600)

    async def invalidate_trace(self, trace_id: str) -> None:
        await self.delete(f"trace:{trace_id}")

    async def get_evaluator_health(self) -> Optional[list[dict]]:
        return await self.get("metrics:evaluator_health")

    async def set_evaluator_health(self, health_data: list[dict]) -> None:
        await self.set("metrics:evaluator_health", health_data, ttl=120)

    async def increment_counter(self, key: str) -> int:
        """Increment a counter (e.g., for rate limiting or tracking)."""
        return await self.client.incr(f"counter:{key}")
