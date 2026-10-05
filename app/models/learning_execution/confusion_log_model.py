from datetime import datetime

from beanie import Document, Indexed
from beanie.odm.fields import PydanticObjectId
from pydantic import Field, StrictStr
from pymongo import IndexModel

from app.enums.learning_enums import ConfusionTriggerType
from app.utils.timestamps import utc_now


class ConfusionLog(Document):
    """Behavioral signal log for moments of likely learner confusion."""

    organization_id: Indexed(PydanticObjectId) = Field(...)
    student_id: Indexed(PydanticObjectId) = Field(...)
    session_id: Indexed(PydanticObjectId) = Field(...)
    topic_id: Indexed(PydanticObjectId) = Field(...)
    trigger_type: ConfusionTriggerType = Field(...)
    trigger_reason: StrictStr = Field(..., min_length=3, max_length=500)
    timestamp: datetime = Field(default_factory=utc_now)

    class Settings:
        name = "confusion_logs"
        indexes = [
            IndexModel([("organization_id", 1), ("session_id", 1)]),
        ]
