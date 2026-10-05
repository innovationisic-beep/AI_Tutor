from datetime import datetime
from typing import List, Literal, Optional

from beanie.odm.fields import PydanticObjectId
from pydantic import Field
from pymongo import IndexModel

from app.models.base import BaseDocument
from app.models.curriculum.curriculum_enums import CurriculumSchemaVersion


class Topic(BaseDocument):
    """Curriculum topic. ``organization_id`` null = platform catalog; else tenant-scoped."""

    organization_id: Optional[PydanticObjectId] = Field(
        default=None,
        description="None = global admin catalog; set for organization-owned topics.",
    )
    subject_id: PydanticObjectId = Field(...)
    topic_name: str = Field(..., min_length=2, max_length=140)
    topic_slug: str = Field(..., min_length=2, max_length=160)
    topic_description: str = Field(..., min_length=10, max_length=3000)
    learning_objectives: List[str] = Field(default_factory=list, max_length=100)
    learning_outcomes: List[str] = Field(default_factory=list, max_length=100)
    key_concepts: List[str] = Field(default_factory=list, max_length=100)
    concept_clusters: Optional[List[List[str]]] = Field(
        default=None,
        description=(
            "Optional grouping of key_concepts into named clusters. "
            "Each inner list is one cluster. If absent, clusters are auto-derived "
            "from key_concepts in chunks of 3–5."
        ),
    )
    common_mistakes: List[str] = Field(default_factory=list, max_length=100)
    difficulty_level: str = Field(..., min_length=1, max_length=20)
    topic_order: int = Field(..., ge=0)
    estimated_time: int = Field(..., ge=1, le=1440)
    default_depth: str = Field(..., min_length=1, max_length=20)
    academic_year: str = Field(..., min_length=4, max_length=20)
    curriculum_version: str = Field(..., min_length=1, max_length=20)
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
    status: Literal["draft", "active", "archived"] = Field(default="draft")
    is_active: bool = Field(default=True)

    class Settings:
        name = "topics"
        indexes = [
            IndexModel([("organization_id", 1), ("subject_id", 1)]),
            IndexModel([("organization_id", 1), ("topic_slug", 1)]),
        ]
