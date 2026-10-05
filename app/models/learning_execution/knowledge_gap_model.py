from datetime import datetime

from beanie import Document, Indexed
from beanie.odm.fields import PydanticObjectId
from pydantic import Field, StrictBool, StrictFloat, StrictStr
from pymongo import IndexModel

from app.utils.timestamps import utc_now


class KnowledgeGap(Document):
    """Detected root-cause knowledge deficit for a student-topic context."""

    organization_id: Indexed(PydanticObjectId) = Field(...)
    student_id: Indexed(PydanticObjectId) = Field(...)
    topic_id: Indexed(PydanticObjectId) = Field(...)
    root_cause_topic_id: Indexed(PydanticObjectId) = Field(...)
    severity_score: StrictFloat = Field(..., ge=0.0, le=100.0)
    detected_reason: StrictStr = Field(..., min_length=3, max_length=500)
    resolved: StrictBool = Field(default=False)
    created_at: datetime = Field(default_factory=utc_now)

    class Settings:
        name = "knowledge_gaps"
        indexes = [
            IndexModel([("organization_id", 1), ("student_id", 1)]),
        ]
