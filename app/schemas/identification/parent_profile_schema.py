from datetime import datetime

from beanie.odm.fields import PydanticObjectId
from pydantic import Field, StrictStr

from app.schemas.identification.base import BaseSchema


class ParentProfileCreate(BaseSchema):
    """Request schema for creating parent profiles."""

    organization_id: PydanticObjectId
    user_id: PydanticObjectId
    phone_number: StrictStr | None = Field(default=None, min_length=7, max_length=20)
    occupation: StrictStr | None = Field(default=None, min_length=2, max_length=80)


class ParentProfileUpdate(BaseSchema):
    """Request schema for updating parent profiles."""

    phone_number: StrictStr | None = Field(default=None, min_length=7, max_length=20)
    occupation: StrictStr | None = Field(default=None, min_length=2, max_length=80)


class ParentProfileRead(BaseSchema):
    """Response schema for parent profiles."""

    id: PydanticObjectId
    organization_id: PydanticObjectId
    user_id: PydanticObjectId
    phone_number: StrictStr | None
    occupation: StrictStr | None
    created_at: datetime
