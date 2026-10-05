from datetime import date, datetime

from beanie.odm.fields import PydanticObjectId
from pydantic import Field, StrictFloat, StrictInt

from app.enums.intelligence_enums import GoalType
from app.schemas.identification.base import BaseSchema


class StudentGoalProfileCreate(BaseSchema):
    """Request schema for creating a student goal profile."""

    organization_id: PydanticObjectId
    student_id: PydanticObjectId
    goal_type: GoalType
    target_exam_date: date | None = None
    target_mastery_score: StrictFloat = Field(..., ge=0.0, le=1.0)
    preferred_study_minutes_per_day: StrictInt = Field(..., ge=5)


class StudentGoalProfileRead(BaseSchema):
    """Response schema for student goal profiles."""

    id: PydanticObjectId
    organization_id: PydanticObjectId
    student_id: PydanticObjectId
    goal_type: GoalType
    target_exam_date: date | None
    target_mastery_score: StrictFloat
    preferred_study_minutes_per_day: StrictInt
    created_at: datetime
    updated_at: datetime


class StudentGoalProfileUpdate(BaseSchema):
    """Request schema for updating a student goal profile."""

    goal_type: GoalType | None = None
    target_exam_date: date | None = None
    target_mastery_score: StrictFloat | None = Field(default=None, ge=0.0, le=1.0)
    preferred_study_minutes_per_day: StrictInt | None = Field(default=None, ge=5)
