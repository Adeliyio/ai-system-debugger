from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.schemas import (
    HealingRequest,
    HealingResponse,
    RCARequest,
    RCAResponse,
    ComparisonRequest,
    ComparisonResponse,
)
from backend.services.rca import RCAService
from backend.services.healing import HealingService
from backend.storage.database import get_db
from backend.storage.models import TraceRecord, HealingRecord
from backend.core.dependencies import get_rca_service, get_healing_service

router = APIRouter(tags=["Healing"])


@router.post("/rca", response_model=RCAResponse)
async def run_root_cause_analysis(
    request: RCARequest,
    service: RCAService = Depends(get_rca_service),
) -> RCAResponse:
    """Perform root cause analysis on a failed trace.

    Combines heuristic signal detection with LLM-powered deep analysis
    to classify the failure source.
    """
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

    Runs the LangGraph healing pipeline: strategy selection -> repair ->
    regression testing -> accept/retry.
    """
    try:
        return await service.heal(request)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/compare", response_model=ComparisonResponse)
async def compare_responses(
    request: ComparisonRequest,
    db: AsyncSession = Depends(get_db),
) -> ComparisonResponse:
    """Compare original vs repaired response side by side."""
    trace = await db.get(TraceRecord, request.trace_id)
    if trace is None:
        raise HTTPException(status_code=404, detail=f"Trace {request.trace_id} not found")

    healing = await db.get(HealingRecord, request.healing_id)
    if healing is None:
        raise HTTPException(status_code=404, detail=f"Healing record {request.healing_id} not found")

    # Build comparison metrics
    original_len = len(trace.response.split())
    repaired_len = len(healing.repaired_response.split())

    return ComparisonResponse(
        trace_id=str(trace.id),
        original_response=trace.response,
        repaired_response=healing.repaired_response,
        original_score=1.0 - healing.improvement_score,  # Approximate original score
        repaired_score=1.0,  # Normalized to repaired
        improvement=healing.improvement_score,
        strategy_used=healing.strategy,
        side_by_side={
            "original_word_count": original_len,
            "repaired_word_count": repaired_len,
            "strategy": healing.strategy,
            "attempts": healing.attempt_number,
            "regression_passed": healing.regression_passed,
        },
    )
