from datetime import datetime

from beanie import Document, Indexed
from beanie.odm.fields import PydanticObjectId
from pydantic import Field, StrictFloat, StrictInt, StrictStr
from pymongo import IndexModel

from app.enums.learning_enums import SessionMode, SessionStatus
from app.utils.timestamps import utc_now


class Session(Document):
    """Represents one learning execution session for a student and topic.

    subject_id is stored denormalized (reference: subjects._id) for query
    performance and analytics, so sessions can be queried by subject without
    joining the topics collection.
    """

    organization_id: Indexed(PydanticObjectId) = Field(...)
    student_id: Indexed(PydanticObjectId) = Field(...)
    topic_id: Indexed(PydanticObjectId) = Field(...)
    subject_id: Indexed(PydanticObjectId) = Field(...)
    mode: SessionMode = Field(...)
    ai_model_used: StrictStr = Field(..., min_length=2, max_length=80)
    start_time: datetime = Field(default_factory=utc_now)
    end_time: datetime | None = Field(default=None)
    duration_seconds: StrictInt = Field(default=0, ge=0)
    confusion_count: StrictInt = Field(default=0, ge=0)
    teachback_score: StrictFloat | None = Field(default=None, ge=0.0, le=100.0)
    completion_status: SessionStatus = Field(default=SessionStatus.in_progress)
    created_at: datetime = Field(default_factory=utc_now)

    class Settings:
        name = "sessions"
        indexes = [
            IndexModel([("organization_id", 1), ("student_id", 1)]),
            IndexModel([("organization_id", 1), ("topic_id", 1)]),
            IndexModel([("organization_id", 1), ("subject_id", 1)]),
        ]
