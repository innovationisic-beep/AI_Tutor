from datetime import datetime

from beanie.odm.fields import PydanticObjectId
from pydantic import Field, StrictFloat, StrictInt, StrictStr

from app.enums.intelligence_enums import AITaskType
from app.schemas.identification.base import BaseSchema


class AIGenerationLogCreate(BaseSchema):
    """Request schema for creating an AI generation log entry."""

    organization_id: PydanticObjectId
    student_id: PydanticObjectId
    topic_id: PydanticObjectId | None = None
    session_id: PydanticObjectId | None = None
    model_used: StrictStr = Field(..., min_length=2, max_length=80)
    task_type: AITaskType
    tokens_used: StrictInt = Field(..., ge=0)
    estimated_cost: StrictFloat = Field(..., ge=0.0)
    response_time_ms: StrictInt = Field(..., ge=0)


class AIGenerationLogRead(BaseSchema):
    """Response schema for AI generation logs."""

    id: PydanticObjectId
    organization_id: PydanticObjectId
    student_id: PydanticObjectId
    topic_id: PydanticObjectId | None
    session_id: PydanticObjectId | None
    model_used: StrictStr
    task_type: AITaskType
    tokens_used: StrictInt
    estimated_cost: StrictFloat
    response_time_ms: StrictInt
    created_at: datetime


class AIGenerationLogUpdate(BaseSchema):
    """Request schema for updating AI generation log fields."""

    model_used: StrictStr | None = Field(default=None, min_length=2, max_length=80)
    task_type: AITaskType | None = None
    tokens_used: StrictInt | None = Field(default=None, ge=0)
    estimated_cost: StrictFloat | None = Field(default=None, ge=0.0)
    response_time_ms: StrictInt | None = Field(default=None, ge=0)
