from datetime import datetime
from typing import Any

from beanie import Document, Indexed
from beanie.odm.fields import PydanticObjectId
from pydantic import Field, StrictBool, StrictInt, StrictStr
from pymongo import IndexModel

from app.enums.learning_enums import EventType
from app.utils.timestamps import utc_now


class SessionEvent(Document):
    """Detailed event log emitted during a session timeline."""

    organization_id: Indexed(PydanticObjectId) = Field(...)
    session_id: Indexed(PydanticObjectId) = Field(...)
    student_id: Indexed(PydanticObjectId) = Field(...)
    event_type: EventType = Field(...)
    content: StrictStr | None = Field(default=None, max_length=4000)
    response_time_ms: StrictInt | None = Field(default=None, ge=0, le=300000)
    is_correct: StrictBool | None = Field(default=None)
    metadata: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=utc_now)

    class Settings:
        name = "session_events"
        indexes = [
            IndexModel([("organization_id", 1), ("session_id", 1)]),
        ]
