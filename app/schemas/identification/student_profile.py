from beanie.odm.fields import PydanticObjectId
from pydantic import Field, StrictFloat, StrictStr

from app.models.enums import LearningDepth, TeachingStyle

from .base import BaseSchema


class StudentProfileCreate(BaseSchema):
    organization_id: PydanticObjectId
    user_id: PydanticObjectId
    grade: StrictStr = Field(..., min_length=1, max_length=32)
    board: StrictStr = Field(..., min_length=1, max_length=64)
    interests: list[StrictStr] = Field(default_factory=list, max_items=50)
    preferred_teaching_style: TeachingStyle = Field(default=TeachingStyle.mixed)
    preferred_depth: LearningDepth = Field(default=LearningDepth.standard)
    preferred_voice_speed: StrictFloat = Field(..., gt=0)
    learning_speed_score: StrictFloat = Field(default=1.0, gt=0)
    baseline_assessment_score: StrictFloat | None = Field(default=None, ge=0, le=100)
    preferred_language: StrictStr = Field(default="en", min_length=2, max_length=10)


class StudentProfileUpdate(BaseSchema):
    grade: StrictStr | None = Field(default=None, min_length=1, max_length=32)
    board: StrictStr | None = Field(default=None, min_length=1, max_length=64)
    interests: list[StrictStr] | None = Field(default=None, max_items=50)
    preferred_teaching_style: TeachingStyle | None = None
    preferred_depth: LearningDepth | None = None
    preferred_voice_speed: StrictFloat | None = Field(default=None, gt=0)
    learning_speed_score: StrictFloat | None = Field(default=None, gt=0)
    baseline_assessment_score: StrictFloat | None = Field(default=None, ge=0, le=100)
    preferred_language: StrictStr | None = Field(default=None, min_length=2, max_length=10)
