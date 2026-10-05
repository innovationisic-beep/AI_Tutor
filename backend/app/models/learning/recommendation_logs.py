from datetime import datetime

from beanie.odm.fields import PydanticObjectId
from pydantic import Field
from pymongo import IndexModel

from app.models.base import BaseDocument


class RecommendationLog(BaseDocument):
    """Audit log for AI recommendation decisions and learner acceptance."""

    organization_id: PydanticObjectId = Field(...)
    student_id: PydanticObjectId = Field(...)
    recommended_topic_id: PydanticObjectId = Field(...)
    recommendation_reason: str = Field(..., min_length=3, max_length=1000)
    recommendation_score: float = Field(..., ge=0.0, le=100.0)
    accepted: bool = Field(default=False)
    timestamp: datetime = Field(...)

    class Settings:
        name = "recommendation_logs"
        indexes = [
            IndexModel([("organization_id", 1), ("student_id", 1)]),
        ]
