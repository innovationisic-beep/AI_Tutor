from datetime import datetime
from typing import Optional

from beanie.odm.fields import PydanticObjectId
from pydantic import Field
from pymongo import IndexModel

from app.models.base import BaseDocument
from app.models.curriculum.curriculum_enums import (
    CurriculumEntityStatus,
    CurriculumZonePurpose,
    TopicSource,
)


class CurriculumZone(BaseDocument):
    """Teacher-authored curriculum zone (Curriculum Zone 0–4) within a topic."""

    organization_id: Optional[PydanticObjectId] = Field(
        default=None,
        description="None when parent catalog topic is platform-global.",
    )
    topic_id: PydanticObjectId = Field(...)
    topic_source: TopicSource = Field(...)
    zone_number: int = Field(..., ge=0, le=4)
    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    purpose: CurriculumZonePurpose = Field(...)
    allows_vtse: bool = Field(default=False)
    is_system_zone: bool = Field(
        default=False,
        description="True for built-in zones (e.g. Zone 0 curiosity) that cannot be deleted.",
    )
    sort_order: int = Field(default=0, ge=0)
    status: CurriculumEntityStatus = Field(default="draft")
    deleted_at: Optional[datetime] = Field(default=None)

    class Settings:
        name = "curriculum_zones"
        indexes = [
            IndexModel(
                [("topic_id", 1), ("topic_source", 1), ("zone_number", 1)],
                name="uq_topic_zone_number",
                unique=True,
                partialFilterExpression={"deleted_at": None},
            ),
            IndexModel(
                [("organization_id", 1), ("topic_id", 1), ("topic_source", 1), ("status", 1)]
            ),
            IndexModel([("topic_id", 1), ("topic_source", 1), ("sort_order", 1)]),
        ]
