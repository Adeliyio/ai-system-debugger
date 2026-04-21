from datetime import datetime, timezone, timedelta

import structlog
from sqlalchemy import select, func, case
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.models.schemas import (
    PipelineMetrics,
    DriftMetrics,
    TraceStatus,
    FailureSource,
)
from backend.storage.models import TraceRecord, EvaluationRecord, HealingRecord, RCARecord
from backend.storage.cache import CacheService

logger = structlog.get_logger(__name__)


class MonitoringService:
    """Real-time monitoring for AI pipeline health, metrics, and drift detection."""

    def __init__(self, db: AsyncSession, cache: CacheService):
        self.db = db
        self.cache = cache

    async def get_pipeline_metrics(
        self,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        window_hours: int = 24,
    ) -> PipelineMetrics:
        """Compute aggregate pipeline metrics over a time window."""
        now = datetime.now(timezone.utc)
        end = end_time or now
        start = start_time or (end - timedelta(hours=window_hours))

        # Check cache first
        cache_key = f"{start.isoformat()}_{end.isoformat()}"
        cached = await self.cache.get_pipeline_metrics(cache_key)
        if cached:
            return PipelineMetrics(**cached)

        # Total traces and status breakdown
        status_query = (
            select(
                TraceRecord.status,
                func.count(TraceRecord.id).label("count"),
            )
            .where(TraceRecord.created_at.between(start, end))
            .group_by(TraceRecord.status)
        )
        status_result = await self.db.execute(status_query)
        traces_by_status = {row.status: row.count for row in status_result}
        total_traces = sum(traces_by_status.values())

        # Latency statistics
        latency_query = select(
            func.avg(TraceRecord.latency_ms).label("mean"),
            func.percentile_cont(0.95).within_group(TraceRecord.latency_ms).label("p95"),
            func.percentile_cont(0.99).within_group(TraceRecord.latency_ms).label("p99"),
        ).where(TraceRecord.created_at.between(start, end))
        latency_result = await self.db.execute(latency_query)
        latency_row = latency_result.one()

        # Failure rate from evaluations
        eval_query = select(
            func.count(EvaluationRecord.id).label("total"),
            func.sum(case((EvaluationRecord.failure_detected.is_(True), 1), else_=0)).label("failures"),
        ).where(EvaluationRecord.created_at.between(start, end))
        eval_result = await self.db.execute(eval_query)
        eval_row = eval_result.one()
        failure_rate = (eval_row.failures / eval_row.total) if eval_row.total > 0 else 0.0

        # Healing success rate
        healing_query = select(
            func.count(HealingRecord.id).label("total"),
            func.sum(case((HealingRecord.regression_passed.is_(True), 1), else_=0)).label("successes"),
        ).where(HealingRecord.created_at.between(start, end))
        healing_result = await self.db.execute(healing_query)
        healing_row = healing_result.one()
        healing_success_rate = (healing_row.successes / healing_row.total) if healing_row.total > 0 else 0.0

        # Top failure sources from RCA
        rca_query = (
            select(
                RCARecord.primary_source,
                func.count(RCARecord.id).label("count"),
            )
            .where(RCARecord.created_at.between(start, end))
            .group_by(RCARecord.primary_source)
            .order_by(func.count(RCARecord.id).desc())
        )
        rca_result = await self.db.execute(rca_query)
        top_failure_sources = {
            FailureSource(row.primary_source): row.count for row in rca_result
        }

        # Model usage breakdown
        model_query = (
            select(
                TraceRecord.model_used,
                func.count(TraceRecord.id).label("count"),
            )
            .where(TraceRecord.created_at.between(start, end))
            .group_by(TraceRecord.model_used)
        )
        model_result = await self.db.execute(model_query)
        model_usage = {row.model_used: row.count for row in model_result}

        metrics = PipelineMetrics(
            total_traces=total_traces,
            failure_rate=round(failure_rate, 4),
            mean_latency_ms=round(latency_row.mean or 0, 2),
            p95_latency_ms=round(latency_row.p95 or 0, 2),
            p99_latency_ms=round(latency_row.p99 or 0, 2),
            healing_success_rate=round(healing_success_rate, 4),
            top_failure_sources=top_failure_sources,
            model_usage=model_usage,
            traces_by_status={
                TraceStatus(k): v for k, v in traces_by_status.items()
            },
            period_start=start,
            period_end=end,
        )

        # Cache the result
        await self.cache.set_pipeline_metrics(cache_key, metrics.model_dump())

        logger.info(
            "pipeline_metrics_computed",
            total_traces=total_traces,
            failure_rate=round(failure_rate, 4),
            window_hours=window_hours,
        )

        return metrics

    async def detect_drift(self, metric_name: str = "failure_rate") -> DriftMetrics:
        """Detect drift by comparing recent metrics against a baseline window.

        Compares the most recent window_days against the prior window_days.
        """
        now = datetime.now(timezone.utc)
        window = timedelta(days=settings.drift_window_days)

        current_start = now - window
        baseline_start = current_start - window
        baseline_end = current_start

        if metric_name == "failure_rate":
            current_value = await self._compute_failure_rate(current_start, now)
            baseline_value = await self._compute_failure_rate(baseline_start, baseline_end)
        elif metric_name == "mean_latency":
            current_value = await self._compute_mean_latency(current_start, now)
            baseline_value = await self._compute_mean_latency(baseline_start, baseline_end)
        elif metric_name == "healing_success_rate":
            current_value = await self._compute_healing_rate(current_start, now)
            baseline_value = await self._compute_healing_rate(baseline_start, baseline_end)
        else:
            raise ValueError(f"Unknown metric: {metric_name}")

        drift_magnitude = abs(current_value - baseline_value)
        is_drifting = drift_magnitude > settings.relevance_degradation_limit

        logger.info(
            "drift_detected" if is_drifting else "drift_within_bounds",
            metric=metric_name,
            current=round(current_value, 4),
            baseline=round(baseline_value, 4),
            magnitude=round(drift_magnitude, 4),
        )

        return DriftMetrics(
            metric_name=metric_name,
            current_value=round(current_value, 4),
            baseline_value=round(baseline_value, 4),
            drift_magnitude=round(drift_magnitude, 4),
            is_drifting=is_drifting,
            window_days=settings.drift_window_days,
        )

    async def _compute_failure_rate(self, start: datetime, end: datetime) -> float:
        query = select(
            func.count(EvaluationRecord.id).label("total"),
            func.sum(case((EvaluationRecord.failure_detected.is_(True), 1), else_=0)).label("failures"),
        ).where(EvaluationRecord.created_at.between(start, end))
        result = await self.db.execute(query)
        row = result.one()
        return (row.failures / row.total) if row.total > 0 else 0.0

    async def _compute_mean_latency(self, start: datetime, end: datetime) -> float:
        query = select(
            func.avg(TraceRecord.latency_ms).label("mean"),
        ).where(TraceRecord.created_at.between(start, end))
        result = await self.db.execute(query)
        row = result.one()
        return row.mean or 0.0

    async def _compute_healing_rate(self, start: datetime, end: datetime) -> float:
        query = select(
            func.count(HealingRecord.id).label("total"),
            func.sum(case((HealingRecord.regression_passed.is_(True), 1), else_=0)).label("successes"),
        ).where(HealingRecord.created_at.between(start, end))
        result = await self.db.execute(query)
        row = result.one()
        return (row.successes / row.total) if row.total > 0 else 0.0
