from beanie.odm.fields import PydanticObjectId
from pydantic import Field
from pymongo import IndexModel

from app.models.base import BaseDocument


class KnowledgeGap(BaseDocument):
    """Detected root-cause knowledge deficit for a student-topic context."""

    organization_id: PydanticObjectId = Field(...)
    student_id: PydanticObjectId = Field(...)
    topic_id: PydanticObjectId = Field(...)
    root_cause_topic_id: PydanticObjectId = Field(...)
    severity_score: float = Field(..., ge=0.0, le=100.0)
    detected_reason: str = Field(..., min_length=3, max_length=500)
    resolved: bool = Field(default=False)

    class Settings:
        name = "knowledge_gaps"
        indexes = [
            IndexModel([("organization_id", 1), ("student_id", 1)]),
        ]
