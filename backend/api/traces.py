from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.schemas import TraceCreate, TraceResponse
from backend.services.instrumentation import InstrumentationService
from backend.services.instrumentation.tracer import _record_to_response
from backend.core.dependencies import get_db, get_instrumentation_service
from backend.storage.models import EvaluationRecord, RCARecord, TraceRecord


router = APIRouter(tags=["Traces"])


@router.post("/trace", response_model=TraceResponse, status_code=201)
async def submit_trace(
    trace_data: TraceCreate,
    service: InstrumentationService = Depends(get_instrumentation_service),
) -> TraceResponse:
    """Submit an AI interaction trace for monitoring and analysis."""
    return await service.capture_trace(trace_data)


@router.get("/traces", response_model=list[TraceResponse])
async def list_traces(
    limit: int = Query(50, ge=1, le=200),
    status: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> list[TraceResponse]:
    """List recent traces, optionally filtered by status."""
    q = select(TraceRecord).order_by(desc(TraceRecord.created_at)).limit(limit)
    if status:
        q = q.where(TraceRecord.status == status)
    rows = (await db.execute(q)).scalars().all()
    return [_record_to_response(r) for r in rows]


@router.get("/traces/failed-with-context")
async def list_failed_traces_with_context(
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """List failed traces with their evaluation and RCA IDs for the healing page."""
    q = (
        select(TraceRecord, EvaluationRecord.id.label("eval_id"), RCARecord.id.label("rca_id"))
        .join(EvaluationRecord, EvaluationRecord.trace_id == TraceRecord.id)
        .outerjoin(RCARecord, RCARecord.trace_id == TraceRecord.id)
        .where(TraceRecord.status == "failed")
        .order_by(desc(TraceRecord.created_at))
        .limit(limit)
    )
    rows = (await db.execute(q)).all()
    seen = set()
    results = []
    for trace, eval_id, rca_id in rows:
        if trace.id in seen:
            continue
        seen.add(trace.id)
        results.append({
            "id": str(trace.id),
            "session_id": trace.session_id,
            "prompt": trace.prompt,
            "model_used": trace.model_used,
            "status": trace.status,
            "created_at": trace.created_at.isoformat() if trace.created_at else None,
            "evaluation_id": str(eval_id) if eval_id else None,
            "rca_id": str(rca_id) if rca_id else None,
        })
    return results


@router.get("/trace/{trace_id}", response_model=TraceResponse)
async def get_trace(
    trace_id: str,
    service: InstrumentationService = Depends(get_instrumentation_service),
) -> TraceResponse:
    """Retrieve a trace by ID."""
    try:
        return await service.get_trace(trace_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
