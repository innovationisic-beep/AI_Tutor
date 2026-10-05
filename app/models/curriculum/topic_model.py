import re
from datetime import datetime

from beanie import Indexed
from beanie.odm.fields import PydanticObjectId
from pydantic import Field, StrictBool, StrictInt, StrictStr, validator
from pymongo import IndexModel

from app.enums.curriculum_enums import CurriculumStatus
from app.models.base import BaseDocument
from app.utils.timestamps import utc_now

SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class Topic(BaseDocument):
    """Tenant-scoped topic entity with pedagogical metadata."""

    organization_id: Indexed(PydanticObjectId) = Field(...)
    subject_id: Indexed(PydanticObjectId) = Field(...)

    topic_name: Indexed(StrictStr) = Field(..., min_length=2, max_length=140)
    topic_slug: Indexed(StrictStr) = Field(..., min_length=2, max_length=160)

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

    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @validator("topic_slug")
    def validate_slug(cls, value: StrictStr) -> StrictStr:
        slug = str(value).strip().lower()
        if not SLUG_PATTERN.match(slug):
            raise ValueError("topic_slug must be URL-safe (lowercase letters, numbers, hyphens)")
        return slug

    class Settings:
        name = "topics"
        indexes = [
            IndexModel([("organization_id", 1), ("subject_id", 1)]),
            IndexModel([("organization_id", 1), ("topic_slug", 1)]),
        ]
