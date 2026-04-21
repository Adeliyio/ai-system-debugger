from fastapi import APIRouter, Depends, HTTPException

from backend.models.schemas import EvaluationRequest, EvaluationResponse
from backend.services.evaluation import EvaluationService
from backend.core.dependencies import get_evaluation_service

router = APIRouter(prefix="/analyze", tags=["Analysis"])


@router.post("", response_model=EvaluationResponse)
async def analyze_trace(
    request: EvaluationRequest,
    service: EvaluationService = Depends(get_evaluation_service),
) -> EvaluationResponse:
    """Analyze a trace for failures using the ensemble evaluation engine.

    Runs three independent evaluators (LLM judge, embedding similarity,
    rule-based) and determines the outcome by majority agreement.
    """
    try:
        return await service.evaluate_trace(request)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
