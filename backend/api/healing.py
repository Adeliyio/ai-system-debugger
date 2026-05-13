import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.dependencies import (
    get_db,
    get_evaluation_service,
    get_healing_service,
    get_rca_service,
)
from backend.models.schemas import (
    ComparisonRequest,
    ComparisonResponse,
    HealingRequest,
    HealingResponse,
    HealingStrategy,
    RCARequest,
    RCAResponse,
)
from backend.services.evaluation import EvaluationService
from backend.services.healing import HealingService
from backend.services.rca import RCAService
from backend.storage.models import HealingRecord, TraceRecord


router = APIRouter(tags=["Healing"])


def _coerce_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError) as e:
        raise HTTPException(status_code=400, detail=f"Invalid UUID: {value}") from e


@router.post("/rca", response_model=RCAResponse)
async def run_root_cause_analysis(
    request: RCARequest,
    service: RCAService = Depends(get_rca_service),
) -> RCAResponse:
    """Perform root cause analysis on a failed trace."""
    try:
        return await service.analyze(request)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/fix", response_model=HealingResponse)
async def apply_fix(
    request: HealingRequest,
    service: HealingService = Depends(get_healing_service),
) -> HealingResponse:
    """Apply a self-healing fix to a failed trace.

    High-risk traces are routed to manual review and not auto-healed.
    """
    try:
        return await service.heal(request)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/compare", response_model=ComparisonResponse)
async def compare_responses(
    request: ComparisonRequest,
    db: AsyncSession = Depends(get_db),
    evaluator: EvaluationService = Depends(get_evaluation_service),
) -> ComparisonResponse:
    """Compare original vs repaired response, scored by the ensemble evaluator."""
    trace = await db.get(TraceRecord, _coerce_uuid(request.trace_id))
    if trace is None:
        raise HTTPException(status_code=404, detail=f"Trace {request.trace_id} not found")

    healing = await db.get(HealingRecord, _coerce_uuid(request.healing_id))
    if healing is None:
        raise HTTPException(
            status_code=404, detail=f"Healing record {request.healing_id} not found"
        )

    # Real ensemble scoring on both
    original_eval = await evaluator.evaluate_response(
        trace.prompt, trace.response, trace.context_documents or [],
    )
    repaired_eval = await evaluator.evaluate_response(
        trace.prompt, healing.repaired_response, trace.context_documents or [],
    )

    return ComparisonResponse(
        trace_id=str(trace.id),
        original_response=trace.response,
        repaired_response=healing.repaired_response,
        original_score=original_eval.overall_score,
        repaired_score=repaired_eval.overall_score,
        improvement=round(repaired_eval.overall_score - original_eval.overall_score, 4),
        strategy_used=HealingStrategy(healing.strategy),
        side_by_side={
            "original_word_count": len(trace.response.split()),
            "repaired_word_count": len(healing.repaired_response.split()),
            "original_failure_type": original_eval.failure_type.value,
            "repaired_failure_type": repaired_eval.failure_type.value,
            "strategy": healing.strategy,
            "attempts": healing.attempt_number,
            "regression_passed": healing.regression_passed,
            "escalated_to_openai": getattr(healing, "escalated_to_openai", False),
        },
    )
