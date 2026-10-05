from typing import Optional

from beanie.odm.fields import PydanticObjectId
from pydantic import Field
from pymongo import IndexModel

from app.models.base import BaseDocument


class TopicProgressionMap(BaseDocument):
    """Recommended next topic mapping based on mastery threshold."""

    organization_id: Optional[PydanticObjectId] = Field(
        default=None,
        description="None = platform-wide (admin) graph; set for tenant/teacher graph.",
    )
    topic_id: PydanticObjectId = Field(...)
    recommended_next_topic_id: PydanticObjectId = Field(...)
    minimum_mastery_to_recommend: float = Field(..., ge=0.0, le=100.0)

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
