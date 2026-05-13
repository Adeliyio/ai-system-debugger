from datetime import datetime, timezone, timedelta

import structlog
from sqlalchemy import select, func, case, desc
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.models.schemas import (
    CostMetrics,
    DriftMetrics,
    FailureSource,
    FailureType,
    LatencyComponentMetric,
    LatencyMetricsResponse,
    PipelineMetrics,
    StructuralFailureCluster,
    TraceStatus,
)
from backend.storage.cache import CacheService
from backend.storage.models import (
    EvaluationRecord,
    FailureClusterRecord,
    HealingRecord,
    RCARecord,
    TraceRecord,
)

logger = structlog.get_logger(__name__)


class MonitoringService:
    """Real-time monitoring for AI pipeline health, cost, latency, drift, and structural failures."""

    def __init__(self, db: AsyncSession, cache: CacheService):
        self.db = db
        self.cache = cache

    async def get_pipeline_metrics(
        self,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        window_hours: int = 24,
    ) -> PipelineMetrics:
        now = datetime.now(timezone.utc)
        end = end_time or now
        start = start_time or (end - timedelta(hours=window_hours))

        cache_key = f"{start.isoformat()}_{end.isoformat()}"
        cached = await self.cache.get_pipeline_metrics(cache_key)
        if cached:
            return PipelineMetrics(**cached)

        # Status breakdown
        status_query = (
            select(TraceRecord.status, func.count(TraceRecord.id).label("count"))
            .where(TraceRecord.created_at.between(start, end))
            .group_by(TraceRecord.status)
        )
        status_result = await self.db.execute(status_query)
        traces_by_status = {row.status: row.count for row in status_result}
        total_traces = sum(traces_by_status.values())

        # Latency
        latency_query = select(
            func.avg(TraceRecord.latency_ms).label("mean"),
            func.percentile_cont(0.95).within_group(TraceRecord.latency_ms).label("p95"),
            func.percentile_cont(0.99).within_group(TraceRecord.latency_ms).label("p99"),
        ).where(TraceRecord.created_at.between(start, end))
        latency_result = await self.db.execute(latency_query)
        latency_row = latency_result.one()

        # Failures
        eval_query = select(
            func.count(EvaluationRecord.id).label("total"),
            func.sum(case((EvaluationRecord.failure_detected.is_(True), 1), else_=0)).label("failures"),
        ).where(EvaluationRecord.created_at.between(start, end))
        eval_row = (await self.db.execute(eval_query)).one()
        failure_rate = (eval_row.failures / eval_row.total) if eval_row.total else 0.0

        # Healing success
        healing_query = select(
            func.count(HealingRecord.id).label("total"),
            func.sum(case((HealingRecord.regression_passed.is_(True), 1), else_=0)).label("successes"),
        ).where(HealingRecord.created_at.between(start, end))
        healing_row = (await self.db.execute(healing_query)).one()
        healing_success_rate = (healing_row.successes / healing_row.total) if healing_row.total else 0.0

        # Top failure sources
        rca_query = (
            select(RCARecord.primary_source, func.count(RCARecord.id).label("count"))
            .where(RCARecord.created_at.between(start, end))
            .group_by(RCARecord.primary_source)
            .order_by(desc("count"))
        )
        rca_result = await self.db.execute(rca_query)
        top_failure_sources = {
            FailureSource(row.primary_source): row.count for row in rca_result
        }

        # Model usage
        model_query = (
            select(TraceRecord.model_used, func.count(TraceRecord.id).label("count"))
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
        await self.cache.set_pipeline_metrics(cache_key, metrics.model_dump())
        return metrics

    async def get_cost_metrics(
        self,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        window_hours: int = 24,
    ) -> CostMetrics:
        now = datetime.now(timezone.utc)
        end = end_time or now
        start = start_time or (end - timedelta(hours=window_hours))

        totals_query = select(
            func.coalesce(func.sum(TraceRecord.total_cost_usd), 0.0).label("total"),
            func.coalesce(func.sum(TraceRecord.model_cost_usd), 0.0).label("model"),
            func.coalesce(func.sum(TraceRecord.evaluation_cost_usd), 0.0).label("evaluation"),
            func.count(TraceRecord.id).label("trace_count"),
        ).where(TraceRecord.created_at.between(start, end))
        totals = (await self.db.execute(totals_query)).one()

        per_model_query = (
            select(
                TraceRecord.model_used,
                func.coalesce(func.sum(TraceRecord.total_cost_usd), 0.0).label("cost"),
            )
            .where(TraceRecord.created_at.between(start, end))
            .group_by(TraceRecord.model_used)
        )
        per_model = await self.db.execute(per_model_query)
        cost_by_model = {row.model_used: float(row.cost) for row in per_model}

        cost_per_trace = (
            float(totals.total) / totals.trace_count if totals.trace_count else 0.0
        )
        return CostMetrics(
            total_cost_usd=round(float(totals.total), 6),
            model_cost_usd=round(float(totals.model), 6),
            evaluation_cost_usd=round(float(totals.evaluation), 6),
            cost_per_trace=round(cost_per_trace, 6),
            cost_by_model=cost_by_model,
            period_start=start,
            period_end=end,
        )

    async def get_latency_metrics(
        self,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        window_hours: int = 24,
    ) -> LatencyMetricsResponse:
        now = datetime.now(timezone.utc)
        end = end_time or now
        start = start_time or (end - timedelta(hours=window_hours))

        # Pull all latency_breakdown JSON rows in window and compute percentiles in Python.
        # This avoids per-component CTEs and stays portable.
        rows_q = select(
            TraceRecord.latency_ms,
            TraceRecord.latency_breakdown,
        ).where(TraceRecord.created_at.between(start, end))
        rows = (await self.db.execute(rows_q)).all()

        components: dict[str, list[float]] = {
            "preprocessing": [],
            "retrieval": [],
            "generation": [],
            "evaluation": [],
            "total": [],
        }
        for row in rows:
            bd = row.latency_breakdown or {}
            for c in ("preprocessing_ms", "retrieval_ms", "generation_ms", "evaluation_ms"):
                v = bd.get(c)
                if v is not None:
                    components[c.replace("_ms", "")].append(float(v))
            if row.latency_ms is not None:
                components["total"].append(float(row.latency_ms))

        def percentile(values: list[float], p: float) -> float:
            if not values:
                return 0.0
            values = sorted(values)
            k = max(0, min(len(values) - 1, int(round((p / 100.0) * (len(values) - 1)))))
            return values[k]

        result_components = []
        for name, vals in components.items():
            result_components.append(LatencyComponentMetric(
                component=name,
                p50_ms=round(percentile(vals, 50), 2),
                p90_ms=round(percentile(vals, 90), 2),
                p99_ms=round(percentile(vals, 99), 2),
                sample_count=len(vals),
            ))

        return LatencyMetricsResponse(
            components=result_components,
            period_start=start,
            period_end=end,
        )

    async def detect_drift(self, metric_name: str = "failure_rate") -> DriftMetrics:
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
        return DriftMetrics(
            metric_name=metric_name,
            current_value=round(current_value, 4),
            baseline_value=round(baseline_value, 4),
            drift_magnitude=round(drift_magnitude, 4),
            is_drifting=is_drifting,
            window_days=settings.drift_window_days,
        )

    async def get_structural_failures(self, min_count: int = 3) -> list[StructuralFailureCluster]:
        q = (
            select(FailureClusterRecord)
            .where(FailureClusterRecord.occurrence_count >= min_count)
            .order_by(FailureClusterRecord.occurrence_count.desc())
            .limit(50)
        )
        rows = (await self.db.execute(q)).scalars().all()
        return [
            StructuralFailureCluster(
                id=str(r.id),
                failure_type=FailureType(r.failure_type),
                primary_source=FailureSource(r.primary_source),
                prompt_fingerprint=r.prompt_fingerprint,
                occurrence_count=r.occurrence_count,
                last_seen=r.last_seen,
                sample_prompt=r.sample_prompt,
            )
            for r in rows
        ]

    async def _compute_failure_rate(self, start: datetime, end: datetime) -> float:
        q = select(
            func.count(EvaluationRecord.id).label("total"),
            func.sum(case((EvaluationRecord.failure_detected.is_(True), 1), else_=0)).label("failures"),
        ).where(EvaluationRecord.created_at.between(start, end))
        row = (await self.db.execute(q)).one()
        return (row.failures / row.total) if row.total else 0.0

    async def _compute_mean_latency(self, start: datetime, end: datetime) -> float:
        q = select(func.avg(TraceRecord.latency_ms).label("mean")).where(
            TraceRecord.created_at.between(start, end)
        )
        row = (await self.db.execute(q)).one()
        return float(row.mean or 0.0)

    async def _compute_healing_rate(self, start: datetime, end: datetime) -> float:
        q = select(
            func.count(HealingRecord.id).label("total"),
            func.sum(case((HealingRecord.regression_passed.is_(True), 1), else_=0)).label("successes"),
        ).where(HealingRecord.created_at.between(start, end))
        row = (await self.db.execute(q)).one()
        return (row.successes / row.total) if row.total else 0.0
