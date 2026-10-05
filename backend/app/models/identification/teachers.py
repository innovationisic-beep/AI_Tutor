from beanie.odm.fields import PydanticObjectId
from pydantic import ConfigDict, Field
from pymongo import IndexModel

from app.models.base import BaseDocument


class Teacher(BaseDocument):
    """Teacher profile linked to a user within a tenant."""

    model_config = ConfigDict(extra="ignore")

    organization_id: PydanticObjectId = Field(...)
    user_id: PydanticObjectId = Field(...)

    class Settings:
        name = "teachers"
        indexes = [
            IndexModel([("organization_id", 1), ("user_id", 1)], unique=True),
        ]
