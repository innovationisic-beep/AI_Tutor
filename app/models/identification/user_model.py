from datetime import datetime

from beanie import Document, Indexed
from beanie.odm.fields import PydanticObjectId
from pydantic import EmailStr, Field, StrictBool, StrictStr, validator
from pymongo import IndexModel

from app.enums.user_enums import UserRole, UserStatus
from app.utils.timestamps import utc_now


class User(Document):
    """Authentication and authorization identity record scoped to an organization."""

    organization_id: Indexed(PydanticObjectId) = Field(...)
    email: EmailStr = Field(...)
    password_hash: StrictStr = Field(..., min_length=32, max_length=256)
    role: UserRole = Field(...)
    status: UserStatus = Field(default=UserStatus.active)
    email_verified: StrictBool = Field(default=False)
    created_at: datetime = Field(default_factory=utc_now)
    last_login: datetime | None = Field(default=None)

    @validator("email")
    def normalize_email(cls, value: EmailStr) -> str:
        return str(value).strip().lower()

    class Settings:
        name = "users"
        indexes = [
            IndexModel([("organization_id", 1), ("email", 1)], unique=True),
            IndexModel([("organization_id", 1), ("role", 1)]),
        ]
