from typing import List, Optional

from beanie.odm.fields import PydanticObjectId
from pydantic import Field
from pymongo import IndexModel

from app.models.base import BaseDocument


class StudentNote(BaseDocument):
    """Personalized notes generated for a specific student learning path."""

    organization_id: PydanticObjectId = Field(...)
    student_id: PydanticObjectId = Field(...)
    topic_id: PydanticObjectId = Field(...)
    base_note_id: Optional[PydanticObjectId] = Field(default=None)
    personalized_highlights: str = Field(..., min_length=1, max_length=10000)
    embedding_vector: Optional[List[float]] = Field(default=None, max_length=4096)

    class Settings:
        name = "student_notes"
        indexes = [
            IndexModel([("organization_id", 1), ("student_id", 1)]),
        ]
