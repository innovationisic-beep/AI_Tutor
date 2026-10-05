from datetime import datetime
from typing import List, Optional

from beanie.odm.fields import PydanticObjectId
from pydantic import Field
from pymongo import IndexModel

from app.models.base import BaseDocument
from app.models.curriculum.curriculum_enums import CurriculumSchemaVersion


class TeacherTopic(BaseDocument):
    """Teacher-authored curriculum topic scoped to org, class, and subject."""

    organization_id: PydanticObjectId = Field(...)
    teacher_id: PydanticObjectId = Field(...)
    class_id: str = Field(..., min_length=1, max_length=64)
    subject_id: str = Field(..., min_length=1, max_length=64)
    topic_name: str = Field(..., min_length=1, max_length=500)
    key_concepts: List[str] = Field(default_factory=list)
    concept_clusters: Optional[List[List[str]]] = Field(
        default=None,
        description=(
            "Optional grouping of key_concepts into clusters. "
            "Each inner list is one cluster. If absent, clusters are auto-derived."
        ),
    )
    curriculum_topic_id: Optional[PydanticObjectId] = Field(default=None)
    curriculum_schema_version: CurriculumSchemaVersion = Field(
        default="v1",
        description="v1=flat key_concepts; v2=structured curriculum tree.",
    )
    curriculum_revision: int = Field(default=0, ge=0)
    curriculum_published_at: Optional[datetime] = Field(default=None)
    supports_class_sessions: bool = Field(
        default=False,
        description="Placeholder for Phase 3 class-session scheduling.",
    )

    class Settings:
        name = "teacher_topics"
        indexes = [
            IndexModel(
                [
                    ("organization_id", 1),
                    ("teacher_id", 1),
                    ("class_id", 1),
                    ("subject_id", 1),
                ]
            ),
            IndexModel(
                [
                    ("organization_id", 1),
                    ("class_id", 1),
                    ("subject_id", 1),
                    ("topic_name", 1),
                ],
                unique=True,
            ),
        ]
