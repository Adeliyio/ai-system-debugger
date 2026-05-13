from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.dependencies import (
    get_cache_service,
    get_db,
    get_monitoring_service,
)
from backend.models.schemas import (
    CostMetrics,
    DriftMetrics,
    EvaluatorHealthResponse,
    EvaluatorType,
    LatencyMetricsResponse,
    PipelineMetrics,
    StructuralFailureCluster,
)
from backend.services.evaluation import recompute_evaluator_health
from backend.services.monitoring import MonitoringService
from backend.storage.cache import CacheService
from backend.storage.models import EvaluatorMetricsRecord


router = APIRouter(tags=["Metrics"])


@router.get("/metrics", response_model=PipelineMetrics)
async def get_pipeline_metrics(
    start_time: Optional[datetime] = Query(None),
    end_time: Optional[datetime] = Query(None),
    window_hours: int = Query(24, ge=1, le=720),
    service: MonitoringService = Depends(get_monitoring_service),
) -> PipelineMetrics:
    return await service.get_pipeline_metrics(start_time, end_time, window_hours)


@router.get("/metrics/cost", response_model=CostMetrics)
async def get_cost_metrics(
    start_time: Optional[datetime] = Query(None),
    end_time: Optional[datetime] = Query(None),
    window_hours: int = Query(24, ge=1, le=720),
    service: MonitoringService = Depends(get_monitoring_service),
) -> CostMetrics:
    """Aggregate cost metrics: total/model/evaluation USD, cost-per-trace, per-model breakdown."""
    return await service.get_cost_metrics(start_time, end_time, window_hours)


@router.get("/metrics/latency", response_model=LatencyMetricsResponse)
async def get_latency_metrics(
    start_time: Optional[datetime] = Query(None),
    end_time: Optional[datetime] = Query(None),
    window_hours: int = Query(24, ge=1, le=720),
    service: MonitoringService = Depends(get_monitoring_service),
) -> LatencyMetricsResponse:
    """P50/P90/P99 latency per pipeline component (preprocessing/retrieval/generation/evaluation)."""
    return await service.get_latency_metrics(start_time, end_time, window_hours)


@router.get("/metrics/structural-failures", response_model=list[StructuralFailureCluster])
async def get_structural_failures(
    min_count: int = Query(3, ge=1, le=100),
    service: MonitoringService = Depends(get_monitoring_service),
) -> list[StructuralFailureCluster]:
    """Recurring failure clusters with >= min_count occurrences."""
    return await service.get_structural_failures(min_count)


@router.get("/evaluator-health", response_model=list[EvaluatorHealthResponse])
async def get_evaluator_health(
    db: AsyncSession = Depends(get_db),
    cache: CacheService = Depends(get_cache_service),
) -> list[EvaluatorHealthResponse]:
    """Latest precision/recall/F1/agreement per evaluator."""
    cached = await cache.get_evaluator_health()
    if cached:
        return [EvaluatorHealthResponse(**item) for item in cached]

    results = []
    for eval_type in EvaluatorType:
        query = (
            select(EvaluatorMetricsRecord)
            .where(EvaluatorMetricsRecord.evaluator_type == eval_type.value)
            .order_by(EvaluatorMetricsRecord.calibrated_at.desc())
            .limit(1)
        )
        record = (await db.execute(query)).scalar_one_or_none()

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

    await cache.set_evaluator_health([r.model_dump() for r in results])
    return results


@router.post("/evaluator-health/recalibrate", response_model=list[EvaluatorHealthResponse])
async def recalibrate_evaluators(
    db: AsyncSession = Depends(get_db),
    cache: CacheService = Depends(get_cache_service),
) -> list[EvaluatorHealthResponse]:
    """Recompute evaluator metrics from labelled human review queue."""
    records = await recompute_evaluator_health(db)
    await cache.delete("metrics:evaluator_health")
    return [
        EvaluatorHealthResponse(
            evaluator_type=EvaluatorType(r.evaluator_type),
            accuracy=r.accuracy,
            precision=r.precision,
            recall=r.recall,
            f1_score=r.f1_score,
            agreement_rate=r.agreement_rate,
            total_evaluations=r.total_evaluations,
            last_calibrated=r.calibrated_at,
        )
        for r in records
    ]


@router.get("/drift", response_model=list[DriftMetrics])
async def get_drift_metrics(
    service: MonitoringService = Depends(get_monitoring_service),
) -> list[DriftMetrics]:
    """Drift across failure_rate, mean_latency, healing_success_rate."""
    metrics_to_check = ["failure_rate", "mean_latency", "healing_success_rate"]
    results = []
    for metric_name in metrics_to_check:
        results.append(await service.detect_drift(metric_name))
    return results
