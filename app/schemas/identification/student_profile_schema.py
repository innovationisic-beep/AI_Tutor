from datetime import datetime
from typing import Literal

from beanie.odm.fields import PydanticObjectId
from pydantic import Field, StrictFloat, StrictStr

from app.schemas.identification.base import BaseSchema


class StudentProfileCreate(BaseSchema):
    """Request schema for creating student profiles."""

    organization_id: PydanticObjectId
    user_id: PydanticObjectId
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


class StudentProfileUpdate(BaseSchema):
    """Request schema for updating student profiles."""

    grade: StrictStr | None = Field(default=None, min_length=1, max_length=32)
    board: StrictStr | None = Field(default=None, min_length=1, max_length=64)
    interests: list[StrictStr] | None = Field(default=None, max_items=50)
    preferred_teaching_style: Literal["visual", "practical", "theory", "mixed"] | None = None
    preferred_depth: Literal["basic", "standard", "advanced"] | None = None
    preferred_voice_speed: StrictFloat | None = Field(default=None, ge=0.5, le=2.0)
    learning_speed_score: StrictFloat | None = Field(default=None, ge=0.1, le=3.0)
    baseline_assessment_score: StrictFloat | None = Field(default=None, ge=0.0, le=100.0)
    preferred_language: StrictStr | None = Field(default=None, min_length=2, max_length=10)


class StudentProfileRead(BaseSchema):
    """Response schema for student profiles."""

    id: PydanticObjectId
    organization_id: PydanticObjectId
    user_id: PydanticObjectId
    grade: StrictStr
    board: StrictStr
    interests: list[StrictStr]
    preferred_teaching_style: Literal["visual", "practical", "theory", "mixed"]
    preferred_depth: Literal["basic", "standard", "advanced"]
    preferred_voice_speed: StrictFloat
    learning_speed_score: StrictFloat
    baseline_assessment_score: StrictFloat | None
    preferred_language: StrictStr
    created_at: datetime
    updated_at: datetime
