from datetime import datetime

from beanie.odm.fields import PydanticObjectId
from pydantic import Field, StrictStr

from app.enums.learning_enums import ConfusionTriggerType
from app.schemas.identification.base import BaseSchema


class ConfusionLogCreate(BaseSchema):
    """Request schema for logging a confusion trigger."""

    organization_id: PydanticObjectId
    student_id: PydanticObjectId
    session_id: PydanticObjectId
    topic_id: PydanticObjectId
    trigger_type: ConfusionTriggerType
    trigger_reason: StrictStr = Field(..., min_length=3, max_length=500)
    timestamp: datetime | None = None


class ConfusionLogRead(BaseSchema):
    """Response schema for confusion log resources."""

    id: PydanticObjectId
    organization_id: PydanticObjectId
    student_id: PydanticObjectId
    session_id: PydanticObjectId
    topic_id: PydanticObjectId
    trigger_type: ConfusionTriggerType
    trigger_reason: StrictStr
    timestamp: datetime
