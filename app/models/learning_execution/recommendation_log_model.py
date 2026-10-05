from datetime import datetime

from beanie import Document, Indexed
from beanie.odm.fields import PydanticObjectId
from pydantic import Field, StrictBool, StrictFloat, StrictStr
from pymongo import IndexModel

from app.utils.timestamps import utc_now


class RecommendationLog(Document):
    """Audit log for AI recommendation decisions and learner acceptance."""

    organization_id: Indexed(PydanticObjectId) = Field(...)
    student_id: Indexed(PydanticObjectId) = Field(...)
    recommended_topic_id: Indexed(PydanticObjectId) = Field(...)
    recommendation_reason: StrictStr = Field(..., min_length=3, max_length=1000)
    recommendation_score: StrictFloat = Field(..., ge=0.0, le=100.0)
    accepted: StrictBool = Field(default=False)
    timestamp: datetime = Field(default_factory=utc_now)

    class Settings:
        name = "recommendation_logs"
        indexes = [
            IndexModel([("organization_id", 1), ("student_id", 1)]),
        ]
