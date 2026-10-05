from datetime import datetime

from beanie.odm.fields import PydanticObjectId
from pydantic import Field
from pymongo import IndexModel

from app.models.base import BaseDocument


class TeachbackEvaluation(BaseDocument):
    """Evaluation output for a student's teachback or quiz response."""

    organization_id: PydanticObjectId = Field(...)
    student_id: PydanticObjectId = Field(...)
    session_id: PydanticObjectId = Field(...)
    topic_id: PydanticObjectId = Field(...)
    question_text: str = Field(..., min_length=1, max_length=5000)
    student_response: str = Field(..., min_length=1, max_length=6000)
    is_correct: bool = Field(...)
    evaluation_score: float = Field(..., ge=0.0, le=100.0)
    feedback: str = Field(..., min_length=1, max_length=3000)
    model_used: str = Field(..., min_length=2, max_length=80)
    timestamp: datetime = Field(...)

    class Settings:
        name = "teachback_evaluations"
        indexes = [
            IndexModel([("organization_id", 1), ("student_id", 1)]),
        ]
