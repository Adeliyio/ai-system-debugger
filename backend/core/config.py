from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Application
    app_name: str = "AI System Debugger"
    app_version: str = "0.1.0"
    debug: bool = False

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:5173"]

    # Database
    database_url: str = "postgresql+asyncpg://localhost:5432/ai_debugger"
    redis_url: str = "redis://localhost:6379/0"

    # OpenAI
    openai_api_key: Optional[str] = None
    openai_model: str = "gpt-4o"

    # Local Model (Llama)
    local_model_endpoint: str = "http://localhost:11434"
    local_model_name: str = "llama3.2"

    # Routing
    complexity_threshold: float = 0.65

    # Evaluation
    similarity_threshold: float = 0.65
    ensemble_agreement_threshold: int = 2  # out of 3 evaluators

    # Self-Healing
    max_repair_attempts: int = 2
    regression_suite_size: int = 20
    relevance_degradation_limit: float = 0.05  # 5%

    # A/B Testing
    shadow_traffic_percentage: float = 0.10  # 10%
    shadow_test_duration_hours: int = 24

    # Drift Detection
    drift_window_days: int = 7

    model_config = {"env_file": ".env", "env_prefix": "ASD_"}


settings = Settings()
