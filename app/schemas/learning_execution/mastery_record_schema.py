from datetime import datetime

from beanie.odm.fields import PydanticObjectId
from pydantic import Field, StrictBool, StrictFloat, StrictInt

from app.schemas.identification.base import BaseSchema


class MasteryRecordCreate(BaseSchema):
    """Request schema for creating student-topic mastery state."""

    organization_id: PydanticObjectId
    student_id: PydanticObjectId
    topic_id: PydanticObjectId
    mastery_score: StrictFloat = Field(..., ge=0.0, le=100.0)
    confidence_score: StrictFloat = Field(..., ge=0.0, le=100.0)
    teachback_average: StrictFloat = Field(..., ge=0.0, le=100.0)
    engagement_score: StrictFloat = Field(..., ge=0.0, le=100.0)
    revision_needed: StrictBool = Field(default=False)
    attempt_count: StrictInt = Field(default=0, ge=0)
    last_session_id: PydanticObjectId | None = None


class MasteryRecordUpdate(BaseSchema):
    """Request schema for updating student-topic mastery state."""

    mastery_score: StrictFloat | None = Field(default=None, ge=0.0, le=100.0)
    confidence_score: StrictFloat | None = Field(default=None, ge=0.0, le=100.0)
    teachback_average: StrictFloat | None = Field(default=None, ge=0.0, le=100.0)
    engagement_score: StrictFloat | None = Field(default=None, ge=0.0, le=100.0)
    revision_needed: StrictBool | None = None
    attempt_count: StrictInt | None = Field(default=None, ge=0)
    last_session_id: PydanticObjectId | None = None
    last_updated: datetime | None = None


class MasteryRecordRead(BaseSchema):
    """Response schema for mastery record resources."""

    id: PydanticObjectId
    organization_id: PydanticObjectId
    student_id: PydanticObjectId
    topic_id: PydanticObjectId
    mastery_score: StrictFloat
    confidence_score: StrictFloat
    teachback_average: StrictFloat
    engagement_score: StrictFloat
    revision_needed: StrictBool
    attempt_count: StrictInt
    last_session_id: PydanticObjectId | None
    last_updated: datetime
