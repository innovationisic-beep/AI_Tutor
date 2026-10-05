from datetime import datetime
from typing import List, Literal, Optional

from beanie.odm.fields import PydanticObjectId
from pydantic import EmailStr, Field
from pymongo import IndexModel

from app.models.base import BaseDocument

UserRole = Literal["admin", "organization", "teacher", "student", "parent"]


class User(BaseDocument):
    """
    Authentication and authorization identity.
    organization_id comes from BaseDocument (optional); null for platform admins created via create_system_user.
    """

    email: EmailStr = Field(...)
    password_hash: str = Field(..., min_length=32, max_length=256)
    role: UserRole = Field(...)
    status: Literal["active", "suspended"] = Field(default="active")
    email_verified: bool = Field(default=False)
    last_login: Optional[datetime] = Field(default=None)
    assigned_classes: List[str] = Field(default_factory=list)
    assigned_subjects: List[str] = Field(default_factory=list)

    class Settings:
        name = "users"
        indexes = [
            IndexModel([("organization_id", 1), ("email", 1)], unique=True),
            IndexModel([("organization_id", 1), ("role", 1)]),
        ]
