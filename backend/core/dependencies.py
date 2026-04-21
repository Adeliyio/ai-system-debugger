from collections.abc import AsyncGenerator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.storage.database import get_db
from backend.storage.cache import get_redis, CacheService
from backend.services.instrumentation import InstrumentationService
from backend.services.routing import ModelRouter
from backend.services.monitoring import MonitoringService
from backend.services.evaluation import EvaluationService
from backend.services.rca import RCAService
from backend.services.healing import HealingService

# Singleton router instance (stateless, holds API clients)
_model_router: ModelRouter | None = None


def get_model_router() -> ModelRouter:
    global _model_router
    if _model_router is None:
        _model_router = ModelRouter()
    return _model_router


async def get_cache_service() -> CacheService:
    client = await get_redis()
    return CacheService(client)


async def get_instrumentation_service(
    db: AsyncSession = Depends(get_db),
) -> InstrumentationService:
    return InstrumentationService(db)


async def get_monitoring_service(
    db: AsyncSession = Depends(get_db),
    cache: CacheService = Depends(get_cache_service),
) -> MonitoringService:
    return MonitoringService(db, cache)


async def get_evaluation_service(
    db: AsyncSession = Depends(get_db),
    router: ModelRouter = Depends(get_model_router),
) -> EvaluationService:
    return EvaluationService(db, router)


async def get_rca_service(
    db: AsyncSession = Depends(get_db),
    router: ModelRouter = Depends(get_model_router),
) -> RCAService:
    return RCAService(db, router)


async def get_healing_service(
    db: AsyncSession = Depends(get_db),
    router: ModelRouter = Depends(get_model_router),
) -> HealingService:
    return HealingService(db, router)
