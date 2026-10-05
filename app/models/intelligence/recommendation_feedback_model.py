from datetime import datetime

from beanie import Document, Indexed
from beanie.odm.fields import PydanticObjectId
from pydantic import Field, StrictStr
from pymongo import IndexModel

from app.enums.intelligence_enums import FeedbackType
from app.utils.timestamps import utc_now


class RecommendationFeedback(Document):
    """Student feedback collected for recommendation quality optimization."""

    organization_id: Indexed(PydanticObjectId) = Field(...)
    student_id: Indexed(PydanticObjectId) = Field(...)
    recommendation_id: Indexed(PydanticObjectId) = Field(...)
    feedback_type: FeedbackType = Field(...)
    feedback_reason: StrictStr | None = Field(default=None, min_length=3, max_length=500)
    created_at: datetime = Field(default_factory=utc_now)

    class Settings:
        name = "recommendation_feedback"
        indexes = [
            IndexModel([("organization_id", 1), ("student_id", 1)]),
        ]
