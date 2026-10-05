from datetime import datetime

from beanie import Indexed
from beanie.odm.fields import PydanticObjectId
from pydantic import Field, StrictBool, StrictStr
from pymongo import IndexModel

from app.enums.curriculum_enums import CurriculumStatus
from app.models.base import BaseDocument
from app.utils.timestamps import utc_now


class Subject(BaseDocument):
    """Tenant-scoped subject definition for curriculum management."""

    organization_id: Indexed(PydanticObjectId) = Field(...)

    name: Indexed(StrictStr) = Field(..., min_length=2, max_length=120)
    grade: Indexed(StrictStr) = Field(..., min_length=1, max_length=32)
    board: StrictStr = Field(..., min_length=1, max_length=64)
    description: StrictStr = Field(..., min_length=10, max_length=2000)

    academic_year: StrictStr = Field(..., min_length=4, max_length=20)
    curriculum_version: StrictStr = Field(..., min_length=1, max_length=20)

    status: CurriculumStatus = Field(default=CurriculumStatus.draft)
    is_active: StrictBool = Field(default=True)

    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    class Settings:
        name = "subjects"
        indexes = [
            IndexModel([("organization_id", 1), ("grade", 1)]),
            IndexModel([("organization_id", 1), ("name", 1)]),
        ]
