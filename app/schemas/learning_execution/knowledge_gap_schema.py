from datetime import datetime

from beanie.odm.fields import PydanticObjectId
from pydantic import Field, StrictBool, StrictFloat, StrictStr

from app.schemas.identification.base import BaseSchema


class KnowledgeGapCreate(BaseSchema):
    """Request schema for creating a detected knowledge gap."""

    organization_id: PydanticObjectId
    student_id: PydanticObjectId
    topic_id: PydanticObjectId
    root_cause_topic_id: PydanticObjectId
    severity_score: StrictFloat = Field(..., ge=0.0, le=100.0)
    detected_reason: StrictStr = Field(..., min_length=3, max_length=500)
    resolved: StrictBool = Field(default=False)


class KnowledgeGapUpdate(BaseSchema):
    """Request schema for updating a knowledge gap state."""

    severity_score: StrictFloat | None = Field(default=None, ge=0.0, le=100.0)
    detected_reason: StrictStr | None = Field(default=None, min_length=3, max_length=500)
    resolved: StrictBool | None = None


class KnowledgeGapRead(BaseSchema):
    """Response schema for knowledge gap resources."""

    id: PydanticObjectId
    organization_id: PydanticObjectId
    student_id: PydanticObjectId
    topic_id: PydanticObjectId
    root_cause_topic_id: PydanticObjectId
    severity_score: StrictFloat
    detected_reason: StrictStr
    resolved: StrictBool
    created_at: datetime
