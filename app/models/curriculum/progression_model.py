from datetime import datetime

from beanie import Indexed
from beanie.odm.fields import PydanticObjectId
from pydantic import Field, StrictFloat, validator
from pymongo import IndexModel

from app.models.base import BaseDocument
from app.utils.timestamps import utc_now


class TopicProgressionMap(BaseDocument):
    """Recommended next topic mapping based on mastery threshold."""

    organization_id: Indexed(PydanticObjectId) = Field(...)
    topic_id: Indexed(PydanticObjectId) = Field(...)
    recommended_next_topic_id: Indexed(PydanticObjectId) = Field(...)
    minimum_mastery_to_recommend: StrictFloat = Field(..., ge=0.0, le=100.0)

    created_at: datetime = Field(default_factory=utc_now)

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

    class Settings:
        name = "topic_progression_map"
        indexes = [
            IndexModel([("organization_id", 1), ("topic_id", 1)]),
            IndexModel(
                [
                    ("organization_id", 1),
                    ("topic_id", 1),
                    ("recommended_next_topic_id", 1),
                ],
                unique=True,
            ),
        ]
