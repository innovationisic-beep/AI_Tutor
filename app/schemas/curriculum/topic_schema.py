import re
from datetime import datetime

from beanie.odm.fields import PydanticObjectId
from pydantic import Field, StrictBool, StrictInt, StrictStr, validator

from app.enums.curriculum_enums import CurriculumStatus
from app.schemas.base import BaseSchema

SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class TopicCreate(BaseSchema):
    """Request schema for creating a curriculum topic."""

    organization_id: PydanticObjectId
    subject_id: PydanticObjectId
    topic_name: StrictStr = Field(..., min_length=2, max_length=140)
    topic_slug: StrictStr = Field(..., min_length=2, max_length=160)
    topic_description: StrictStr = Field(..., min_length=10, max_length=3000)
    learning_objectives: list[StrictStr] = Field(default_factory=list, max_items=100)
    learning_outcomes: list[StrictStr] = Field(default_factory=list, max_items=100)
    key_concepts: list[StrictStr] = Field(default_factory=list, max_items=100)
    common_mistakes: list[StrictStr] = Field(default_factory=list, max_items=100)
    difficulty_level: StrictStr = Field(..., min_length=1, max_length=20)
    topic_order: StrictInt = Field(..., ge=0)
    estimated_time: StrictInt = Field(..., ge=1, le=1440)
    default_depth: StrictStr = Field(..., min_length=1, max_length=20)
    academic_year: StrictStr = Field(..., min_length=4, max_length=20)
    curriculum_version: StrictStr = Field(..., min_length=1, max_length=20)
    status: CurriculumStatus = Field(default=CurriculumStatus.draft)
    is_active: StrictBool = Field(default=True)

    @validator("topic_slug")
    def validate_slug(cls, value: StrictStr) -> StrictStr:
        slug = str(value).strip().lower()
        if not SLUG_PATTERN.match(slug):
            raise ValueError("topic_slug must be URL-safe (lowercase letters, numbers, hyphens)")
        return slug


class TopicUpdate(BaseSchema):
    """Request schema for updating a curriculum topic."""

    topic_name: StrictStr | None = Field(default=None, min_length=2, max_length=140)
    topic_slug: StrictStr | None = Field(default=None, min_length=2, max_length=160)
    topic_description: StrictStr | None = Field(default=None, min_length=10, max_length=3000)
    learning_objectives: list[StrictStr] | None = Field(default=None, max_items=100)
    learning_outcomes: list[StrictStr] | None = Field(default=None, max_items=100)
    key_concepts: list[StrictStr] | None = Field(default=None, max_items=100)
    common_mistakes: list[StrictStr] | None = Field(default=None, max_items=100)
    difficulty_level: StrictStr | None = Field(default=None, min_length=1, max_length=20)
    topic_order: StrictInt | None = Field(default=None, ge=0)
    estimated_time: StrictInt | None = Field(default=None, ge=1, le=1440)
    default_depth: StrictStr | None = Field(default=None, min_length=1, max_length=20)
    academic_year: StrictStr | None = Field(default=None, min_length=4, max_length=20)
    curriculum_version: StrictStr | None = Field(default=None, min_length=1, max_length=20)
    status: CurriculumStatus | None = None
    is_active: StrictBool | None = None

    @validator("topic_slug")
    def validate_optional_slug(cls, value: StrictStr | None) -> StrictStr | None:
        if value is None:
            return None
        slug = str(value).strip().lower()
        if not SLUG_PATTERN.match(slug):
            raise ValueError("topic_slug must be URL-safe (lowercase letters, numbers, hyphens)")
        return slug


class TopicRead(BaseSchema):
    """Response schema for curriculum topic resources."""

    id: PydanticObjectId
    organization_id: PydanticObjectId
    subject_id: PydanticObjectId
    topic_name: StrictStr
    topic_slug: StrictStr
    topic_description: StrictStr
    learning_objectives: list[StrictStr]
    learning_outcomes: list[StrictStr]
    key_concepts: list[StrictStr]
    common_mistakes: list[StrictStr]
    difficulty_level: StrictStr
    topic_order: StrictInt
    estimated_time: StrictInt
    default_depth: StrictStr
    academic_year: StrictStr
    curriculum_version: StrictStr
    status: CurriculumStatus
    is_active: StrictBool
    created_at: datetime
    updated_at: datetime
