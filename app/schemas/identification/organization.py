from pydantic import Field, StrictInt, StrictStr

from app.models.enums import OrganizationStatus, SubscriptionPlan

from .base import BaseSchema


class OrganizationCreate(BaseSchema):
    name: StrictStr = Field(..., min_length=2, max_length=120)
    subscription_plan: SubscriptionPlan = Field(default=SubscriptionPlan.free)
    max_students: StrictInt = Field(..., ge=0)
    max_teachers: StrictInt = Field(..., ge=0)
    status: OrganizationStatus = Field(default=OrganizationStatus.active)


class OrganizationUpdate(BaseSchema):
    name: StrictStr | None = Field(default=None, min_length=2, max_length=120)
    subscription_plan: SubscriptionPlan | None = None
    max_students: StrictInt | None = Field(default=None, ge=0)
    max_teachers: StrictInt | None = Field(default=None, ge=0)
    status: OrganizationStatus | None = None
