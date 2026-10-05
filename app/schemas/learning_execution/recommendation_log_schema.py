from datetime import datetime

from beanie.odm.fields import PydanticObjectId
from pydantic import Field, StrictBool, StrictFloat, StrictStr

from app.schemas.identification.base import BaseSchema


class RecommendationLogCreate(BaseSchema):
    """Request schema for recording recommendation decisions."""

    organization_id: PydanticObjectId
    student_id: PydanticObjectId
    recommended_topic_id: PydanticObjectId
    recommendation_reason: StrictStr = Field(..., min_length=3, max_length=1000)
    recommendation_score: StrictFloat = Field(..., ge=0.0, le=100.0)
    accepted: StrictBool = Field(default=False)
    timestamp: datetime | None = None


class RecommendationLogRead(BaseSchema):
    """Response schema for recommendation log resources."""

    id: PydanticObjectId
    organization_id: PydanticObjectId
    student_id: PydanticObjectId
    recommended_topic_id: PydanticObjectId
    recommendation_reason: StrictStr
    recommendation_score: StrictFloat
    accepted: StrictBool
    timestamp: datetime
