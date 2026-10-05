from datetime import datetime

from beanie.odm.fields import PydanticObjectId
from pydantic import Field, StrictFloat, StrictStr

from app.schemas.identification.base import BaseSchema


class StudentNoteCreate(BaseSchema):
    """Request schema for creating personalized student notes."""

    organization_id: PydanticObjectId
    student_id: PydanticObjectId
    topic_id: PydanticObjectId
    base_note_id: PydanticObjectId | None = None
    personalized_highlights: StrictStr = Field(..., min_length=1, max_length=10000)
    embedding_vector: list[StrictFloat] | None = Field(default=None, min_items=1, max_items=4096)


class StudentNoteRead(BaseSchema):
    """Response schema for personalized student notes."""

    id: PydanticObjectId
    organization_id: PydanticObjectId
    student_id: PydanticObjectId
    topic_id: PydanticObjectId
    base_note_id: PydanticObjectId | None
    personalized_highlights: StrictStr
    embedding_vector: list[StrictFloat] | None
    created_at: datetime


class StudentNoteUpdate(BaseSchema):
    """Request schema for updating personalized student notes."""

    base_note_id: PydanticObjectId | None = None
    personalized_highlights: StrictStr | None = Field(default=None, min_length=1, max_length=10000)
    embedding_vector: list[StrictFloat] | None = Field(default=None, min_items=1, max_items=4096)
