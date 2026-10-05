from datetime import datetime
from typing import Literal

from beanie import Document, Indexed
from beanie.odm.fields import PydanticObjectId
from pydantic import Field, StrictFloat, StrictStr
from pymongo import IndexModel

from app.utils.timestamps import utc_now


class StudentProfile(Document):
    """Learner profile storing preferences and personalized learning signals."""

    organization_id: Indexed(PydanticObjectId) = Field(...)
    user_id: Indexed(PydanticObjectId) = Field(...)
    grade: StrictStr = Field(..., min_length=1, max_length=32)
    board: StrictStr = Field(..., min_length=1, max_length=64)
    interests: list[StrictStr] = Field(default_factory=list, max_items=50)
    preferred_teaching_style: Literal["visual", "practical", "theory", "mixed"] = Field(
        default="mixed"
    )
    preferred_depth: Literal["basic", "standard", "advanced"] = Field(default="standard")
    preferred_voice_speed: StrictFloat = Field(default=1.0, ge=0.5, le=2.0)
    learning_speed_score: StrictFloat = Field(default=1.0, ge=0.1, le=3.0)
    baseline_assessment_score: StrictFloat | None = Field(default=None, ge=0.0, le=100.0)
    preferred_language: StrictStr = Field(default="en", min_length=2, max_length=10)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    class Settings:
        name = "student_profiles"
        indexes = [
            IndexModel([("organization_id", 1), ("user_id", 1)], unique=True),
        ]
