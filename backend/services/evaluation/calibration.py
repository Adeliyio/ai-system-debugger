"""Evaluator calibration: recompute precision/recall/F1/agreement metrics from
the human review queue and persist into `evaluator_metrics`.

Design:
- Each `human_review_queue` row with a non-null `label` is a ground-truth datum.
- For each evaluator (llm_judge, embedding_similarity, rule_based) we compare its
  per-trace verdict (passed vs not) against `label != none`.
- The ensemble's "agreement_rate" is computed against the same labels.
- If we have fewer than `MIN_LABELED` ground-truth labels, this returns a
  cold-start placeholder so the dashboard renders meaningfully.
"""

import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.schemas import EvaluatorType
from backend.storage.models import (
    EvaluationRecord,
    EvaluatorMetricsRecord,
    HumanReviewRecord,
)

logger = structlog.get_logger(__name__)

MIN_LABELED = 5  # cold-start threshold


async def recompute_evaluator_health(db: AsyncSession) -> list[EvaluatorMetricsRecord]:
    """Recompute and persist the latest evaluator metrics from human review labels.

    Returns the newly written EvaluatorMetricsRecord rows.
    """
    # Pull labeled reviews with their evaluations
    review_rows = (
        await db.execute(
            select(HumanReviewRecord, EvaluationRecord)
            .join(EvaluationRecord, EvaluationRecord.id == HumanReviewRecord.evaluation_id)
            .where(HumanReviewRecord.label.is_not(None))
        )
    ).all()

    if len(review_rows) < MIN_LABELED:
        # Cold-start placeholder: zeroed metrics for each evaluator
        records = []
        for ev_type in EvaluatorType:
            rec = EvaluatorMetricsRecord(
                id=uuid.uuid4(),
                evaluator_type=ev_type.value,
                accuracy=0.0,
                precision=0.0,
                recall=0.0,
                f1_score=0.0,
                agreement_rate=0.0,
                total_evaluations=len(review_rows),
                calibrated_at=datetime.now(timezone.utc),
            )
            db.add(rec)
            records.append(rec)
        await db.flush()
        logger.info("evaluator_calibration_cold_start", labeled=len(review_rows))
        return records

    # Build per-evaluator confusion counts
    per_eval: dict[str, dict[str, int]] = {
        et.value: {"tp": 0, "fp": 0, "tn": 0, "fn": 0, "total": 0}
        for et in EvaluatorType
    }
    ensemble_agreement = 0
    total = 0

    for review, evaluation in review_rows:
        truth_failure = (review.label or "none") != "none"
        verdicts = evaluation.verdicts or []
        ensemble_failure_predicted = not evaluation.passed
        if ensemble_failure_predicted == truth_failure:
            ensemble_agreement += 1
        total += 1

        for v in verdicts:
            et = v.get("evaluator_type")
            predicted_failure = not bool(v.get("passed"))
            if et not in per_eval:
                continue
            counts = per_eval[et]
            counts["total"] += 1
            if predicted_failure and truth_failure:
                counts["tp"] += 1
            elif predicted_failure and not truth_failure:
                counts["fp"] += 1
            elif not predicted_failure and not truth_failure:
                counts["tn"] += 1
            else:
                counts["fn"] += 1

    records = []
    for et, counts in per_eval.items():
        tp, fp, tn, fn = counts["tp"], counts["fp"], counts["tn"], counts["fn"]
        n = counts["total"] or 1
        accuracy = (tp + tn) / n
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
        rec = EvaluatorMetricsRecord(
            id=uuid.uuid4(),
            evaluator_type=et,
            accuracy=round(accuracy, 4),
            precision=round(precision, 4),
            recall=round(recall, 4),
            f1_score=round(f1, 4),
            agreement_rate=round(ensemble_agreement / total, 4) if total else 0.0,
            total_evaluations=counts["total"],
            calibrated_at=datetime.now(timezone.utc),
        )
        db.add(rec)
        records.append(rec)

    await db.flush()
    logger.info(
        "evaluator_calibration_completed",
        labeled=total,
        ensemble_agreement=round(ensemble_agreement / total, 4) if total else 0.0,
    )
    return records
