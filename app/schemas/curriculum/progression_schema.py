from datetime import datetime

from beanie.odm.fields import PydanticObjectId
from pydantic import Field, StrictFloat, validator

from app.schemas.base import BaseSchema


class TopicProgressionMapCreate(BaseSchema):
    """Request schema for creating topic progression rules."""

    organization_id: PydanticObjectId
    topic_id: PydanticObjectId
    recommended_next_topic_id: PydanticObjectId
    minimum_mastery_to_recommend: StrictFloat = Field(..., ge=0.0, le=100.0)

    @validator("recommended_next_topic_id")
    def prevent_self_progression(
        cls,
        value: PydanticObjectId,
        values: dict[str, PydanticObjectId],
    ) -> PydanticObjectId:
        topic_id = values.get("topic_id")
        if topic_id is not None and topic_id == value:
            raise ValueError("topic_id and recommended_next_topic_id must be different")
        return value


class TopicProgressionMapRead(BaseSchema):
    """Response schema for topic progression map entries."""

    id: PydanticObjectId
    organization_id: PydanticObjectId
    topic_id: PydanticObjectId
    recommended_next_topic_id: PydanticObjectId
    minimum_mastery_to_recommend: StrictFloat
    created_at: datetime
