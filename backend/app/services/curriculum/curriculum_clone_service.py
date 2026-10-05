"""Clone structured curriculum tree and linked content between topics."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence
from uuid import uuid4

from beanie.odm.fields import PydanticObjectId
from pydantic import ValidationError

from app.models.content.topic_question_bank import TopicQuestionBank
from app.models.curriculum.curriculum_enums import TopicSource
from app.models.curriculum.topics import Topic
from app.models.teacher_topic import TeacherTopic
from app.repositories.curriculum_cluster_repository import CurriculumClusterRepository
from app.repositories.curriculum_concept_repository import CurriculumConceptRepository
from app.repositories.curriculum_zone_repository import CurriculumZoneRepository
from app.services.curriculum.concept_teaching_sequence import normalize_story_hook
from app.services.curriculum.curriculum_publish_service import CurriculumPublishService
from app.services.curriculum.topic_context_service import TopicContext
from app.services.storage.story_hook_storage import get_story_hook_storage
from app.services.storage.visual_teaching_storage import get_visual_teaching_storage
from app.services.visual_teaching.authored import normalize_visual_teaching

logger = logging.getLogger(__name__)


@dataclass
class CloneStructuredCurriculumResult:
    zone_id_map: Dict[PydanticObjectId, PydanticObjectId] = field(default_factory=dict)
    cluster_id_map: Dict[PydanticObjectId, PydanticObjectId] = field(default_factory=dict)
    concept_id_map: Dict[PydanticObjectId, PydanticObjectId] = field(default_factory=dict)
    zones_copied: int = 0
    clusters_copied: int = 0
    concepts_copied: int = 0
    notes_copied: int = 0
    questions_copied: int = 0
    visuals_copied: int = 0
    metadata_synced: bool = False


class CurriculumCloneService:
    def __init__(
        self,
        zone_repo: CurriculumZoneRepository | None = None,
        cluster_repo: CurriculumClusterRepository | None = None,
        concept_repo: CurriculumConceptRepository | None = None,
    ) -> None:
        self._zones = zone_repo or CurriculumZoneRepository()
        self._clusters = cluster_repo or CurriculumClusterRepository()
        self._concepts = concept_repo or CurriculumConceptRepository()

    async def clone_structured_curriculum(
        self,
        *,
        source_topic_id: PydanticObjectId,
        source_topic_source: TopicSource,
        source_organization_id: Optional[PydanticObjectId],
        target_topic_id: PydanticObjectId,
        target_topic_source: TopicSource,
        target_organization_id: Optional[PydanticObjectId],
        copy_content: bool = True,
        note_grade: str = "General",
        note_board: str = "general",
    ) -> CloneStructuredCurriculumResult:
        """Deep-copy zones, clusters, concepts, and admin content onto a teacher topic."""
        result = CloneStructuredCurriculumResult()

        source_zones = await self._zones.list_by_topic(
            source_topic_id,
            source_topic_source,
            organization_id=source_organization_id,
        )
        source_clusters = await self._clusters.list_by_topic(
            source_topic_id,
            source_topic_source,
            organization_id=source_organization_id,
            zone_ids=[z.id for z in source_zones],
        )
        source_concepts = await self._concepts.list_by_topic(
            source_topic_id,
            source_topic_source,
            organization_id=source_organization_id,
            cluster_ids=[c.id for c in source_clusters],
        )

        # Duplicate Story Hook binaries before writing any row: the target must
        # never reference a storage_key owned by the source tenant, and a failed
        # copy must not leave a half-imported curriculum behind.
        story_hooks, visuals_copied = await self._duplicate_story_hook_visuals(
            source_concepts
        )
        result.visuals_copied = visuals_copied
        vt_pkgs, vt_copied, vt_written = await self._duplicate_visual_teaching_images(
            source_concepts
        )
        vtse_pkgs, vtse_copied, vtse_written = await self._duplicate_vtse_visuals(
            source_concepts
        )
        result.visuals_copied = visuals_copied + vt_copied + vtse_copied

        try:
            return await self._write_cloned_tree(
                result=result,
                source_zones=source_zones,
                source_clusters=source_clusters,
                source_concepts=source_concepts,
                story_hooks=story_hooks,
                vt_pkgs=vt_pkgs,
                vtse_pkgs=vtse_pkgs,
                source_topic_id=source_topic_id,
                target_topic_id=target_topic_id,
                target_topic_source=target_topic_source,
                target_organization_id=target_organization_id,
                copy_content=copy_content,
                note_grade=note_grade,
                note_board=note_board,
            )
        except Exception:
            # Visual Teaching binaries were already written; roll them back so a
            # failed clone never leaves destination orphans.
            if vt_written or vtse_written:
                storage = get_visual_teaching_storage()
                from app.services.storage.visual_teaching_storage import (
                    get_vtse_visuals_storage,
                )

                vtse_storage = get_vtse_visuals_storage()
                for key in vt_written:
                    try:
                        await storage.delete(key)
                    except Exception:  # noqa: BLE001
                        logger.warning(
                            "clone: orphaned visual teaching object %s", key
                        )
                for key in vtse_written:
                    try:
                        await vtse_storage.delete(key)
                    except Exception:  # noqa: BLE001
                        logger.warning("clone: orphaned vtse visual %s", key)
            raise

    async def _write_cloned_tree(
        self,
        *,
        result: CloneStructuredCurriculumResult,
        source_zones: Sequence[Any],
        source_clusters: Sequence[Any],
        source_concepts: Sequence[Any],
        story_hooks: Dict[PydanticObjectId, Optional[Dict[str, Any]]],
        vt_pkgs: Dict[PydanticObjectId, Optional[Dict[str, Any]]],
        vtse_pkgs: Optional[Dict[PydanticObjectId, Optional[Dict[str, Any]]]] = None,
        source_topic_id: PydanticObjectId,
        target_topic_id: PydanticObjectId,
        target_topic_source: TopicSource,
        target_organization_id: Optional[PydanticObjectId],
        copy_content: bool,
        note_grade: str,
        note_board: str,
    ) -> CloneStructuredCurriculumResult:
        zone_id_map: Dict[PydanticObjectId, PydanticObjectId] = {}
        for zone in source_zones:
            created = await self._zones.create(
                {
                    "organization_id": target_organization_id,
                    "topic_id": target_topic_id,
                    "topic_source": target_topic_source,
                    "zone_number": zone.zone_number,
                    "title": zone.title,
                    "description": zone.description,
                    "purpose": zone.purpose,
                    "allows_vtse": zone.allows_vtse,
                    "is_system_zone": zone.is_system_zone,
                    "sort_order": zone.sort_order,
                    "status": zone.status,
                }
            )
            zone_id_map[zone.id] = created.id
            result.zones_copied += 1
        result.zone_id_map = zone_id_map

        cluster_id_map: Dict[PydanticObjectId, PydanticObjectId] = {}
        for cluster in source_clusters:
            new_zone_id = zone_id_map.get(cluster.curriculum_zone_id)
            if new_zone_id is None:
                continue
            created = await self._clusters.create(
                {
                    "organization_id": target_organization_id,
                    "topic_id": target_topic_id,
                    "topic_source": target_topic_source,
                    "curriculum_zone_id": new_zone_id,
                    "cluster_number": cluster.cluster_number,
                    "title": cluster.title,
                    "description": getattr(cluster, "description", "") or "",
                    "study_points": list(getattr(cluster, "study_points", None) or []),
                    "learning_outcomes": list(
                        getattr(cluster, "learning_outcomes", None) or []
                    ),
                    "sort_order": cluster.sort_order,
                    "estimated_learning_minutes": cluster.estimated_learning_minutes,
                    "status": cluster.status,
                }
            )
            cluster_id_map[cluster.id] = created.id
            result.clusters_copied += 1
        result.cluster_id_map = cluster_id_map

        concept_id_map: Dict[PydanticObjectId, PydanticObjectId] = {}
        for concept in source_concepts:
            new_cluster_id = cluster_id_map.get(concept.curriculum_cluster_id)
            new_zone_id = zone_id_map.get(concept.curriculum_zone_id)
            if new_cluster_id is None or new_zone_id is None:
                continue
            created = await self._concepts.create(
                {
                    "organization_id": target_organization_id,
                    "topic_id": target_topic_id,
                    "topic_source": target_topic_source,
                    "curriculum_zone_id": new_zone_id,
                    "curriculum_cluster_id": new_cluster_id,
                    "slug": concept.slug,
                    "display_name": concept.display_name,
                    "canonical_runtime_key": concept.canonical_runtime_key,
                    "sort_order": concept.sort_order,
                    "difficulty_level": concept.difficulty_level,
                    "estimated_learning_minutes": concept.estimated_learning_minutes,
                    "study_points": list(getattr(concept, "study_points", None) or []),
                    "learning_outcomes": list(
                        getattr(concept, "learning_outcomes", None) or []
                    ),
                    "story_hook": story_hooks.get(concept.id),
                    "visual_teaching": vt_pkgs.get(concept.id),
                    "teaching_sequence": list(
                        getattr(concept, "teaching_sequence", None) or []
                    ),
                    "teaching_sequence_mode": str(
                        getattr(concept, "teaching_sequence_mode", None) or "manual"
                    ),
                    "teaching_sequence_auto": list(
                        getattr(concept, "teaching_sequence_auto", None) or []
                    ),
                    "teaching_sequence_auto_fingerprint": str(
                        getattr(concept, "teaching_sequence_auto_fingerprint", None) or ""
                    ),
                    "teaching_sequence_auto_reason": str(
                        getattr(concept, "teaching_sequence_auto_reason", None) or ""
                    ),
                    "teaching_sequence_auto_status": str(
                        getattr(concept, "teaching_sequence_auto_status", None) or ""
                    ),
                    "vtse_visuals": (
                        (vtse_pkgs or {}).get(concept.id)
                        if vtse_pkgs is not None
                        else getattr(concept, "vtse_visuals", None)
                    ),
                    "vtse_template": (
                        dict(concept.vtse_template)
                        if isinstance(getattr(concept, "vtse_template", None), dict)
                        else (
                            concept.vtse_template.model_dump()
                            if getattr(concept, "vtse_template", None) is not None
                            and hasattr(concept.vtse_template, "model_dump")
                            else None
                        )
                    ),
                    "legacy_concept_key": concept.legacy_concept_key,
                    "published_revision": concept.published_revision,
                    "status": concept.status,
                }
            )
            concept_id_map[concept.id] = created.id
            result.concepts_copied += 1
        result.concept_id_map = concept_id_map

        if copy_content:
            notes_copied, questions_copied = await self._copy_admin_content(
                source_topic_id=source_topic_id,
                target_topic_id=target_topic_id,
                target_organization_id=target_organization_id,
                concept_id_map=concept_id_map,
                note_grade=note_grade,
                note_board=note_board,
            )
            result.notes_copied = notes_copied
            result.questions_copied = questions_copied

        if target_topic_source == "teacher":
            synced = await self._sync_teacher_metadata_from_source(
                source_topic_id=source_topic_id,
                target_topic_id=target_topic_id,
            )
            result.metadata_synced = synced

        return result

    async def _duplicate_story_hook_visuals(
        self,
        source_concepts: Sequence[Any],
    ) -> tuple[Dict[PydanticObjectId, Optional[Dict[str, Any]]], int]:
        """
        Deep-copy each concept's Story Hook, duplicating visual binaries through
        the storage provider so the target owns its own objects.

        ``asset_key`` is preserved (the planner and authored prompts refer to it);
        only ``id`` and ``storage_key`` are regenerated. Any copy failure aborts
        the whole clone after deleting the objects written so far.
        """
        storage = get_story_hook_storage()
        hooks: Dict[PydanticObjectId, Optional[Dict[str, Any]]] = {}
        written: List[str] = []
        copied = 0
        try:
            for concept in source_concepts:
                hook = normalize_story_hook(getattr(concept, "story_hook", None))
                if hook is None:
                    hooks[concept.id] = None
                    continue
                for visual in hook.visuals:
                    new_key = await storage.copy(
                        visual.storage_key, key_hint=visual.asset_key
                    )
                    written.append(new_key)
                    visual.storage_key = new_key
                    visual.id = uuid4().hex
                    copied += 1
                hooks[concept.id] = hook.model_dump()
        except Exception:
            for key in written:
                try:
                    await storage.delete(key)
                except Exception:  # noqa: BLE001 - best-effort cleanup
                    logger.warning("clone: orphaned story hook object %s", key)
            raise
        return hooks, copied

    async def _duplicate_vtse_visuals(
        self,
        source_concepts: Sequence[Any],
    ) -> tuple[Dict[PydanticObjectId, Optional[Dict[str, Any]]], int, List[str]]:
        from app.services.storage.visual_teaching_storage import get_vtse_visuals_storage
        from app.services.vtse_visuals.authored import normalize_vtse_visuals

        storage = get_vtse_visuals_storage()
        pkgs: Dict[PydanticObjectId, Optional[Dict[str, Any]]] = {}
        written: List[str] = []
        copied = 0
        try:
            for concept in source_concepts:
                pkg = normalize_vtse_visuals(getattr(concept, "vtse_visuals", None))
                if pkg is None:
                    pkgs[concept.id] = None
                    continue
                for image in pkg.get("images") or []:
                    new_key = await storage.copy(
                        str(image.get("storage_key") or ""),
                        key_hint=str(image.get("asset_key") or ""),
                    )
                    written.append(new_key)
                    image["storage_key"] = new_key
                    image["id"] = uuid4().hex
                    copied += 1
                pkgs[concept.id] = pkg
        except Exception:
            for key in written:
                try:
                    await storage.delete(key)
                except Exception:  # noqa: BLE001
                    logger.warning("clone: orphaned vtse visual %s", key)
            raise
        return pkgs, copied, written

    async def _duplicate_visual_teaching_images(
        self,
        source_concepts: Sequence[Any],
    ) -> tuple[Dict[PydanticObjectId, Optional[Dict[str, Any]]], int, List[str]]:
        """
        Deep-copy Visual Teaching packages with new binaries.
        Preserve asset_key / region_id / anchor_id / connection_id; regenerate id + storage_key.
        Returns (pkgs_by_concept_id, copied_count, written_storage_keys).
        """
        storage = get_visual_teaching_storage()
        pkgs: Dict[PydanticObjectId, Optional[Dict[str, Any]]] = {}
        written: List[str] = []
        copied = 0
        try:
            for concept in source_concepts:
                pkg = normalize_visual_teaching(
                    getattr(concept, "visual_teaching", None)
                )
                if pkg is None:
                    pkgs[concept.id] = None
                    continue
                for image in pkg.images:
                    new_key = await storage.copy(
                        image.storage_key, key_hint=image.asset_key
                    )
                    written.append(new_key)
                    image.storage_key = new_key
                    image.id = uuid4().hex
                    copied += 1
                pkgs[concept.id] = pkg.model_dump()
        except Exception:
            for key in written:
                try:
                    await storage.delete(key)
                except Exception:  # noqa: BLE001
                    logger.warning("clone: orphaned visual teaching object %s", key)
            raise
        return pkgs, copied, written

    async def _sync_teacher_metadata_from_source(
        self,
        *,
        source_topic_id: PydanticObjectId,
        target_topic_id: PydanticObjectId,
    ) -> bool:
        catalog = await Topic.get(source_topic_id)
        teacher = await TeacherTopic.get(target_topic_id)
        if catalog is None or teacher is None:
            return False
        if catalog.curriculum_schema_version != "v2":
            return False

        teacher.curriculum_schema_version = "v2"
        teacher.curriculum_revision = int(catalog.curriculum_revision or 0)
        teacher.curriculum_published_at = catalog.curriculum_published_at
        teacher.supports_class_sessions = bool(catalog.supports_class_sessions)
        await teacher.save()

        if catalog.curriculum_published_at is not None:
            ctx = TopicContext(
                topic_id=target_topic_id,
                topic_source="teacher",
                organization_id=teacher.organization_id,
                topic_name=teacher.topic_name,
                curriculum_schema_version="v2",
                curriculum_revision=int(teacher.curriculum_revision or 0),
                curriculum_published_at=teacher.curriculum_published_at,
                supports_class_sessions=bool(teacher.supports_class_sessions),
                is_catalog=False,
            )
            await CurriculumPublishService()._sync_runtime_cache(ctx)
        return True

    async def _copy_admin_content(
        self,
        *,
        source_topic_id: PydanticObjectId,
        target_topic_id: PydanticObjectId,
        target_organization_id: Optional[PydanticObjectId],
        concept_id_map: Dict[PydanticObjectId, PydanticObjectId],
        note_grade: str,
        note_board: str,
    ) -> tuple[int, int]:
        notes_copied = 0
        questions_copied = 0

        # Structured TopicNotes are no longer curriculum teaching material
        # (VTSE templates replace them). Still copy question bank rows.

        rows = await TopicQuestionBank.find(
            {
                "topic_id": source_topic_id,
                "organization_id": None,
                "source_type": "admin",
            }
        ).to_list()
        for q in rows:
            qtext = (q.question_text or "").strip()
            if len(qtext) < 3:
                continue
            expl = (q.explanation or "").strip() or "Imported from curriculum."
            opts = [str(x).strip() for x in (q.options or []) if str(x).strip()][:10]
            new_concept_id = None
            concept_source = q.concept_source
            concept_str = q.concept
            if q.concept_id is not None and q.concept_id in concept_id_map:
                new_concept_id = concept_id_map[q.concept_id]
                concept_source = "structured"
            try:
                await TopicQuestionBank(
                    organization_id=target_organization_id,
                    topic_id=target_topic_id,
                    difficulty_level=q.difficulty_level or "medium",
                    question_text=qtext[:5000],
                    options=opts,
                    correct_answer=q.correct_answer,
                    explanation=expl[:5000],
                    source_type="teacher",
                    concept=concept_str,
                    concept_id=new_concept_id,
                    concept_source=concept_source,
                    question_type=getattr(q, "question_type", None),
                    quiz_stage=getattr(q, "quiz_stage", None),
                    approved=True,
                    usage_count=0,
                    embedding=None,
                ).insert()
                questions_copied += 1
            except (ValueError, ValidationError):
                continue

        return notes_copied, questions_copied


async def clone_structured_curriculum(
    *,
    source_topic_id: PydanticObjectId,
    source_topic_source: TopicSource,
    source_organization_id: Optional[PydanticObjectId],
    target_topic_id: PydanticObjectId,
    target_topic_source: TopicSource,
    target_organization_id: Optional[PydanticObjectId],
    copy_content: bool = True,
    note_grade: str = "General",
    note_board: str = "general",
) -> CloneStructuredCurriculumResult:
    """Module-level helper for import and tests."""
    return await CurriculumCloneService().clone_structured_curriculum(
        source_topic_id=source_topic_id,
        source_topic_source=source_topic_source,
        source_organization_id=source_organization_id,
        target_topic_id=target_topic_id,
        target_topic_source=target_topic_source,
        target_organization_id=target_organization_id,
        copy_content=copy_content,
        note_grade=note_grade,
        note_board=note_board,
    )
