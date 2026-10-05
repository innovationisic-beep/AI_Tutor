from datetime import datetime

from beanie.odm.fields import PydanticObjectId
from pydantic import Field, StrictFloat, StrictInt, StrictStr

from app.enums.learning_enums import SessionMode, SessionStatus
from app.schemas.identification.base import BaseSchema


class SessionCreate(BaseSchema):
    """Request schema for creating a learning session."""

    organization_id: PydanticObjectId
    student_id: PydanticObjectId
    topic_id: PydanticObjectId
    mode: SessionMode
    ai_model_used: StrictStr = Field(..., min_length=2, max_length=80)
    start_time: datetime | None = None
    completion_status: SessionStatus = Field(default=SessionStatus.in_progress)


class SessionUpdate(BaseSchema):
    """Request schema for updating session state and scores."""

    end_time: datetime | None = None
    duration_seconds: StrictInt | None = Field(default=None, ge=0)
    confusion_count: StrictInt | None = Field(default=None, ge=0)
    teachback_score: StrictFloat | None = Field(default=None, ge=0.0, le=100.0)
    completion_status: SessionStatus | None = None


class SessionRead(BaseSchema):
    """Response schema for session resources."""

    id: PydanticObjectId
    organization_id: PydanticObjectId
    student_id: PydanticObjectId
    topic_id: PydanticObjectId
    mode: SessionMode
    ai_model_used: StrictStr
    start_time: datetime
    end_time: datetime | None
    duration_seconds: StrictInt
    confusion_count: StrictInt
    teachback_score: StrictFloat | None
    completion_status: SessionStatus
    created_at: datetime
