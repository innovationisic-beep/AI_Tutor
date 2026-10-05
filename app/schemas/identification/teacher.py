from beanie.odm.fields import PydanticObjectId
from pydantic import Field, StrictStr

from .base import BaseSchema


class TeacherCreate(BaseSchema):
    organization_id: PydanticObjectId
    user_id: PydanticObjectId
    subjects: list[StrictStr] = Field(..., min_items=1, max_items=50)
    grades: list[StrictStr] = Field(..., min_items=1, max_items=50)


class TeacherUpdate(BaseSchema):
    subjects: list[StrictStr] | None = Field(default=None, min_items=1, max_items=50)
    grades: list[StrictStr] | None = Field(default=None, min_items=1, max_items=50)
