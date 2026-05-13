import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.dependencies import get_db
from backend.models.schemas import (
    FailureType,
    HumanReviewItem,
    HumanReviewLabel,
    RiskTier,
    SeverityLevel,
)
from backend.storage.models import HumanReviewRecord


router = APIRouter(tags=["Review"])


def _coerce_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError) as e:
        raise HTTPException(status_code=400, detail=f"Invalid UUID: {value}") from e


def _to_item(record: HumanReviewRecord) -> HumanReviewItem:
    return HumanReviewItem(
        id=str(record.id),
        trace_id=str(record.trace_id),
        evaluation_id=str(record.evaluation_id) if record.evaluation_id else None,
        reason=record.reason,
        severity=SeverityLevel(record.severity),
        risk_tier=RiskTier(record.risk_tier),
        created_at=record.created_at,
        label=FailureType(record.label) if record.label else None,
        resolved_at=record.resolved_at,
        notes=record.notes,
    )


@router.get("/review/queue", response_model=list[HumanReviewItem])
async def list_review_queue(
    resolved: Optional[bool] = Query(None, description="Filter by resolved/unresolved"),
    reason: Optional[str] = Query(None, description="Filter by reason"),
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> list[HumanReviewItem]:
    """List items in the human review queue.

    `resolved=False` returns only unresolved items (default behaviour for the dashboard).
    """
    q = select(HumanReviewRecord).order_by(HumanReviewRecord.created_at.desc()).limit(limit)
    if resolved is True:
        q = q.where(HumanReviewRecord.resolved_at.is_not(None))
    elif resolved is False:
        q = q.where(HumanReviewRecord.resolved_at.is_(None))
    if reason:
        q = q.where(HumanReviewRecord.reason == reason)

    rows = (await db.execute(q)).scalars().all()
    return [_to_item(r) for r in rows]


@router.post("/review/{review_id}/label", response_model=HumanReviewItem)
async def label_review_item(
    review_id: str,
    payload: HumanReviewLabel,
    db: AsyncSession = Depends(get_db),
) -> HumanReviewItem:
    """Apply a ground-truth label to a queued review item, marking it resolved."""
    record = await db.get(HumanReviewRecord, _coerce_uuid(review_id))
    if record is None:
        raise HTTPException(status_code=404, detail=f"Review item {review_id} not found")

    record.label = payload.label.value
    record.notes = payload.notes
    record.reviewer = payload.reviewer
    record.resolved_at = datetime.now(timezone.utc)
    await db.flush()
    return _to_item(record)
