from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.core.config import settings
from backend.storage.database import close_db
from backend.storage.cache import close_redis
from backend.api import traces_router, analysis_router, healing_router, metrics_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage startup and shutdown of database and cache connections."""
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


@app.get("/health")
async def health_check():
    return {"status": "healthy", "version": settings.app_version}
