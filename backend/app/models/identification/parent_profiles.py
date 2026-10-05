from typing import Optional

from beanie.odm.fields import PydanticObjectId
from pydantic import Field
from pymongo import IndexModel

from app.models.base import BaseDocument


class ParentProfile(BaseDocument):
    """Parent profile linked to a tenant-scoped user account."""

    organization_id: PydanticObjectId = Field(...)
    user_id: PydanticObjectId = Field(...)
    phone_number: Optional[str] = Field(default=None, min_length=7, max_length=20)
    occupation: Optional[str] = Field(default=None, min_length=2, max_length=80)

    class Settings:
        name = "parent_profiles"
        indexes = [
            IndexModel([("organization_id", 1), ("user_id", 1)], unique=True),
        ]
