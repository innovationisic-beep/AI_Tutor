from datetime import datetime
from typing import List, Optional

from beanie.odm.fields import PydanticObjectId
from pydantic import Field
from pymongo import IndexModel

from app.models.base import BaseDocument
from app.models.curriculum.curriculum_enums import CurriculumEntityStatus, TopicSource


class CurriculumCluster(BaseDocument):
    """Cluster within a curriculum zone."""

    organization_id: Optional[PydanticObjectId] = Field(default=None)
    topic_id: PydanticObjectId = Field(...)
    topic_source: TopicSource = Field(...)
    curriculum_zone_id: PydanticObjectId = Field(...)
    cluster_number: int = Field(..., ge=1, le=100)
    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    study_points: List[str] = Field(
        default_factory=list,
        description="Teacher-authored bullets: what we will study in this cluster.",
    )
    learning_outcomes: List[str] = Field(
        default_factory=list,
        description="Teacher-authored bullets: learning outcomes for this cluster.",
    )
    sort_order: int = Field(default=0, ge=0)
    estimated_learning_minutes: Optional[int] = Field(default=None, ge=1, le=1440)
    status: CurriculumEntityStatus = Field(default="draft")
    deleted_at: Optional[datetime] = Field(default=None)

    class Settings:
        name = "curriculum_clusters"
        indexes = [
            IndexModel(
                [("curriculum_zone_id", 1), ("cluster_number", 1)],
                name="uq_zone_cluster_number",
                unique=True,
                partialFilterExpression={"deleted_at": None},
            ),
            IndexModel([("curriculum_zone_id", 1), ("sort_order", 1)]),
            IndexModel([("topic_id", 1), ("topic_source", 1)]),
        ]
