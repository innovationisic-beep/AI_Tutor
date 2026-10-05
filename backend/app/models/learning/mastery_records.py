from datetime import datetime
from typing import Optional

from beanie.odm.fields import PydanticObjectId
from pydantic import Field
from pymongo import IndexModel

from app.models.base import BaseDocument


def normalize_concept(concept: str | None) -> str | None:
    if concept is None:
        return None
    s = str(concept).strip()
    return s if s else None


def mastery_record_filter(
    organization_id: PydanticObjectId,
    student_id: PydanticObjectId,
    topic_id: PydanticObjectId,
    concept: str | None = None,
) -> dict:
    """Topic-level when concept is None; otherwise scoped to that concept."""
    base: dict = {
        "organization_id": organization_id,
        "student_id": student_id,
        "topic_id": topic_id,
    }
    c = normalize_concept(concept)
    if c is None:
        base["$or"] = [{"concept": None}, {"concept": {"$exists": False}}]
    else:
        base["concept"] = c
    return base


def is_due_for_review(
    last_reviewed_at: Optional[datetime],
    review_interval_days: float,
    now: datetime,
) -> bool:
    """
    Return True if the concept should be revisited based on spaced-retrieval
    scheduling.

    A concept is due when:
      * it has never been reviewed (``last_reviewed_at`` is None), OR
      * the elapsed time since the last review equals or exceeds
        ``review_interval_days``.

    Args:
        last_reviewed_at:     Timestamp of the last review, or None if unseen.
        review_interval_days: Scheduled interval in fractional days (SM-2 I(n)).
        now:                  Current UTC timestamp for comparison.

    Returns:
        True if the concept is due (or overdue) for review; False otherwise.
    """
    if last_reviewed_at is None:
        return True
    elapsed_days = (now - last_reviewed_at).total_seconds() / 86_400.0
    return elapsed_days >= review_interval_days


class MasteryRecord(BaseDocument):
    """Aggregated mastery snapshot per student per topic (optionally per concept)."""

    organization_id: PydanticObjectId = Field(...)
    student_id: PydanticObjectId = Field(...)
    topic_id: PydanticObjectId = Field(...)
    concept: str | None = Field(default=None)
    mastery_score: float = Field(..., ge=0.0, le=100.0)
    confidence_score: float = Field(..., ge=0.0, le=100.0)
    teachback_average: float = Field(..., ge=0.0, le=100.0)
    engagement_score: float = Field(..., ge=0.0, le=100.0)
    revision_needed: bool = Field(default=False)
    attempt_count: int = Field(default=0, ge=0)
    last_session_id: Optional[PydanticObjectId] = Field(default=None)
    last_updated: datetime = Field(...)
    # ── Spaced-retrieval fields (Phase 2) ─────────────────────────────────────
    # All three default to None / conservative values so that existing records
    # in MongoDB that predate this migration continue to deserialize correctly
    # without any schema migration.
    last_reviewed_at: Optional[datetime] = Field(
        default=None,
        description="UTC timestamp of the most recent review event (explain / quiz / teachback).",
    )
    review_interval_days: float = Field(
        default=1.0,
        ge=0.0,
        description="SM-2 scheduled interval until the next review, in fractional days.",
    )
    ease_factor: float = Field(
        default=2.5,
        ge=1.3,
        description="SM-2 ease factor controlling how quickly the review interval grows.",
    )

    class Settings:
        name = "mastery_records"
        indexes = [
            IndexModel(
                [
                    ("organization_id", 1),
                    ("student_id", 1),
                    ("topic_id", 1),
                    ("concept", 1),
                ],
                unique=True,
            ),
        ]
