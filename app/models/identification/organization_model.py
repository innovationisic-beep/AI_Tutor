from datetime import datetime
from typing import Literal

from beanie import Document, Indexed
from pydantic import Field, StrictInt, StrictStr
from pymongo import IndexModel

from app.utils.timestamps import utc_now


class Organization(Document):
    """Tenant root entity for subscription and capacity controls."""

    name: Indexed(StrictStr, unique=True) = Field(..., min_length=2, max_length=120)
    subscription_plan: Literal["free", "basic", "premium"] = Field(default="free")
    max_students: StrictInt = Field(..., ge=0)
    max_teachers: StrictInt = Field(..., ge=0)
    status: Literal["active", "suspended"] = Field(default="active")
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    class Settings:
        name = "organizations"
        indexes = [
            IndexModel([("name", 1)], unique=True),
        ]
