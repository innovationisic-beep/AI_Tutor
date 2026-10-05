from datetime import datetime

from beanie.odm.fields import PydanticObjectId
from pydantic import EmailStr, Field, StrictBool, StrictStr, validator

from app.models.enums import UserRole, UserStatus

from .base import BaseSchema


class UserCreate(BaseSchema):
    organization_id: PydanticObjectId
    email: EmailStr = Field(..., max_length=320)
    password: StrictStr = Field(..., min_length=8, max_length=128)
    role: UserRole
    status: UserStatus = Field(default=UserStatus.active)
    email_verified: StrictBool = Field(default=False)

    @validator("email")
    def normalize_email(cls, value: EmailStr) -> EmailStr:
        return EmailStr(str(value).strip().lower())


class UserUpdate(BaseSchema):
    email: EmailStr | None = Field(default=None, max_length=320)
    password: StrictStr | None = Field(default=None, min_length=8, max_length=128)
    role: UserRole | None = None
    status: UserStatus | None = None
    email_verified: StrictBool | None = None
    last_login: datetime | None = None

    @validator("email")
    def normalize_email(cls, value: EmailStr | None) -> EmailStr | None:
        if value is None:
            return None
        return EmailStr(str(value).strip().lower())


class UserLogin(BaseSchema):
    email: EmailStr = Field(..., max_length=320)
    password: StrictStr = Field(..., min_length=8, max_length=128)

    @validator("email")
    def normalize_email(cls, value: EmailStr) -> EmailStr:
        return EmailStr(str(value).strip().lower())


class TokenPayload(BaseSchema):
    sub: PydanticObjectId
    organization_id: PydanticObjectId
    role: UserRole
