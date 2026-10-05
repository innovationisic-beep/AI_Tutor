from datetime import datetime

from beanie import Document, Indexed
from beanie.odm.fields import PydanticObjectId
from pydantic import Field, StrictFloat, StrictStr
from pymongo import IndexModel

from app.utils.timestamps import utc_now


class TeachbackEvaluation(Document):
    """Evaluation output for a student's teachback response."""

    organization_id: Indexed(PydanticObjectId) = Field(...)
    student_id: Indexed(PydanticObjectId) = Field(...)
    session_id: Indexed(PydanticObjectId) = Field(...)
    topic_id: Indexed(PydanticObjectId) = Field(...)
    student_response: StrictStr = Field(..., min_length=1, max_length=6000)
    evaluation_score: StrictFloat = Field(..., ge=0.0, le=100.0)
    feedback: StrictStr = Field(..., min_length=1, max_length=3000)
    model_used: StrictStr = Field(..., min_length=2, max_length=80)
    timestamp: datetime = Field(default_factory=utc_now)

    class Settings:
        name = "teachback_evaluations"
        indexes = [
            IndexModel([("organization_id", 1), ("student_id", 1)]),
        ]
