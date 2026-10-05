from datetime import datetime
from typing import Literal

from beanie.odm.fields import PydanticObjectId
from pydantic import Field
from pymongo import IndexModel

from app.models.base import BaseDocument


class ConfusionLog(BaseDocument):
    """Behavioral signal log for moments of likely learner confusion."""

    organization_id: PydanticObjectId = Field(...)
    student_id: PydanticObjectId = Field(...)
    session_id: PydanticObjectId = Field(...)
    topic_id: PydanticObjectId = Field(...)
    trigger_type: Literal[
        "slow_response",
        "wrong_answer",
        "repeated_pause",
        "repeated_rewind",
        "multiple_explanation_requests",
    ] = Field(...)
    trigger_reason: str = Field(..., min_length=3, max_length=500)
    timestamp: datetime = Field(...)

    class Settings:
        name = "confusion_logs"
        indexes = [
            IndexModel([("organization_id", 1), ("session_id", 1)]),
        ]
