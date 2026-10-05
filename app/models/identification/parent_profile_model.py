from datetime import datetime

from beanie import Document, Indexed
from beanie.odm.fields import PydanticObjectId
from pydantic import Field, StrictStr
from pymongo import IndexModel

from app.utils.timestamps import utc_now


class ParentProfile(Document):
    """Parent profile linked to a tenant-scoped user account."""

    organization_id: Indexed(PydanticObjectId) = Field(...)
    user_id: Indexed(PydanticObjectId) = Field(...)
    phone_number: StrictStr | None = Field(default=None, min_length=7, max_length=20)
    occupation: StrictStr | None = Field(default=None, min_length=2, max_length=80)
    created_at: datetime = Field(default_factory=utc_now)

    class Settings:
        name = "parent_profiles"
        indexes = [
            IndexModel([("organization_id", 1), ("user_id", 1)], unique=True),
        ]
