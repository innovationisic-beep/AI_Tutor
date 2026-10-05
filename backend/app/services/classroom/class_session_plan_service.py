from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from beanie.odm.fields import PydanticObjectId
from fastapi import HTTPException, status

from app.models.classroom.class_session_plan import ClassSessionPlan, ClassSessionPlanItem
from app.models.curriculum.curriculum_cluster import CurriculumCluster
from app.models.curriculum.curriculum_concept import CurriculumConcept
from app.models.curriculum.curriculum_zone import CurriculumZone
from app.models.identification.users import User
from app.models.teacher_topic import TeacherTopic
from app.models.curriculum.topics import Topic
from app.repositories.class_session_plan_repository import ClassSessionPlanRepository
from app.repositories.curriculum_cluster_repository import CurriculumClusterRepository
from app.repositories.curriculum_concept_repository import CurriculumConceptRepository
from app.repositories.curriculum_zone_repository import CurriculumZoneRepository
from app.services.classroom.class_session_plan_validation_service import (
    ClassSessionPlanValidationService,
)
from app.services.curriculum.topic_context_service import TopicContext, resolve_topic_context
from app.services.runtime.snapshot_materialization_service import (
    SnapshotMaterializationService,
)


class ClassSessionPlanService:
    def __init__(
        self,
        plan_repo: ClassSessionPlanRepository | None = None,
        validation: ClassSessionPlanValidationService | None = None,
        zone_repo: CurriculumZoneRepository | None = None,
        cluster_repo: CurriculumClusterRepository | None = None,
        concept_repo: CurriculumConceptRepository | None = None,
        materialization: SnapshotMaterializationService | None = None,
    ) -> None:
        self._plans = plan_repo or ClassSessionPlanRepository()
        self._validation = validation or ClassSessionPlanValidationService()
        self._zones = zone_repo or CurriculumZoneRepository()
        self._clusters = cluster_repo or CurriculumClusterRepository()
        self._concepts = concept_repo or CurriculumConceptRepository()
        self._materialization = materialization or SnapshotMaterializationService()

    async def _ctx_for_catalog_topic(
        self, catalog_topic_id: PydanticObjectId, user: User
    ) -> tuple[TopicContext, Topic]:
        topic = await Topic.get(catalog_topic_id)
        if topic is None:
            raise HTTPException(status_code=404, detail="Catalog topic not found")
        ctx = await resolve_topic_context(catalog_topic_id, "catalog", user)
        return ctx, topic

    async def _ctx_for_plan(
        self, plan: ClassSessionPlan, user: User
    ) -> TopicContext:
        if plan.plan_scope == "catalog":
            if plan.catalog_topic_id is None:
                raise HTTPException(status_code=400, detail="Catalog plan missing topic")
            ctx, _ = await self._ctx_for_catalog_topic(plan.catalog_topic_id, user)
            return ctx
        if plan.teacher_topic_id is None:
            raise HTTPException(status_code=400, detail="Teacher plan missing topic")
        ctx, _ = await self._ctx_for_teacher_topic(plan.teacher_topic_id, user)
        return ctx

    async def _ctx_for_teacher_topic(
        self, teacher_topic_id: PydanticObjectId, user: User
    ) -> tuple[TopicContext, TeacherTopic]:
        tt = await TeacherTopic.get(teacher_topic_id)
        if tt is None:
            raise HTTPException(status_code=404, detail="Teacher topic not found")
        ctx = await resolve_topic_context(tt.id, "teacher", user)
        return ctx, tt

    async def _get_plan_for_user(
        self, plan_id: PydanticObjectId, user: User
    ) -> ClassSessionPlan:
        plan = await self._plans.get_by_id(plan_id)
        if plan is None or plan.deleted_at is not None:
            raise HTTPException(status_code=404, detail="Plan not found")
        if plan.plan_scope == "catalog":
            if user.role != "admin":
                raise HTTPException(status_code=403, detail="Admin access required")
            return plan
        if user.organization_id is None or plan.organization_id != user.organization_id:
            raise HTTPException(status_code=403, detail="Plan not in your organization")
        if user.role == "teacher" and plan.teacher_id != user.id:
            raise HTTPException(status_code=403, detail="Not your plan")
        return plan

    async def create_draft(
        self,
        user: User,
        *,
        teacher_topic_id: PydanticObjectId,
        class_id: str,
        subject_id: str,
        sequence_number: int,
        title: str,
        description: str = "",
        target_duration_minutes: Optional[int] = None,
        teacher_notes: str = "",
    ) -> ClassSessionPlan:
        ctx, tt = await self._ctx_for_teacher_topic(teacher_topic_id, user)
        if ctx.curriculum_schema_version != "v2":
            raise HTTPException(
                status_code=400,
                detail="Classroom planning requires a v2 structured curriculum topic",
            )
        if not ctx.supports_class_sessions:
            raise HTTPException(
                status_code=400,
                detail="supports_class_sessions is not enabled for this topic",
            )
        return await self._plans.create(
            {
                "plan_scope": "teacher",
                "organization_id": tt.organization_id,
                "teacher_id": user.id,
                "teacher_topic_id": tt.id,
                "class_id": class_id.strip(),
                "subject_id": subject_id.strip(),
                "sequence_number": sequence_number,
                "title": title.strip(),
                "description": description.strip(),
                "target_duration_minutes": target_duration_minutes,
                "teacher_notes": teacher_notes.strip(),
                "curriculum_schema_version": ctx.curriculum_schema_version,
                "curriculum_revision": int(ctx.curriculum_revision or 0),
                "items": [],
                "status": "draft",
            }
        )

    async def update_draft(
        self,
        plan_id: PydanticObjectId,
        user: User,
        *,
        title: Optional[str] = None,
        description: Optional[str] = None,
        session_study_points: Optional[List[str]] = None,
        session_learning_outcomes: Optional[List[str]] = None,
        sequence_number: Optional[int] = None,
        target_duration_minutes: Optional[int] = None,
        teacher_notes: Optional[str] = None,
    ) -> ClassSessionPlan:
        plan = await self._get_plan_for_user(plan_id, user)
        if plan.status != "draft":
            raise HTTPException(
                status_code=409,
                detail="Only draft plans can be edited",
            )
        if title is not None:
            plan.title = title.strip()
        if description is not None:
            plan.description = description.strip()
        if session_study_points is not None:
            plan.session_study_points = [
                str(s).strip() for s in session_study_points if str(s).strip()
            ]
        if session_learning_outcomes is not None:
            plan.session_learning_outcomes = [
                str(s).strip() for s in session_learning_outcomes if str(s).strip()
            ]
        if sequence_number is not None:
            plan.sequence_number = sequence_number
        if target_duration_minutes is not None:
            plan.target_duration_minutes = target_duration_minutes
        if teacher_notes is not None:
            plan.teacher_notes = teacher_notes.strip()
        await plan.save()
        return plan

    async def _hydrate_item(
        self,
        item: ClassSessionPlanItem,
        ctx: TopicContext,
    ) -> ClassSessionPlanItem:
        if item.item_type == "non_curriculum":
            return item
        if item.item_type == "zone_coverage":
            if item.curriculum_zone_id is None:
                raise HTTPException(status_code=400, detail="curriculum_zone_id required")
            zone = await self._zones.get_by_id(item.curriculum_zone_id)
            if zone is None or zone.deleted_at is not None:
                raise HTTPException(status_code=400, detail="Invalid curriculum_zone_id")
            if str(zone.topic_id) != str(ctx.topic_id):
                raise HTTPException(status_code=400, detail="Zone does not belong to topic")
            if int(zone.zone_number) != 0:
                raise HTTPException(
                    status_code=400,
                    detail="zone_coverage is only valid for Curriculum Zone 0",
                )
            return item.model_copy(
                update={
                    "zone_number": 0,
                    "display_name_snapshot": item.display_name_snapshot or zone.title,
                }
            )
        if item.curriculum_zone_id is None or item.curriculum_cluster_id is None:
            raise HTTPException(
                status_code=400,
                detail="curriculum_zone_id and curriculum_cluster_id are required",
            )
        zone = await self._zones.get_by_id(item.curriculum_zone_id)
        if zone is None or zone.deleted_at is not None:
            raise HTTPException(status_code=400, detail="Invalid curriculum_zone_id")
        cluster = await self._clusters.get_by_id(item.curriculum_cluster_id)
        if cluster is None or cluster.deleted_at is not None:
            raise HTTPException(status_code=400, detail="Invalid curriculum_cluster_id")
        if cluster.curriculum_zone_id != zone.id:
            raise HTTPException(status_code=400, detail="Cluster does not belong to zone")
        if str(zone.topic_id) != str(ctx.topic_id):
            raise HTTPException(status_code=400, detail="Zone does not belong to topic")

        data = item.model_copy(
            update={
                "zone_number": int(zone.zone_number),
                "display_name_snapshot": item.display_name_snapshot
                or (
                    cluster.title
                    if item.item_type == "cluster_coverage"
                    else None
                ),
            }
        )
        if item.item_type == "concept_coverage":
            if item.curriculum_concept_id is None:
                raise HTTPException(status_code=400, detail="curriculum_concept_id required")
            concept = await self._concepts.get_by_id(item.curriculum_concept_id)
            if concept is None or concept.deleted_at is not None:
                raise HTTPException(status_code=400, detail="Invalid curriculum_concept_id")
            if concept.curriculum_cluster_id != cluster.id:
                raise HTTPException(status_code=400, detail="Concept does not belong to cluster")
            data = data.model_copy(
                update={
                    "display_name_snapshot": concept.display_name,
                    "canonical_runtime_key_snapshot": concept.canonical_runtime_key,
                }
            )
        elif data.display_name_snapshot is None:
            data = data.model_copy(update={"display_name_snapshot": cluster.title})
        return data

    async def set_items(
        self,
        plan_id: PydanticObjectId,
        user: User,
        items: List[ClassSessionPlanItem],
    ) -> ClassSessionPlan:
        plan = await self._get_plan_for_user(plan_id, user)
        if plan.status != "draft":
            raise HTTPException(status_code=409, detail="Only draft plans can be edited")
        ctx = await self._ctx_for_plan(plan, user)
        hydrated: List[ClassSessionPlanItem] = []
        for i, raw in enumerate(items):
            row = raw.model_copy(update={"sort_order": i})
            hydrated.append(await self._hydrate_item(row, ctx))
        plan.items = hydrated
        await plan.save()
        return plan

    async def create_catalog_draft(
        self,
        user: User,
        *,
        catalog_topic_id: PydanticObjectId,
        sequence_number: int,
        title: str,
        description: str = "",
        target_duration_minutes: Optional[int] = None,
        teacher_notes: str = "",
    ) -> ClassSessionPlan:
        if user.role != "admin":
            raise HTTPException(status_code=403, detail="Admin access required")
        ctx, topic = await self._ctx_for_catalog_topic(catalog_topic_id, user)
        if ctx.curriculum_schema_version != "v2":
            raise HTTPException(
                status_code=400,
                detail="Catalog planning requires a v2 structured curriculum topic",
            )
        if not ctx.supports_class_sessions:
            raise HTTPException(
                status_code=400,
                detail="supports_class_sessions is not enabled for this topic",
            )
        return await self._plans.create(
            {
                "plan_scope": "catalog",
                "organization_id": None,
                "teacher_id": user.id,
                "catalog_topic_id": topic.id,
                "class_id": "",
                "subject_id": "",
                "sequence_number": sequence_number,
                "title": title.strip(),
                "description": description.strip(),
                "target_duration_minutes": target_duration_minutes,
                "teacher_notes": teacher_notes.strip(),
                "curriculum_schema_version": ctx.curriculum_schema_version,
                "curriculum_revision": int(ctx.curriculum_revision or 0),
                "items": [],
                "status": "draft",
            }
        )

    async def list_catalog_plans(
        self,
        user: User,
        *,
        catalog_topic_id: PydanticObjectId,
        status: Optional[str] = None,
    ) -> List[ClassSessionPlan]:
        if user.role != "admin":
            raise HTTPException(status_code=403, detail="Admin access required")
        await self._ctx_for_catalog_topic(catalog_topic_id, user)
        return await self._plans.list_for_catalog_topic(
            catalog_topic_id=catalog_topic_id,
            status=status,
        )

    async def list_published_catalog_plans_for_students(
        self,
        *,
        catalog_topic_id: PydanticObjectId,
    ) -> List[ClassSessionPlan]:
        return await self._plans.list_for_catalog_topic(
            catalog_topic_id=catalog_topic_id,
            status="published",
        )

    async def get_published_catalog_plan(
        self,
        plan_id: PydanticObjectId,
        *,
        catalog_topic_id: PydanticObjectId,
    ) -> ClassSessionPlan:
        plan = await self._plans.get_by_id(plan_id)
        if plan is None or plan.deleted_at is not None:
            raise HTTPException(status_code=404, detail="Plan not found")
        if plan.plan_scope != "catalog" or plan.catalog_topic_id != catalog_topic_id:
            raise HTTPException(status_code=404, detail="Plan not found")
        if plan.status != "published":
            raise HTTPException(status_code=400, detail="PLAN_NOT_PUBLISHED")
        return plan

    async def validate(self, plan_id: PydanticObjectId, user: User) -> Dict[str, Any]:
        plan = await self._get_plan_for_user(plan_id, user)
        ctx = await self._ctx_for_plan(plan, user)
        teacher_topic = None
        if plan.plan_scope == "teacher" and plan.teacher_topic_id is not None:
            teacher_topic = await TeacherTopic.get(plan.teacher_topic_id)
        return (
            await self._validation.validate_plan(plan, ctx, teacher_topic=teacher_topic)
        ).to_dict()

    async def publish(self, plan_id: PydanticObjectId, user: User) -> ClassSessionPlan:
        plan = await self._get_plan_for_user(plan_id, user)
        if plan.status != "draft":
            raise HTTPException(status_code=409, detail="Only draft plans can be published")
        ctx = await self._ctx_for_plan(plan, user)
        teacher_topic = None
        if plan.plan_scope == "teacher" and plan.teacher_topic_id is not None:
            teacher_topic = await TeacherTopic.get(plan.teacher_topic_id)
        result = await self._validation.validate_plan(plan, ctx, teacher_topic=teacher_topic)
        if not result.ready_to_publish:
            raise HTTPException(status_code=400, detail=result.to_dict())

        hydrated: List[ClassSessionPlanItem] = []
        for item in sorted(plan.items, key=lambda x: x.sort_order):
            hydrated.append(await self._hydrate_item(item, ctx))
        org_id = plan.organization_id if plan.plan_scope == "teacher" else None
        materialized = await self._materialization.materialize_items(
            hydrated,
            organization_id=org_id,
        )
        plan.items = materialized
        plan.curriculum_revision = int(ctx.curriculum_revision or 0)
        plan.status = "published"
        plan.published_at = datetime.utcnow()
        await plan.save()
        return plan

    async def unpublish(self, plan_id: PydanticObjectId, user: User) -> ClassSessionPlan:
        """Return a published plan to draft so teachers/admins can edit again."""
        plan = await self._get_plan_for_user(plan_id, user)
        if plan.status != "published":
            raise HTTPException(
                status_code=409,
                detail="Only published plans can be unpublished",
            )
        plan.status = "draft"
        plan.published_at = None
        await plan.save()
        return plan

    async def archive(self, plan_id: PydanticObjectId, user: User) -> ClassSessionPlan:
        plan = await self._get_plan_for_user(plan_id, user)
        await self._plans.soft_delete(plan.id)
        refreshed = await self._plans.get_by_id(plan.id)
        assert refreshed is not None
        return refreshed

    async def get(self, plan_id: PydanticObjectId, user: User) -> ClassSessionPlan:
        return await self._get_plan_for_user(plan_id, user)

    async def list_plans(
        self,
        user: User,
        *,
        teacher_topic_id: PydanticObjectId,
        class_id: str,
        status: Optional[str] = None,
    ) -> List[ClassSessionPlan]:
        if user.organization_id is None:
            raise HTTPException(status_code=403, detail="Organization required")
        await self._ctx_for_teacher_topic(teacher_topic_id, user)
        return await self._plans.list_for_topic_class(
            organization_id=user.organization_id,
            teacher_topic_id=teacher_topic_id,
            class_id=class_id,
            status=status,
        )
