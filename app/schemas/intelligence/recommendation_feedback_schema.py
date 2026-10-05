from datetime import datetime

from beanie.odm.fields import PydanticObjectId
from pydantic import Field, StrictStr

from app.enums.intelligence_enums import FeedbackType
from app.schemas.identification.base import BaseSchema


class RecommendationFeedbackCreate(BaseSchema):
    """Request schema for creating recommendation feedback."""

    organization_id: PydanticObjectId
    student_id: PydanticObjectId
    recommendation_id: PydanticObjectId
    feedback_type: FeedbackType
    feedback_reason: StrictStr | None = Field(default=None, min_length=3, max_length=500)


class RecommendationFeedbackRead(BaseSchema):
    """Response schema for recommendation feedback."""

    id: PydanticObjectId
    organization_id: PydanticObjectId
    student_id: PydanticObjectId
    recommendation_id: PydanticObjectId
    feedback_type: FeedbackType
    feedback_reason: StrictStr | None
    created_at: datetime


class RecommendationFeedbackUpdate(BaseSchema):
    """Request schema for updating recommendation feedback."""

    feedback_type: FeedbackType | None = None
    feedback_reason: StrictStr | None = Field(default=None, min_length=3, max_length=500)
