from datetime import datetime
from typing import Literal

from beanie.odm.fields import PydanticObjectId
from pydantic import Field, StrictInt, StrictStr

from app.schemas.identification.base import BaseSchema


class OrganizationCreate(BaseSchema):
    """Request schema for creating organizations."""

    name: StrictStr = Field(..., min_length=2, max_length=120)
    subscription_plan: Literal["free", "basic", "premium"] = Field(default="free")
    max_students: StrictInt = Field(..., ge=0)
    max_teachers: StrictInt = Field(..., ge=0)
    status: Literal["active", "suspended"] = Field(default="active")


class OrganizationUpdate(BaseSchema):
    """Request schema for organization updates."""

    name: StrictStr | None = Field(default=None, min_length=2, max_length=120)
    subscription_plan: Literal["free", "basic", "premium"] | None = None
    max_students: StrictInt | None = Field(default=None, ge=0)
    max_teachers: StrictInt | None = Field(default=None, ge=0)
    status: Literal["active", "suspended"] | None = None


class OrganizationRead(BaseSchema):
    """Response schema for organizations."""

    id: PydanticObjectId
    name: StrictStr
    subscription_plan: Literal["free", "basic", "premium"]
    max_students: StrictInt
    max_teachers: StrictInt
    status: Literal["active", "suspended"]
    created_at: datetime
    updated_at: datetime
