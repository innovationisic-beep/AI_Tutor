from datetime import datetime

from beanie.odm.fields import PydanticObjectId
from pydantic import Field, StrictBool, StrictStr

from app.enums.curriculum_enums import CurriculumStatus
from app.schemas.base import BaseSchema


class SubjectCreate(BaseSchema):
    """Request schema for creating a subject."""

    organization_id: PydanticObjectId
    name: StrictStr = Field(..., min_length=2, max_length=120)
    grade: StrictStr = Field(..., min_length=1, max_length=32)
    board: StrictStr = Field(..., min_length=1, max_length=64)
    description: StrictStr = Field(..., min_length=10, max_length=2000)
    academic_year: StrictStr = Field(..., min_length=4, max_length=20)
    curriculum_version: StrictStr = Field(..., min_length=1, max_length=20)
    status: CurriculumStatus = Field(default=CurriculumStatus.draft)
    is_active: StrictBool = Field(default=True)


class SubjectUpdate(BaseSchema):
    """Request schema for updating a subject."""

    name: StrictStr | None = Field(default=None, min_length=2, max_length=120)
    grade: StrictStr | None = Field(default=None, min_length=1, max_length=32)
    board: StrictStr | None = Field(default=None, min_length=1, max_length=64)
    description: StrictStr | None = Field(default=None, min_length=10, max_length=2000)
    academic_year: StrictStr | None = Field(default=None, min_length=4, max_length=20)
    curriculum_version: StrictStr | None = Field(default=None, min_length=1, max_length=20)
    status: CurriculumStatus | None = None
    is_active: StrictBool | None = None


class SubjectRead(BaseSchema):
    """Response schema for subject resources."""

    id: PydanticObjectId
    organization_id: PydanticObjectId
    name: StrictStr
    grade: StrictStr
    board: StrictStr
    description: StrictStr
    academic_year: StrictStr
    curriculum_version: StrictStr
    status: CurriculumStatus
    is_active: StrictBool
    created_at: datetime
    updated_at: datetime
