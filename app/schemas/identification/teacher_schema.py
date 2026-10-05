from datetime import datetime

from beanie.odm.fields import PydanticObjectId
from pydantic import Field, StrictStr

from app.schemas.identification.base import BaseSchema


class TeacherCreate(BaseSchema):
    """Request schema for creating teacher profiles."""

    organization_id: PydanticObjectId
    user_id: PydanticObjectId
    subjects: list[StrictStr] = Field(..., min_items=1, max_items=100)
    grades: list[StrictStr] = Field(..., min_items=1, max_items=100)


class TeacherUpdate(BaseSchema):
    """Request schema for updating teacher profiles."""

    subjects: list[StrictStr] | None = Field(default=None, min_items=1, max_items=100)
    grades: list[StrictStr] | None = Field(default=None, min_items=1, max_items=100)


class TeacherRead(BaseSchema):
    """Response schema for teacher profiles."""

    id: PydanticObjectId
    organization_id: PydanticObjectId
    user_id: PydanticObjectId
    subjects: list[StrictStr]
    grades: list[StrictStr]
    created_at: datetime
