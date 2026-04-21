from fastapi import APIRouter, Depends, HTTPException

from backend.models.schemas import TraceCreate, TraceResponse
from backend.services.instrumentation import InstrumentationService
from backend.core.dependencies import get_instrumentation_service

router = APIRouter(prefix="/trace", tags=["Traces"])


@router.post("", response_model=TraceResponse, status_code=201)
async def submit_trace(
    trace_data: TraceCreate,
    service: InstrumentationService = Depends(get_instrumentation_service),
) -> TraceResponse:
    """Submit an AI interaction trace for monitoring and analysis."""
    return await service.capture_trace(trace_data)


@router.get("/{trace_id}", response_model=TraceResponse)
async def get_trace(
    trace_id: str,
    service: InstrumentationService = Depends(get_instrumentation_service),
) -> TraceResponse:
    """Retrieve a trace by ID."""
    try:
        return await service.get_trace(trace_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
