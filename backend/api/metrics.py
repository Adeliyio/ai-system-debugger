from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.schemas import (
    PipelineMetrics,
    EvaluatorHealthResponse,
    DriftMetrics,
    EvaluatorType,
)
from backend.services.monitoring import MonitoringService
from backend.storage.database import get_db
from backend.storage.models import EvaluatorMetricsRecord
from backend.storage.cache import CacheService
from backend.core.dependencies import get_monitoring_service, get_cache_service

router = APIRouter(tags=["Metrics"])


@router.get("/metrics", response_model=PipelineMetrics)
async def get_pipeline_metrics(
    start_time: Optional[datetime] = Query(None, description="Window start (ISO 8601)"),
    end_time: Optional[datetime] = Query(None, description="Window end (ISO 8601)"),
    window_hours: int = Query(24, ge=1, le=720, description="Lookback window in hours"),
    service: MonitoringService = Depends(get_monitoring_service),
) -> PipelineMetrics:
    """Get aggregate pipeline metrics over a time window.

    Returns trace counts, failure rate, latency percentiles, healing success rate,
    top failure sources, and model usage breakdown.
    """
    return await service.get_pipeline_metrics(start_time, end_time, window_hours)


@router.get("/evaluator-health", response_model=list[EvaluatorHealthResponse])
async def get_evaluator_health(
    db: AsyncSession = Depends(get_db),
    cache: CacheService = Depends(get_cache_service),
) -> list[EvaluatorHealthResponse]:
    """Get reliability metrics for each evaluator in the ensemble.

    Returns accuracy, precision, recall, F1 score, and agreement rate
    for the LLM judge, embedding similarity, and rule-based evaluators.
    """
    # Check cache
    cached = await cache.get_evaluator_health()
    if cached:
        return [EvaluatorHealthResponse(**item) for item in cached]

    # Query latest metrics for each evaluator type
    results = []
    for eval_type in EvaluatorType:
        query = (
            select(EvaluatorMetricsRecord)
            .where(EvaluatorMetricsRecord.evaluator_type == eval_type.value)
            .order_by(EvaluatorMetricsRecord.calibrated_at.desc())
            .limit(1)
        )
        result = await db.execute(query)
        record = result.scalar_one_or_none()

        if record:
            results.append(EvaluatorHealthResponse(
                evaluator_type=EvaluatorType(record.evaluator_type),
                accuracy=record.accuracy,
                precision=record.precision,
                recall=record.recall,
                f1_score=record.f1_score,
                agreement_rate=record.agreement_rate,
                total_evaluations=record.total_evaluations,
                last_calibrated=record.calibrated_at,
            ))
        else:
            # Return defaults for uncalibrated evaluators
            results.append(EvaluatorHealthResponse(
                evaluator_type=eval_type,
                accuracy=0.0,
                precision=0.0,
                recall=0.0,
                f1_score=0.0,
                agreement_rate=0.0,
                total_evaluations=0,
                last_calibrated=None,
            ))

    # Cache the result
    await cache.set_evaluator_health([r.model_dump() for r in results])

    return results


@router.get("/drift", response_model=list[DriftMetrics])
async def get_drift_metrics(
    service: MonitoringService = Depends(get_monitoring_service),
) -> list[DriftMetrics]:
    """Detect drift across key pipeline metrics.

    Compares recent metric values against a historical baseline window
    and flags metrics that have drifted beyond the configured threshold.
    """
    metrics_to_check = ["failure_rate", "mean_latency", "healing_success_rate"]
    results = []

    for metric_name in metrics_to_check:
        drift = await service.detect_drift(metric_name)
        results.append(drift)

    return results
