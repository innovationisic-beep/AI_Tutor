from datetime import datetime

from beanie.odm.fields import PydanticObjectId
from pydantic import Field, StrictBool, StrictFloat, StrictInt, StrictStr

from app.enums.content_enums import AssignmentType
from app.schemas.identification.base import BaseSchema


class AssignmentCreate(BaseSchema):
    """Request schema for creating assignments."""

    organization_id: PydanticObjectId
    topic_id: PydanticObjectId
    teacher_id: PydanticObjectId
    assignment_type: AssignmentType
    description: StrictStr = Field(..., min_length=3, max_length=12000)
    rubric: StrictStr = Field(..., min_length=3, max_length=12000)
    embedding_vector: list[StrictFloat] | None = Field(default=None, min_items=1, max_items=4096)
    due_days: StrictInt = Field(..., ge=0)
    approved: StrictBool = Field(default=False)


class AssignmentRead(BaseSchema):
    """Response schema for assignments."""

    id: PydanticObjectId
    organization_id: PydanticObjectId
    topic_id: PydanticObjectId
    teacher_id: PydanticObjectId
    assignment_type: AssignmentType
    description: StrictStr
    rubric: StrictStr
    embedding_vector: list[StrictFloat] | None
    due_days: StrictInt
    approved: StrictBool
    created_at: datetime


class AssignmentUpdate(BaseSchema):
    """Request schema for updating assignments."""

    assignment_type: AssignmentType | None = None
    description: StrictStr | None = Field(default=None, min_length=3, max_length=12000)
    rubric: StrictStr | None = Field(default=None, min_length=3, max_length=12000)
    embedding_vector: list[StrictFloat] | None = Field(default=None, min_items=1, max_items=4096)
    due_days: StrictInt | None = Field(default=None, ge=0)
    approved: StrictBool | None = None
