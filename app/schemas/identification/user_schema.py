from datetime import datetime

from beanie.odm.fields import PydanticObjectId
from pydantic import EmailStr, Field, StrictBool, StrictStr, validator

from app.enums.user_enums import UserRole, UserStatus
from app.schemas.identification.base import BaseSchema


class UserCreate(BaseSchema):
    """Request schema for creating users."""

    organization_id: PydanticObjectId
    email: EmailStr
    password: StrictStr = Field(..., min_length=8, max_length=128)
    role: UserRole
    status: UserStatus = Field(default=UserStatus.active)
    email_verified: StrictBool = Field(default=False)

    @validator("email")
    def normalize_email(cls, value: EmailStr) -> str:
        return str(value).strip().lower()


class UserUpdate(BaseSchema):
    """Request schema for updating users."""

    email: EmailStr | None = None
    password: StrictStr | None = Field(default=None, min_length=8, max_length=128)
    role: UserRole | None = None
    status: UserStatus | None = None
    email_verified: StrictBool | None = None
    last_login: datetime | None = None

    @validator("email")
    def normalize_optional_email(cls, value: EmailStr | None) -> str | None:
        if value is None:
            return None
        return str(value).strip().lower()


class UserRead(BaseSchema):
    """Response schema for users."""

    id: PydanticObjectId
    organization_id: PydanticObjectId
    email: EmailStr
    role: UserRole
    status: UserStatus
    email_verified: StrictBool
    created_at: datetime
    last_login: datetime | None


class UserLogin(BaseSchema):
    """Request schema for login endpoint."""

    email: EmailStr
    password: StrictStr = Field(..., min_length=8, max_length=128)

    @validator("email")
    def normalize_email(cls, value: EmailStr) -> str:
        return str(value).strip().lower()


class TokenPayload(BaseSchema):
    """JWT payload schema for future authentication integration."""

    sub: PydanticObjectId
    organization_id: PydanticObjectId
    role: UserRole
