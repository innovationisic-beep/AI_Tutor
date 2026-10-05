from typing import List, Literal, Optional

from beanie.odm.fields import PydanticObjectId
from pydantic import Field
from pymongo import IndexModel

from app.models.base import BaseDocument


class StudentProfile(BaseDocument):
    """Learner profile storing preferences and personalized learning signals."""

    organization_id: PydanticObjectId = Field(...)
    user_id: PydanticObjectId = Field(...)
    full_name: Optional[str] = Field(default=None, max_length=120)
    """Display name from signup; optional for legacy profiles."""
    class_id: Optional[str] = Field(default=None, max_length=64)
    """Org class id when the student joined via school invite."""
    grade: str = Field(..., min_length=1, max_length=32)
    board: str = Field(..., min_length=1, max_length=64)
    interests: List[str] = Field(default_factory=list, max_length=50)
    preferred_teaching_style: Literal["visual", "practical", "theory", "mixed"] = Field(
        default="mixed"
    )
    preferred_depth: Literal["basic", "standard", "advanced"] = Field(default="standard")
    preferred_voice_speed: float = Field(default=1.0, ge=0.5, le=2.0)
    learning_speed_score: float = Field(default=1.0, ge=0.1, le=3.0)
    baseline_assessment_score: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    preferred_language: str = Field(default="en", min_length=2, max_length=16)
    """Tutor language preference. ``en`` (default) or ``hinglish``."""

    class Settings:
        name = "student_profiles"
        indexes = [
            IndexModel([("organization_id", 1), ("user_id", 1)], unique=True),
        ]
