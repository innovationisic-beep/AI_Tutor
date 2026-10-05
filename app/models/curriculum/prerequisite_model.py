from datetime import datetime

from beanie import Indexed
from beanie.odm.fields import PydanticObjectId
from pydantic import Field, validator
from pymongo import IndexModel

from app.models.base import BaseDocument
from app.utils.timestamps import utc_now


class PrerequisiteGraph(BaseDocument):
    """Directed graph edge from prerequisite topic to target topic."""

    organization_id: Indexed(PydanticObjectId) = Field(...)
    topic_id: Indexed(PydanticObjectId) = Field(...)
    prerequisite_topic_id: Indexed(PydanticObjectId) = Field(...)

    created_at: datetime = Field(default_factory=utc_now)

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

    class Settings:
        name = "prerequisite_graph"
        indexes = [
            IndexModel([("organization_id", 1), ("topic_id", 1)]),
            IndexModel([("organization_id", 1), ("prerequisite_topic_id", 1)]),
            IndexModel(
                [
                    ("organization_id", 1),
                    ("topic_id", 1),
                    ("prerequisite_topic_id", 1),
                ],
                unique=True,
            ),
        ]
