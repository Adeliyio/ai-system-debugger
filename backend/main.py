import logging
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.core.config import settings
from backend.storage.database import init_db, close_db
from backend.storage.cache import close_redis
from backend.api import (
    traces_router,
    analysis_router,
    healing_router,
    metrics_router,
    review_router,
)


# Configure structlog once at import time
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer() if settings.debug else structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(
        logging.DEBUG if settings.debug else logging.INFO
    ),
    cache_logger_on_first_use=True,
)
logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage startup and shutdown of database and cache connections."""
    if settings.debug:
        # Auto-create tables on dev start so the API works without alembic
        try:
            await init_db()
            logger.info("dev_mode_init_db_complete")
        except Exception as e:
            logger.warning("dev_mode_init_db_failed", error=str(e))

    yield

    await close_db()
    await close_redis()


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Production-grade AI observability and self-healing system for LLM pipelines",
    lifespan=lifespan,
)

# CORS middleware for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Register API routers
app.include_router(traces_router)
app.include_router(analysis_router)
app.include_router(healing_router)
app.include_router(metrics_router)
app.include_router(review_router)


@app.get("/health")
async def health_check():
    return {"status": "healthy", "version": settings.app_version}
