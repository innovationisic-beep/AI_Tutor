from datetime import datetime
from typing import Any, Optional

from beanie.odm.fields import PydanticObjectId
from pydantic import Field
from pymongo import IndexModel

from app.enums.learning_enums import SessionEventType
from app.models.base import BaseDocument


class SessionEvent(BaseDocument):
    """Detailed event log emitted during a session timeline."""

    organization_id: PydanticObjectId = Field(...)
    session_id: PydanticObjectId = Field(...)
    student_id: PydanticObjectId = Field(...)
    event_type: SessionEventType = Field(...)
    content: Optional[str] = Field(default=None, max_length=4000)
    response_time_ms: Optional[int] = Field(default=None, ge=0, le=300000)
    is_correct: Optional[bool] = Field(default=None)
    metadata: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(...)

    class Settings:
        name = "session_events"
        indexes = [
            IndexModel([("organization_id", 1), ("session_id", 1)]),
        ]
