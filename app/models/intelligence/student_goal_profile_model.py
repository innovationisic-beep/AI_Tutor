from datetime import date, datetime

from beanie import Document, Indexed
from beanie.odm.fields import PydanticObjectId
from pydantic import Field, StrictFloat, StrictInt
from pymongo import IndexModel

from app.enums.intelligence_enums import GoalType
from app.utils.timestamps import utc_now


class StudentGoalProfile(Document):
    """Long-term goal settings used for personalized adaptation."""

    organization_id: Indexed(PydanticObjectId) = Field(...)
    student_id: Indexed(PydanticObjectId) = Field(...)
    goal_type: GoalType = Field(...)
    target_exam_date: date | None = Field(default=None)
    target_mastery_score: StrictFloat = Field(..., ge=0.0, le=1.0)
    preferred_study_minutes_per_day: StrictInt = Field(..., ge=5)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    class Settings:
        name = "student_goal_profiles"
        indexes = [
            IndexModel([("organization_id", 1), ("student_id", 1)]),
        ]
