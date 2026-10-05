from datetime import datetime

from beanie import Document, Indexed
from beanie.odm.fields import PydanticObjectId
from pydantic import Field, StrictFloat, StrictStr
from pymongo import IndexModel

from app.utils.timestamps import utc_now


class StudentNote(Document):
    """Personalized notes generated for a specific student learning path."""

    organization_id: Indexed(PydanticObjectId) = Field(...)
    student_id: Indexed(PydanticObjectId) = Field(...)
    topic_id: Indexed(PydanticObjectId) = Field(...)
    base_note_id: PydanticObjectId | None = Field(default=None)
    personalized_highlights: StrictStr = Field(..., min_length=1, max_length=10000)
    embedding_vector: list[StrictFloat] | None = Field(default=None, min_items=1, max_items=4096)
    created_at: datetime = Field(default_factory=utc_now)

    class Settings:
        name = "student_notes"
        indexes = [
            IndexModel([("organization_id", 1), ("student_id", 1)]),
        ]
