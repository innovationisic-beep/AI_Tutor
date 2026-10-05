"""Resolve planning snapshots into RuntimeCurriculumManifest."""

from __future__ import annotations

from typing import List, Optional

from beanie.odm.fields import PydanticObjectId

from app.models.classroom.class_session_instance import ClassSessionInstance
from app.models.classroom.class_session_plan import ClassSessionPlan, ClassSessionPlanItem
from app.models.runtime.runtime_curriculum_manifest import (
    LaunchContext,
    RuntimeCurriculumManifest,
)
from app.models.teacher_topic import TeacherTopic
from app.repositories.curriculum_cluster_repository import CurriculumClusterRepository
from app.repositories.curriculum_concept_repository import CurriculumConceptRepository
from app.repositories.curriculum_zone_repository import CurriculumZoneRepository
from app.services.curriculum.curriculum_validators import normalize_runtime_key
from app.services.curriculum.topic_context_service import TopicContext


class CurriculumResolutionError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


class CurriculumResolutionService:
    def __init__(
        self,
        *,
        zone_repo: CurriculumZoneRepository | None = None,
        cluster_repo: CurriculumClusterRepository | None = None,
        concept_repo: CurriculumConceptRepository | None = None,
    ) -> None:
        self._zones = zone_repo or CurriculumZoneRepository()
        self._clusters = cluster_repo or CurriculumClusterRepository()
        self._concepts = concept_repo or CurriculumConceptRepository()

    async def resolve_published_topic_v2(
        self,
        ctx: TopicContext,
    ) -> RuntimeCurriculumManifest:
        if ctx.curriculum_schema_version != "v2":
            raise CurriculumResolutionError(
                "V2_REQUIRED",
                "Published topic resolution requires curriculum_schema_version v2",
            )
        if ctx.curriculum_published_at is None:
            raise CurriculumResolutionError(
                "NOT_PUBLISHED",
                "Topic curriculum is not published",
            )

        zones = await self._zones.list_by_topic(
            ctx.topic_id,
            ctx.topic_source,
            organization_id=ctx.organization_id,
        )
        zone_ids = [z.id for z in zones]
        clusters = await self._clusters.list_by_topic(
            ctx.topic_id,
            ctx.topic_source,
            organization_id=ctx.organization_id,
            zone_ids=zone_ids if zone_ids else [],
        )
        cluster_ids = [c.id for c in clusters]
        concepts = await self._concepts.list_by_topic(
            ctx.topic_id,
            ctx.topic_source,
            organization_id=ctx.organization_id,
            cluster_ids=cluster_ids if cluster_ids else [],
        )

        zone_by_id = {z.id: z for z in zones}
        clusters_by_zone: dict[PydanticObjectId, list] = {}
        for cl in clusters:
            if cl.status != "published" or cl.deleted_at is not None:
                continue
            zone = zone_by_id.get(cl.curriculum_zone_id)
            if zone is None or zone.zone_number == 0:
                continue
            clusters_by_zone.setdefault(cl.curriculum_zone_id, []).append(cl)

        concepts_by_cluster: dict[PydanticObjectId, list] = {}
        for concept in concepts:
            if concept.status != "published" or concept.deleted_at is not None:
                continue
            concepts_by_cluster.setdefault(concept.curriculum_cluster_id, []).append(
                concept
            )

        key_concepts: List[str] = []
        concept_clusters: List[List[str]] = []
        concept_ids_ordered: List[PydanticObjectId] = []
        seen_keys: set[str] = set()

        for zone in sorted(zones, key=lambda z: z.zone_number):
            if zone.zone_number == 0 or zone.status != "published":
                continue
            zone_clusters = sorted(
                clusters_by_zone.get(zone.id, []),
                key=lambda c: c.sort_order,
            )
            for cluster in zone_clusters:
                group: List[str] = []
                cluster_concepts = sorted(
                    concepts_by_cluster.get(cluster.id, []),
                    key=lambda c: c.sort_order,
                )
                for concept in cluster_concepts:
                    key = normalize_runtime_key(concept.canonical_runtime_key)
                    group.append(key)
                    if key not in seen_keys:
                        seen_keys.add(key)
                        key_concepts.append(key)
                        concept_ids_ordered.append(concept.id)
                if group:
                    concept_clusters.append(group)

        if not key_concepts:
            raise CurriculumResolutionError(
                "EMPTY_CURRICULUM",
                "No published curriculum concepts found for runtime",
            )

        launch_context = LaunchContext(
            launch_kind="personal",
            resolution_mode="published_topic_v2",
            curriculum_schema_version="v2",
            curriculum_revision=int(ctx.curriculum_revision),
            source_topic_id=ctx.topic_id,
            topic_source=ctx.topic_source,
        )
        return RuntimeCurriculumManifest(
            key_concepts=key_concepts,
            concept_clusters=concept_clusters or None,
            concept_ids_ordered=concept_ids_ordered,
            launch_context=launch_context,
        )

    def resolve_catalog_session_plan(
        self,
        plan: ClassSessionPlan,
        *,
        materialized_items: Optional[List[ClassSessionPlanItem]] = None,
    ) -> RuntimeCurriculumManifest:
        if plan.plan_scope != "catalog" or plan.catalog_topic_id is None:
            raise CurriculumResolutionError(
                "INVALID_PLAN_SCOPE",
                "Plan is not a catalog session plan",
            )
        if plan.status != "published":
            raise CurriculumResolutionError(
                "PLAN_NOT_PUBLISHED",
                "Catalog session plan must be published",
            )

        items = sorted(
            materialized_items if materialized_items is not None else plan.items,
            key=lambda row: row.sort_order,
        )

        key_concepts: List[str] = []
        concept_ids_ordered: List[PydanticObjectId] = []
        concept_clusters: List[List[str]] = []
        cluster_index_by_id: dict[PydanticObjectId, int] = {}
        seen_keys: set[str] = set()

        for item in items:
            self._resolve_item_into_manifest(
                item,
                key_concepts=key_concepts,
                concept_ids_ordered=concept_ids_ordered,
                concept_clusters=concept_clusters,
                cluster_index_by_id=cluster_index_by_id,
                seen_keys=seen_keys,
            )

        if not key_concepts:
            raise CurriculumResolutionError(
                "EMPTY_SESSION_SCOPE",
                "No curriculum keys resolved from catalog session plan",
            )

        launch_context = LaunchContext(
            launch_kind="personal",
            resolution_mode="catalog_session_plan",
            curriculum_schema_version="v2",
            curriculum_revision=int(plan.curriculum_revision),
            source_topic_id=plan.catalog_topic_id,
            topic_source="catalog",
            class_session_plan_id=plan.id,
        )
        return RuntimeCurriculumManifest(
            key_concepts=key_concepts,
            concept_clusters=concept_clusters or None,
            concept_ids_ordered=concept_ids_ordered,
            launch_context=launch_context,
        )

    def resolve_class_session(
        self,
        instance: ClassSessionInstance,
        *,
        item_id: Optional[str] = None,
    ) -> RuntimeCurriculumManifest:
        if instance.status not in ("scheduled", "live"):
            raise CurriculumResolutionError(
                "INSTANCE_NOT_LAUNCHABLE",
                f"Instance status {instance.status} cannot be launched",
            )

        items = sorted(
            instance.plan_snapshot.items,
            key=lambda row: row.sort_order,
        )
        if item_id is not None:
            items = [i for i in items if i.item_id == item_id]
            if not items:
                raise CurriculumResolutionError(
                    "PLAN_ITEM_NOT_FOUND",
                    "Plan item not found in snapshot",
                )
            mode = "class_session_item"
        else:
            mode = "class_session_full"

        key_concepts: List[str] = []
        concept_ids_ordered: List[PydanticObjectId] = []
        concept_clusters: List[List[str]] = []
        cluster_index_by_id: dict[PydanticObjectId, int] = {}
        seen_keys: set[str] = set()

        for item in items:
            self._resolve_item_into_manifest(
                item,
                key_concepts=key_concepts,
                concept_ids_ordered=concept_ids_ordered,
                concept_clusters=concept_clusters,
                cluster_index_by_id=cluster_index_by_id,
                seen_keys=seen_keys,
            )

        if not key_concepts:
            raise CurriculumResolutionError(
                "EMPTY_SESSION_SCOPE",
                "No curriculum keys resolved from snapshot",
            )

        launch_context = LaunchContext(
            launch_kind="classroom",
            resolution_mode=mode,
            curriculum_schema_version="v2",
            curriculum_revision=int(instance.plan_snapshot.curriculum_revision),
            source_topic_id=instance.teacher_topic_id,
            topic_source="teacher",
            class_session_instance_id=instance.id,
            class_session_plan_id=instance.plan_snapshot.plan_id,
            plan_item_id=item_id,
            class_id=instance.class_id,
            subject_id=instance.subject_id,
        )
        return RuntimeCurriculumManifest(
            key_concepts=key_concepts,
            concept_clusters=concept_clusters or None,
            concept_ids_ordered=concept_ids_ordered,
            launch_context=launch_context,
        )

    def resolve_legacy_v1(self, teacher_topic: TeacherTopic) -> RuntimeCurriculumManifest:
        kc_raw = [
            str(c).strip()
            for c in (teacher_topic.key_concepts or [])
            if c is not None and str(c).strip()
        ]
        key_concepts = (
            [normalize_runtime_key(c) for c in kc_raw]
            if kc_raw
            else [normalize_runtime_key("introduction")]
        )
        clusters = teacher_topic.concept_clusters
        launch_context = LaunchContext(
            launch_kind="personal",
            resolution_mode="legacy_v1",
            curriculum_schema_version="v1",
            curriculum_revision=int(teacher_topic.curriculum_revision or 0),
            source_topic_id=teacher_topic.id,
            topic_source="teacher",
            class_id=teacher_topic.class_id,
            subject_id=teacher_topic.subject_id,
        )
        return RuntimeCurriculumManifest(
            key_concepts=key_concepts,
            concept_clusters=clusters,
            concept_ids_ordered=[],
            launch_context=launch_context,
        )

    def _resolve_item_into_manifest(
        self,
        item: ClassSessionPlanItem,
        *,
        key_concepts: List[str],
        concept_ids_ordered: List[PydanticObjectId],
        concept_clusters: List[List[str]],
        cluster_index_by_id: dict[PydanticObjectId, int],
        seen_keys: set[str],
    ) -> None:
        if item.item_type == "zone_coverage":
            return

        if item.item_type == "non_curriculum":
            return

        if item.item_type == "cluster_coverage":
            keys = item.resolved_runtime_keys or []
            ids = item.resolved_concept_ids or []
            if not keys:
                raise CurriculumResolutionError(
                    "SNAPSHOT_NOT_MATERIALIZED",
                    "cluster_coverage item missing resolved_runtime_keys",
                )
            cluster_group: List[str] = []
            for idx, raw in enumerate(keys):
                key = normalize_runtime_key(raw)
                cluster_group.append(key)
                if key not in seen_keys:
                    seen_keys.add(key)
                    key_concepts.append(key)
                    if idx < len(ids):
                        concept_ids_ordered.append(ids[idx])
            concept_clusters.append(cluster_group)
            if item.curriculum_cluster_id is not None:
                cluster_index_by_id[item.curriculum_cluster_id] = (
                    len(concept_clusters) - 1
                )
            return

        if item.item_type == "concept_coverage":
            if not item.resolved_runtime_keys:
                if item.canonical_runtime_key_snapshot:
                    keys = [normalize_runtime_key(item.canonical_runtime_key_snapshot)]
                    ids = (
                        [item.curriculum_concept_id]
                        if item.curriculum_concept_id is not None
                        else []
                    )
                else:
                    raise CurriculumResolutionError(
                        "SNAPSHOT_NOT_MATERIALIZED",
                        "concept_coverage item missing runtime key snapshot",
                    )
            else:
                keys = [normalize_runtime_key(k) for k in item.resolved_runtime_keys]
                ids = list(item.resolved_concept_ids or [])

            for idx, key in enumerate(keys):
                if key not in seen_keys:
                    seen_keys.add(key)
                    key_concepts.append(key)
                    if idx < len(ids) and ids[idx] is not None:
                        concept_ids_ordered.append(ids[idx])

            cluster_id = item.curriculum_cluster_id
            if cluster_id is not None and cluster_id in cluster_index_by_id:
                group = concept_clusters[cluster_index_by_id[cluster_id]]
                for key in keys:
                    if key not in group:
                        group.append(key)
            else:
                concept_clusters.append(list(keys))
                if cluster_id is not None:
                    cluster_index_by_id[cluster_id] = len(concept_clusters) - 1
