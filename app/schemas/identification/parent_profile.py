from beanie.odm.fields import PydanticObjectId
from pydantic import Field, StrictStr

from .base import BaseSchema


class ParentProfileCreate(BaseSchema):
    organization_id: PydanticObjectId
    user_id: PydanticObjectId
    phone_number: StrictStr | None = Field(default=None, min_length=7, max_length=20)
    occupation: StrictStr | None = Field(default=None, min_length=2, max_length=80)


class ParentProfileUpdate(BaseSchema):
    phone_number: StrictStr | None = Field(default=None, min_length=7, max_length=20)
    occupation: StrictStr | None = Field(default=None, min_length=2, max_length=80)
