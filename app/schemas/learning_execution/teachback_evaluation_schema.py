from datetime import datetime

from beanie.odm.fields import PydanticObjectId
from pydantic import Field, StrictFloat, StrictStr

from app.schemas.identification.base import BaseSchema


class TeachbackEvaluationCreate(BaseSchema):
    """Request schema for creating teachback evaluations."""

    organization_id: PydanticObjectId
    student_id: PydanticObjectId
    session_id: PydanticObjectId
    topic_id: PydanticObjectId
    student_response: StrictStr = Field(..., min_length=1, max_length=6000)
    evaluation_score: StrictFloat = Field(..., ge=0.0, le=100.0)
    feedback: StrictStr = Field(..., min_length=1, max_length=3000)
    model_used: StrictStr = Field(..., min_length=2, max_length=80)
    timestamp: datetime | None = None


class TeachbackEvaluationRead(BaseSchema):
    """Response schema for teachback evaluation resources."""

    id: PydanticObjectId
    organization_id: PydanticObjectId
    student_id: PydanticObjectId
    session_id: PydanticObjectId
    topic_id: PydanticObjectId
    student_response: StrictStr
    evaluation_score: StrictFloat
    feedback: StrictStr
    model_used: StrictStr
    timestamp: datetime
