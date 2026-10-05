from typing import Literal, Optional

from beanie.odm.fields import PydanticObjectId
from pydantic import Field
from pymongo import IndexModel

from app.models.base import BaseDocument


class RecommendationFeedback(BaseDocument):
    """Student feedback collected for recommendation quality optimization."""

    organization_id: PydanticObjectId = Field(...)
    student_id: PydanticObjectId = Field(...)
    recommendation_id: PydanticObjectId = Field(...)
    feedback_type: Literal[
        "accepted",
        "ignored",
        "rejected",
    ] = Field(...)
    feedback_reason: Optional[str] = Field(default=None, min_length=3, max_length=500)

    class Settings:
        name = "recommendation_feedback"
        indexes = [
            IndexModel([("organization_id", 1), ("student_id", 1)]),
        ]
