from datetime import datetime
from typing import Any

from beanie.odm.fields import PydanticObjectId
from pydantic import Field, StrictBool, StrictInt, StrictStr

from app.enums.learning_enums import EventType
from app.schemas.identification.base import BaseSchema


class SessionEventCreate(BaseSchema):
    """Request schema for logging an in-session interaction event."""

    organization_id: PydanticObjectId
    session_id: PydanticObjectId
    student_id: PydanticObjectId
    event_type: EventType
    content: StrictStr | None = Field(default=None, max_length=4000)
    response_time_ms: StrictInt | None = Field(default=None, ge=0, le=300000)
    is_correct: StrictBool | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime | None = None


class SessionEventRead(BaseSchema):
    """Response schema for session event resources."""

    id: PydanticObjectId
    organization_id: PydanticObjectId
    session_id: PydanticObjectId
    student_id: PydanticObjectId
    event_type: EventType
    content: StrictStr | None
    response_time_ms: StrictInt | None
    is_correct: StrictBool | None
    metadata: dict[str, Any]
    timestamp: datetime
