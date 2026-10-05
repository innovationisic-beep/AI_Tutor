from datetime import datetime

from beanie import Document, Indexed
from beanie.odm.fields import PydanticObjectId
from pydantic import Field, StrictBool, StrictFloat, StrictInt, StrictStr
from pymongo import IndexModel

from app.enums.content_enums import NoteType
from app.utils.timestamps import utc_now


class TopicNote(Document):
    """Reusable topic note authored or generated for cross-student reuse."""

    organization_id: Indexed(PydanticObjectId) = Field(...)
    topic_id: Indexed(PydanticObjectId) = Field(...)
    grade: StrictStr = Field(..., min_length=1, max_length=32)
    board: StrictStr = Field(..., min_length=1, max_length=64)
    note_type: NoteType = Field(...)
    content_markdown: StrictStr = Field(..., min_length=1, max_length=25000)
    embedding_vector: list[StrictFloat] | None = Field(default=None, min_items=1, max_items=4096)
    content_version: StrictInt = Field(default=1, ge=1)
    approved: StrictBool = Field(default=False)
    usage_count: StrictInt = Field(default=0, ge=0)
    created_at: datetime = Field(default_factory=utc_now)

    class Settings:
        name = "topic_notes"
        indexes = [
            IndexModel([("organization_id", 1), ("topic_id", 1)]),
        ]
