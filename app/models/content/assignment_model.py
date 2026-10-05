from datetime import datetime

from beanie import Document, Indexed
from beanie.odm.fields import PydanticObjectId
from pydantic import Field, StrictBool, StrictFloat, StrictInt, StrictStr
from pymongo import IndexModel

from app.enums.content_enums import AssignmentType
from app.utils.timestamps import utc_now


class Assignment(Document):
    """Teacher-authored assignment record with reusable rubric context."""

    organization_id: Indexed(PydanticObjectId) = Field(...)
    topic_id: Indexed(PydanticObjectId) = Field(...)
    teacher_id: Indexed(PydanticObjectId) = Field(...)
    assignment_type: AssignmentType = Field(...)
    description: StrictStr = Field(..., min_length=3, max_length=12000)
    rubric: StrictStr = Field(..., min_length=3, max_length=12000)
    embedding_vector: list[StrictFloat] | None = Field(default=None, min_items=1, max_items=4096)
    due_days: StrictInt = Field(..., ge=0)
    approved: StrictBool = Field(default=False)
    created_at: datetime = Field(default_factory=utc_now)

    class Settings:
        name = "assignments"
        indexes = [
            IndexModel([("organization_id", 1), ("topic_id", 1)]),
        ]
