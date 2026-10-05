from datetime import datetime

from beanie.odm.fields import PydanticObjectId
from pydantic import validator

from app.schemas.base import BaseSchema


class PrerequisiteGraphCreate(BaseSchema):
    """Request schema for creating prerequisite graph edges."""

    organization_id: PydanticObjectId
    topic_id: PydanticObjectId
    prerequisite_topic_id: PydanticObjectId

    @validator("prerequisite_topic_id")
    def prevent_self_dependency(
        cls,
        value: PydanticObjectId,
        values: dict[str, PydanticObjectId],
    ) -> PydanticObjectId:
        topic_id = values.get("topic_id")
        if topic_id is not None and topic_id == value:
            raise ValueError("topic_id and prerequisite_topic_id must be different")
        return value


class PrerequisiteGraphRead(BaseSchema):
    """Response schema for prerequisite graph edges."""

    id: PydanticObjectId
    organization_id: PydanticObjectId
    topic_id: PydanticObjectId
    prerequisite_topic_id: PydanticObjectId
    created_at: datetime
