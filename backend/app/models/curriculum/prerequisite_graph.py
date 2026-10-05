from typing import Optional

from beanie.odm.fields import PydanticObjectId
from pydantic import Field
from pymongo import IndexModel

from app.models.base import BaseDocument


class PrerequisiteGraph(BaseDocument):
    """Directed graph edge from prerequisite topic to target topic."""

    organization_id: Optional[PydanticObjectId] = Field(
        default=None,
        description="None = platform-wide (admin) graph; set for tenant/teacher graph.",
    )
    topic_id: PydanticObjectId = Field(...)
    prerequisite_topic_id: PydanticObjectId = Field(...)

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
