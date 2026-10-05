from datetime import datetime

from beanie.odm.fields import PydanticObjectId
from pydantic import Field, StrictBool, StrictFloat, StrictInt, StrictStr

from app.enums.content_enums import NoteType
from app.schemas.identification.base import BaseSchema


class TopicNoteCreate(BaseSchema):
    """Request schema for creating reusable topic notes."""

    organization_id: PydanticObjectId
    topic_id: PydanticObjectId
    grade: StrictStr = Field(..., min_length=1, max_length=32)
    board: StrictStr = Field(..., min_length=1, max_length=64)
    note_type: NoteType
    content_markdown: StrictStr = Field(..., min_length=1, max_length=25000)
    embedding_vector: list[StrictFloat] | None = Field(default=None, min_items=1, max_items=4096)
    content_version: StrictInt = Field(default=1, ge=1)
    approved: StrictBool = Field(default=False)
    usage_count: StrictInt = Field(default=0, ge=0)


class TopicNoteRead(BaseSchema):
    """Response schema for topic notes."""

    id: PydanticObjectId
    organization_id: PydanticObjectId
    topic_id: PydanticObjectId
    grade: StrictStr
    board: StrictStr
    note_type: NoteType
    content_markdown: StrictStr
    embedding_vector: list[StrictFloat] | None
    content_version: StrictInt
    approved: StrictBool
    usage_count: StrictInt
    created_at: datetime


class TopicNoteUpdate(BaseSchema):
    """Request schema for updating reusable topic notes."""

    grade: StrictStr | None = Field(default=None, min_length=1, max_length=32)
    board: StrictStr | None = Field(default=None, min_length=1, max_length=64)
    note_type: NoteType | None = None
    content_markdown: StrictStr | None = Field(default=None, min_length=1, max_length=25000)
    embedding_vector: list[StrictFloat] | None = Field(default=None, min_items=1, max_items=4096)
    content_version: StrictInt | None = Field(default=None, ge=1)
    approved: StrictBool | None = None
    usage_count: StrictInt | None = Field(default=None, ge=0)
