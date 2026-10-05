from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from uuid import uuid4

from beanie.odm.fields import PydanticObjectId
from pydantic import BaseModel, Field, model_validator
from pymongo import IndexModel

from app.models.base import BaseDocument
from app.models.classroom.classroom_enums import (
    ClassSessionPlanItemType,
    ClassSessionPlanStatus,
)
from app.models.curriculum.curriculum_enums import CurriculumSchemaVersion, TopicSource


class ClassSessionPlanItem(BaseModel):
    """One agenda row in a classroom session plan."""

    item_id: str = Field(default_factory=lambda: str(uuid4()))
    sort_order: int = Field(..., ge=0)
    item_type: ClassSessionPlanItemType
    curriculum_zone_id: Optional[PydanticObjectId] = None
    curriculum_cluster_id: Optional[PydanticObjectId] = None
    curriculum_concept_id: Optional[PydanticObjectId] = None
    zone_number: Optional[int] = Field(default=None, ge=0, le=4)
    canonical_runtime_key_snapshot: Optional[str] = Field(default=None, max_length=500)
    display_name_snapshot: Optional[str] = Field(default=None, max_length=500)
    estimated_minutes: Optional[int] = Field(default=None, ge=1, le=480)
    is_required: bool = True
    non_curriculum_label: Optional[str] = Field(default=None, max_length=200)
    resolved_runtime_keys: Optional[List[str]] = Field(
        default=None,
        description="Frozen at instance create for cluster_coverage expansion.",
    )
    resolved_concept_ids: Optional[List[PydanticObjectId]] = Field(
        default=None,
        description="Frozen concept ids aligned with resolved_runtime_keys.",
    )

    @model_validator(mode="after")
    def validate_item_shape(self) -> ClassSessionPlanItem:
        if self.item_type == "non_curriculum":
            if (
                self.curriculum_zone_id is not None
                or self.curriculum_cluster_id is not None
                or self.curriculum_concept_id is not None
            ):
                raise ValueError(
                    "non_curriculum items must not reference curriculum entities"
                )
            return self
        if self.item_type == "zone_coverage":
            if self.curriculum_zone_id is None:
                raise ValueError("zone_coverage items require curriculum_zone_id")
            if (
                self.curriculum_cluster_id is not None
                or self.curriculum_concept_id is not None
            ):
                raise ValueError(
                    "zone_coverage items must not reference clusters or concepts"
                )
            if self.zone_number is not None and self.zone_number != 0:
                raise ValueError("zone_coverage items must use zone_number 0")
            return self
        if self.curriculum_zone_id is None or self.curriculum_cluster_id is None:
            raise ValueError(
                "curriculum items require curriculum_zone_id and curriculum_cluster_id"
            )
        if self.item_type == "concept_coverage" and self.curriculum_concept_id is None:
            raise ValueError("concept_coverage items require curriculum_concept_id")
        return self


class ClassSessionPlan(BaseDocument):
    """Coverage plan for one classroom or catalog (independent-student) session."""

    plan_scope: TopicSource = Field(
        default="teacher",
        description="teacher=institution class plan; catalog=platform topic plan for independent students.",
    )
    organization_id: Optional[PydanticObjectId] = Field(
        default=None,
        description="Required for teacher scope; None for catalog scope.",
    )
    teacher_id: PydanticObjectId = Field(...)
    teacher_topic_id: Optional[PydanticObjectId] = Field(default=None)
    catalog_topic_id: Optional[PydanticObjectId] = Field(default=None)
    class_id: str = Field(default="", max_length=64)
    subject_id: str = Field(default="", max_length=64)
    sequence_number: int = Field(..., ge=1, le=500)
    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    session_study_points: List[str] = Field(
        default_factory=list,
        description="Teacher-authored bullets: what we will study this session.",
    )
    session_learning_outcomes: List[str] = Field(
        default_factory=list,
        description="Teacher-authored bullets: learning outcomes for this session.",
    )
    target_duration_minutes: Optional[int] = Field(default=None, ge=1, le=480)
    teacher_notes: str = Field(default="", max_length=4000)
    curriculum_schema_version: CurriculumSchemaVersion = Field(default="v2")
    curriculum_revision: int = Field(default=0, ge=0)
    items: List[ClassSessionPlanItem] = Field(default_factory=list)
    status: ClassSessionPlanStatus = Field(default="draft")
    published_at: Optional[datetime] = Field(default=None)
    deleted_at: Optional[datetime] = Field(default=None)

    class Settings:
        name = "class_session_plans"
        indexes = [
            IndexModel(
                [
                    ("organization_id", 1),
                    ("teacher_topic_id", 1),
                    ("class_id", 1),
                    ("sequence_number", 1),
                ]
            ),
            IndexModel(
                [("organization_id", 1), ("teacher_id", 1), ("status", 1)]
            ),
            IndexModel(
                [
                    ("teacher_topic_id", 1),
                    ("class_id", 1),
                    ("sequence_number", 1),
                ],
                name="uq_topic_class_sequence",
                unique=True,
                partialFilterExpression={
                    "plan_scope": "teacher",
                    "status": "published",
                    "deleted_at": None,
                },
            ),
            IndexModel(
                [("catalog_topic_id", 1), ("sequence_number", 1)],
                name="uq_catalog_topic_sequence",
                unique=True,
                partialFilterExpression={
                    "plan_scope": "catalog",
                    "status": "published",
                    "deleted_at": None,
                },
            ),
        ]
