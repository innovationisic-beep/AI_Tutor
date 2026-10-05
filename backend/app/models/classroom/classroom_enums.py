"""Enums for classroom planning (Phase 3A)."""

from typing import Literal

ClassSessionPlanStatus = Literal["draft", "published", "archived"]
ClassSessionInstanceStatus = Literal["scheduled", "live", "completed", "cancelled"]
ClassSessionPlanItemType = Literal[
    "zone_coverage",
    "cluster_coverage",
    "concept_coverage",
    "non_curriculum",
]
EnrollmentStatus = Literal["enrolled", "excused", "withdrawn"]
