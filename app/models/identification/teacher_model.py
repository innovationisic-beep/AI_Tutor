from datetime import datetime

from beanie import Document, Indexed
from beanie.odm.fields import PydanticObjectId
from pydantic import Field, StrictStr
from pymongo import IndexModel

from app.utils.timestamps import utc_now


class Teacher(Document):
    """Teacher profile mapped to a user identity within a tenant."""

    organization_id: Indexed(PydanticObjectId) = Field(...)
    user_id: Indexed(PydanticObjectId) = Field(...)
    subjects: list[StrictStr] = Field(..., min_items=1, max_items=100)
    grades: list[StrictStr] = Field(..., min_items=1, max_items=100)
    created_at: datetime = Field(default_factory=utc_now)

    class Settings:
        name = "teachers"
        indexes = [
            IndexModel([("organization_id", 1), ("user_id", 1)], unique=True),
        ]
