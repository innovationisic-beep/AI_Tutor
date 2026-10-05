from datetime import date
from typing import Literal, Optional

from beanie.odm.fields import PydanticObjectId
from pydantic import Field
from pymongo import IndexModel

from app.models.base import BaseDocument


class StudentGoalProfile(BaseDocument):
    """Long-term goal settings used for personalized adaptation."""

    organization_id: PydanticObjectId = Field(...)
    student_id: PydanticObjectId = Field(...)
    goal_type: Literal[
        "exam_prep",
        "concept_mastery",
        "syllabus_completion",
    ] = Field(...)
    target_exam_date: Optional[date] = Field(default=None)
    target_mastery_score: float = Field(..., ge=0.0, le=1.0)
    preferred_study_minutes_per_day: int = Field(..., ge=5)

    class Settings:
        name = "student_goal_profiles"
        indexes = [
            IndexModel([("organization_id", 1), ("student_id", 1)]),
        ]
