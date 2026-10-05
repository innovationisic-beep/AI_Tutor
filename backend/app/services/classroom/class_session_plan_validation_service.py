from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from beanie.odm.fields import PydanticObjectId

from app.models.classroom.class_session_plan import ClassSessionPlan, ClassSessionPlanItem
from app.models.curriculum.curriculum_cluster import CurriculumCluster
from app.models.curriculum.curriculum_concept import CurriculumConcept
from app.models.curriculum.curriculum_zone import CurriculumZone
from app.models.teacher_topic import TeacherTopic
from app.repositories.class_session_plan_repository import ClassSessionPlanRepository
from app.repositories.curriculum_cluster_repository import CurriculumClusterRepository
from app.repositories.curriculum_concept_repository import CurriculumConceptRepository
from app.repositories.curriculum_zone_repository import CurriculumZoneRepository
from app.services.curriculum.topic_context_service import TopicContext


@dataclass
class ValidationIssue:
    code: str
    message: str
    path: str = ""


@dataclass
class PlanValidationResult:
    errors: List[ValidationIssue] = field(default_factory=list)
    warnings: List[ValidationIssue] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)

    @property
    def ready_to_publish(self) -> bool:
        return len(self.errors) == 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "errors": [
                {"code": e.code, "message": e.message, "path": e.path}
                for e in self.errors
            ],
            "warnings": [
                {"code": w.code, "message": w.message, "path": w.path}
                for w in self.warnings
            ],
            "summary": self.summary,
            "ready_to_publish": self.ready_to_publish,
        }


def _curriculum_items(items: List[ClassSessionPlanItem]) -> List[ClassSessionPlanItem]:
    return [i for i in items if i.item_type != "non_curriculum"]


class ClassSessionPlanValidationService:
    def __init__(
        self,
        plan_repo: ClassSessionPlanRepository | None = None,
        zone_repo: CurriculumZoneRepository | None = None,
        cluster_repo: CurriculumClusterRepository | None = None,
        concept_repo: CurriculumConceptRepository | None = None,
    ) -> None:
        self._plans = plan_repo or ClassSessionPlanRepository()
        self._zones = zone_repo or CurriculumZoneRepository()
        self._clusters = cluster_repo or CurriculumClusterRepository()
        self._concepts = concept_repo or CurriculumConceptRepository()

    async def validate_plan(
        self,
        plan: ClassSessionPlan,
        ctx: TopicContext,
        *,
        teacher_topic: Optional[TeacherTopic] = None,
    ) -> PlanValidationResult:
        result = PlanValidationResult()

        if ctx.curriculum_schema_version != "v2":
            result.errors.append(
                ValidationIssue(
                    "V2_REQUIRED",
                    "Classroom planning requires curriculum_schema_version v2",
                )
            )
        if not ctx.supports_class_sessions:
            result.errors.append(
                ValidationIssue(
                    "CLASS_SESSIONS_DISABLED",
                    "supports_class_sessions must be enabled on the topic",
                )
            )
        if plan.plan_scope == "teacher":
            tt = teacher_topic or (
                await TeacherTopic.get(plan.teacher_topic_id)
                if plan.teacher_topic_id is not None
                else None
            )
            if tt is None or plan.teacher_topic_id is None or str(tt.id) != str(plan.teacher_topic_id):
                result.errors.append(
                    ValidationIssue("TOPIC_NOT_FOUND", "Teacher topic not found")
                )
                return result
        elif plan.plan_scope == "catalog":
            if plan.catalog_topic_id is None:
                result.errors.append(
                    ValidationIssue("TOPIC_NOT_FOUND", "Catalog topic not found")
                )
                return result

        curriculum_items = sorted(_curriculum_items(plan.items), key=lambda x: x.sort_order)
        if not curriculum_items:
            result.errors.append(
                ValidationIssue("EMPTY_PLAN", "Plan must include at least one curriculum item")
            )

        zones = await self._zones.list_by_topic(
            ctx.topic_id,
            ctx.topic_source,
            organization_id=ctx.organization_id,
        )
        zone_by_id = {z.id: z for z in zones}
        clusters = await self._clusters.list_by_topic(
            ctx.topic_id,
            ctx.topic_source,
            organization_id=ctx.organization_id,
            zone_ids=[z.id for z in zones],
        )
        cluster_by_id = {c.id: c for c in clusters}
        concepts = await self._concepts.list_by_topic(
            ctx.topic_id,
            ctx.topic_source,
            organization_id=ctx.organization_id,
            cluster_ids=[c.id for c in clusters],
        )
        concept_by_id = {c.id: c for c in concepts}

        prev_zone: Optional[int] = None
        max_zone_in_plan: Optional[int] = None
        min_zone_in_plan: Optional[int] = None
        zones_in_plan: Set[int] = set()

        for idx, item in enumerate(curriculum_items):
            path = f"items[{idx}]"

            if item.item_type == "zone_coverage":
                if item.curriculum_zone_id is None:
                    result.errors.append(
                        ValidationIssue(
                            "ZONE_REQUIRED",
                            "zone_coverage items require curriculum_zone_id",
                            path,
                        )
                    )
                    continue
                zone = zone_by_id.get(item.curriculum_zone_id)
                if zone is None:
                    result.errors.append(
                        ValidationIssue(
                            "INVALID_CURRICULUM_REF",
                            "curriculum_zone_id not found on this topic",
                            path,
                        )
                    )
                    continue
                if zone.zone_number != 0:
                    result.errors.append(
                        ValidationIssue(
                            "ZONE_COVERAGE_ZONE_0_ONLY",
                            "zone_coverage is only valid for Curriculum Zone 0",
                            path,
                        )
                    )
                zn = int(zone.zone_number)
                zones_in_plan.add(zn)
                min_zone_in_plan = (
                    zn if min_zone_in_plan is None else min(min_zone_in_plan, zn)
                )
                max_zone_in_plan = (
                    zn if max_zone_in_plan is None else max(max_zone_in_plan, zn)
                )
                if item.zone_number is not None and item.zone_number != zn:
                    result.errors.append(
                        ValidationIssue(
                            "ZONE_NUMBER_MISMATCH",
                            "item.zone_number does not match curriculum zone",
                            path,
                        )
                    )
                if prev_zone is not None:
                    if zn < prev_zone:
                        result.errors.append(
                            ValidationIssue(
                                "ZONE_REGRESSION",
                                "Zone order must not decrease within a plan",
                                path,
                            )
                        )
                    elif zn > prev_zone + 1:
                        result.errors.append(
                            ValidationIssue(
                                "ZONE_SKIP",
                                f"Cannot skip from zone {prev_zone} to zone {zn}; zones must progress sequentially",
                                path,
                            )
                        )
                prev_zone = zn
                continue

            if item.curriculum_zone_id is None or item.curriculum_cluster_id is None:
                result.errors.append(
                    ValidationIssue(
                        "ZONE_CLUSTER_REQUIRED",
                        "Curriculum items require curriculum_zone_id and curriculum_cluster_id",
                        path,
                    )
                )
                continue

            zone = zone_by_id.get(item.curriculum_zone_id)
            if zone is None:
                result.errors.append(
                    ValidationIssue(
                        "INVALID_CURRICULUM_REF",
                        "curriculum_zone_id not found on this topic",
                        path,
                    )
                )
                continue

            cluster = cluster_by_id.get(item.curriculum_cluster_id)
            if cluster is None:
                result.errors.append(
                    ValidationIssue(
                        "INVALID_CURRICULUM_REF",
                        "curriculum_cluster_id not found on this topic",
                        path,
                    )
                )
                continue

            if cluster.curriculum_zone_id != zone.id:
                result.errors.append(
                    ValidationIssue(
                        "CLUSTER_ZONE_MISMATCH",
                        "Cluster does not belong to the specified zone",
                        path,
                    )
                )

            zn = int(zone.zone_number)
            zones_in_plan.add(zn)
            min_zone_in_plan = zn if min_zone_in_plan is None else min(min_zone_in_plan, zn)
            max_zone_in_plan = zn if max_zone_in_plan is None else max(max_zone_in_plan, zn)

            if item.zone_number is not None and item.zone_number != zn:
                result.errors.append(
                    ValidationIssue(
                        "ZONE_NUMBER_MISMATCH",
                        "item.zone_number does not match curriculum zone",
                        path,
                    )
                )

            if prev_zone is not None:
                if zn < prev_zone:
                    result.errors.append(
                        ValidationIssue(
                            "ZONE_REGRESSION",
                            "Zone order must not decrease within a plan (system controls zone progression)",
                            path,
                        )
                    )
                elif zn > prev_zone + 1:
                    result.errors.append(
                        ValidationIssue(
                            "ZONE_SKIP",
                            f"Cannot skip from zone {prev_zone} to zone {zn}; zones must progress sequentially",
                            path,
                        )
                    )
            prev_zone = zn

            if item.item_type == "concept_coverage":
                if item.curriculum_concept_id is None:
                    result.errors.append(
                        ValidationIssue(
                            "CONCEPT_REQUIRED",
                            "concept_coverage items require curriculum_concept_id",
                            path,
                        )
                    )
                else:
                    concept = concept_by_id.get(item.curriculum_concept_id)
                    if concept is None:
                        result.errors.append(
                            ValidationIssue(
                                "INVALID_CURRICULUM_REF",
                                "curriculum_concept_id not found on this topic",
                                path,
                            )
                        )
                    elif concept.curriculum_cluster_id != cluster.id:
                        result.errors.append(
                            ValidationIssue(
                                "CONCEPT_CLUSTER_MISMATCH",
                                "Concept does not belong to the specified cluster",
                                path,
                            )
                        )

        await self._validate_cross_plan_sequence(plan, result, min_zone_in_plan)

        result.summary = {
            "curriculum_item_count": len(curriculum_items),
            "zones_in_plan": sorted(zones_in_plan),
            "min_zone": min_zone_in_plan,
            "max_zone": max_zone_in_plan,
        }
        return result

    async def _validate_cross_plan_sequence(
        self,
        plan: ClassSessionPlan,
        result: PlanValidationResult,
        min_zone_in_plan: Optional[int],
    ) -> None:
        if min_zone_in_plan is None or min_zone_in_plan == 0:
            return

        if plan.plan_scope == "catalog" and plan.catalog_topic_id is not None:
            prior = await self._plans.list_published_catalog_before_sequence(
                catalog_topic_id=plan.catalog_topic_id,
                sequence_number=plan.sequence_number,
            )
            dup_filter = {
                "plan_scope": "catalog",
                "catalog_topic_id": plan.catalog_topic_id,
                "sequence_number": plan.sequence_number,
                "status": "published",
                "deleted_at": None,
                "_id": {"$ne": plan.id},
            }
        else:
            if plan.teacher_topic_id is None:
                return
            prior = await self._plans.list_published_before_sequence(
                teacher_topic_id=plan.teacher_topic_id,
                class_id=plan.class_id,
                sequence_number=plan.sequence_number,
            )
            dup_filter = {
                "plan_scope": "teacher",
                "teacher_topic_id": plan.teacher_topic_id,
                "class_id": plan.class_id,
                "sequence_number": plan.sequence_number,
                "status": "published",
                "deleted_at": None,
                "_id": {"$ne": plan.id},
            }

        prior_zones: Set[int] = set()
        for p in prior:
            for item in _curriculum_items(p.items):
                if item.zone_number is not None:
                    prior_zones.add(int(item.zone_number))

        for z in range(0, min_zone_in_plan):
            if z not in prior_zones:
                result.errors.append(
                    ValidationIssue(
                        "ZONE_SKIP",
                        f"Zone {z} must be covered in a prior published plan before zone {min_zone_in_plan} can begin",
                        "sequence_number",
                    )
                )

        dup = await ClassSessionPlan.find_one(dup_filter)
        if dup is not None:
            result.errors.append(
                ValidationIssue(
                    "DUPLICATE_SEQUENCE",
                    f"Published plan with sequence_number {plan.sequence_number} already exists",
                    "sequence_number",
                )
            )
