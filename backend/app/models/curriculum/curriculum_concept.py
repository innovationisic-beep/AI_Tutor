from datetime import datetime
from typing import Any, Dict, List, Optional

from beanie.odm.fields import PydanticObjectId
from pydantic import Field
from pymongo import IndexModel

from app.models.base import BaseDocument
from app.models.curriculum.curriculum_enums import (
    ContentDifficulty,
    CurriculumEntityStatus,
    TopicSource,
)


class CurriculumConcept(BaseDocument):
    """Atomic teachable concept within a curriculum cluster."""

    organization_id: Optional[PydanticObjectId] = Field(default=None)
    topic_id: PydanticObjectId = Field(...)
    topic_source: TopicSource = Field(...)
    curriculum_zone_id: PydanticObjectId = Field(...)
    curriculum_cluster_id: PydanticObjectId = Field(...)
    slug: str = Field(..., min_length=1, max_length=160)
    display_name: str = Field(..., min_length=1, max_length=500)
    canonical_runtime_key: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Immutable stable key used for TopicNote/TopicQuestionBank.concept at runtime.",
    )
    sort_order: int = Field(default=0, ge=0)
    difficulty_level: ContentDifficulty = Field(default="medium")
    estimated_learning_minutes: Optional[int] = Field(default=None, ge=1, le=480)
    study_points: List[str] = Field(
        default_factory=list,
        description="Author-authored bullets: what we will study for this concept.",
    )
    learning_outcomes: List[str] = Field(
        default_factory=list,
        description="Author-authored bullets: learning outcomes for this concept.",
    )
    story_hook: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional authored story hook stage {title, body} for concept teaching.",
    )
    visual_teaching: Optional[Dict[str, Any]] = Field(
        default=None,
        description=(
            "Optional Visual Teaching package: ordered images with semantic regions, "
            "anchors, and connections."
        ),
    )
    teaching_sequence: List[str] = Field(
        default_factory=list,
        description=(
            "Ordered concept teaching stages: vtse | story_hook | visual_teaching | media. "
            "Empty means legacy default (vtse only). Manual order. Auto never writes this."
        ),
    )
    teaching_sequence_mode: str = Field(
        default="manual",
        max_length=16,
        description="manual | auto. Missing or empty means manual.",
    )
    teaching_sequence_auto: List[str] = Field(
        default_factory=list,
        description="Last accepted Auto permutation. Ignored while mode is manual.",
    )
    teaching_sequence_auto_fingerprint: str = Field(
        default="",
        max_length=128,
        description="Hash of the executable stage set and authored context. Not the manual order.",
    )
    teaching_sequence_auto_reason: str = Field(
        default="",
        max_length=240,
        description="Author-facing one-line reason. Not shown to students.",
    )
    teaching_sequence_auto_status: str = Field(
        default="",
        max_length=16,
        description="resolved | fallback | empty.",
    )
    vtse_visuals: Optional[Dict[str, Any]] = Field(
        default=None,
        description=(
            "Optional annotated images for the VTSE stage. Not a teaching-sequence "
            "stage. Absent means VTSE runs exactly as before."
        ),
    )
    vtse_template: Optional[Dict[str, Any]] = Field(
        default=None,
        description=(
            "Optional authored VTSE template {strategy_id, version, payload}. "
            "When set, Zone-1 teaching locks to this strategy and skips auto-select."
        ),
    )
    legacy_concept_key: Optional[str] = Field(default=None, max_length=500)
    published_revision: int = Field(default=0, ge=0)
    status: CurriculumEntityStatus = Field(default="draft")
    deleted_at: Optional[datetime] = Field(default=None)

    class Settings:
        name = "curriculum_concepts"
        indexes = [
            IndexModel(
                [("topic_id", 1), ("topic_source", 1), ("slug", 1)],
                name="uq_topic_concept_slug",
                unique=True,
                partialFilterExpression={"deleted_at": None},
            ),
            IndexModel(
                [("topic_id", 1), ("topic_source", 1), ("canonical_runtime_key", 1)],
                name="uq_topic_canonical_runtime_key",
                unique=True,
                partialFilterExpression={"deleted_at": None},
            ),
            IndexModel([("curriculum_cluster_id", 1), ("sort_order", 1)]),
            IndexModel([("curriculum_zone_id", 1)]),
        ]
