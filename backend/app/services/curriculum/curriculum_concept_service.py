from __future__ import annotations

import logging
from typing import Any, List, Optional

from beanie.odm.fields import PydanticObjectId
from fastapi import HTTPException, status

from app.models.content.topic_notes import TopicNote
from app.models.content.topic_question_bank import TopicQuestionBank
from app.models.curriculum.curriculum_concept import CurriculumConcept
from app.repositories.curriculum_cluster_repository import CurriculumClusterRepository
from app.repositories.curriculum_concept_repository import CurriculumConceptRepository
from app.services.curriculum.curriculum_cluster_service import CurriculumClusterService
from app.repositories.curriculum_zone_repository import CurriculumZoneRepository
from app.services.curriculum.curriculum_edit_helpers import (
    demote_published_to_draft,
    raise_published_locked,
)
from app.services.curriculum.curriculum_validators import (
    assign_canonical_runtime_key,
    normalize_runtime_key,
    normalize_slug,
)
from app.services.curriculum.concept_teaching_sequence import (
    ConceptStoryHook,
    normalize_story_hook,
    normalize_teaching_sequence_mode,
    validate_teaching_sequence,
)
from app.services.curriculum.concept_vtse_template import (
    ConceptVtseTemplate,
    normalize_vtse_template,
    vtse_template_to_dict,
)
from app.services.storage.story_hook_storage import (
    get_story_hook_storage,
    is_valid_storage_key,
)
from app.services.storage.visual_teaching_storage import (
    get_visual_teaching_storage,
    is_valid_storage_key as is_valid_vt_storage_key,
)
from app.services.visual_teaching.authored import (
    ConceptVisualTeaching,
    apply_server_replace_stale,
    normalize_visual_teaching,
    visual_teaching_storage_keys,
)
from app.services.curriculum.topic_context_service import TopicContext


logger = logging.getLogger(__name__)


def _clean_bullet_list(values: Optional[list[str]]) -> list[str]:
    return [str(s).strip() for s in (values or []) if str(s).strip()]


def _story_hook_storage_keys(raw: Any) -> set[str]:
    hook = normalize_story_hook(raw)
    if hook is None:
        return set()
    return {v.storage_key for v in hook.visuals if v.storage_key}


def _assert_visual_storage_keys_valid(hook: Optional[ConceptStoryHook]) -> None:
    """Reject keys that are not provider-issued (path traversal, absolute paths)."""
    for visual in (hook.visuals if hook is not None else []):
        if not is_valid_storage_key(visual.storage_key):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "INVALID_VISUAL_STORAGE_KEY",
                    "message": (
                        f"Story Hook visual '{visual.asset_key}' has an invalid "
                        "storage_key. Upload the image again."
                    ),
                },
            )


def _assert_vt_storage_keys_valid(pkg: Optional[ConceptVisualTeaching]) -> None:
    for img in (pkg.images if pkg is not None else []):
        if not is_valid_vt_storage_key(img.storage_key):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "INVALID_VISUAL_TEACHING_STORAGE_KEY",
                    "message": (
                        f"Visual Teaching image '{img.asset_key}' has an invalid "
                        "storage_key. Upload the image again."
                    ),
                },
            )


async def _delete_orphaned_visual_binaries(storage_keys: set[str]) -> None:
    if not storage_keys:
        return
    storage = get_story_hook_storage()
    for key in storage_keys:
        try:
            await storage.delete(key)
        except Exception:  # noqa: BLE001
            logger.warning("[STORY_HOOK_VISUAL] orphan_delete_failed key=%s", key)


async def _delete_orphaned_vtse_visual_binaries(storage_keys: set[str]) -> None:
    if not storage_keys:
        return
    from app.services.storage.visual_teaching_storage import get_vtse_visuals_storage

    storage = get_vtse_visuals_storage()
    for key in storage_keys:
        try:
            await storage.delete(key)
        except Exception:  # noqa: BLE001
            logger.warning("[VTSE_VISUAL] orphan_delete_failed key=%s", key)


async def _delete_orphaned_vt_binaries(storage_keys: set[str]) -> None:
    if not storage_keys:
        return
    storage = get_visual_teaching_storage()
    for key in storage_keys:
        try:
            await storage.delete(key)
        except Exception:  # noqa: BLE001
            logger.warning("[VISUAL_TEACHING] orphan_delete_failed key=%s", key)


class CurriculumConceptService:
    def __init__(
        self,
        concept_repo: Optional[CurriculumConceptRepository] = None,
        cluster_repo: Optional[CurriculumClusterRepository] = None,
    ) -> None:
        self._concepts = concept_repo or CurriculumConceptRepository()
        self._clusters = cluster_repo or CurriculumClusterRepository()
        self._zones = CurriculumZoneRepository()
        self._cluster_service = CurriculumClusterService(
            cluster_repo=self._clusters,
            concept_repo=self._concepts,
        )

    def _assert_editable(self, concept: CurriculumConcept) -> None:
        if concept.status == "published":
            raise_published_locked("concepts")

    async def create(
        self,
        ctx: TopicContext,
        *,
        curriculum_cluster_id: PydanticObjectId,
        display_name: str,
        slug: Optional[str] = None,
        sort_order: Optional[int] = None,
        difficulty_level: str = "medium",
        estimated_learning_minutes: Optional[int] = None,
        study_points: Optional[list[str]] = None,
        learning_outcomes: Optional[list[str]] = None,
        story_hook: Optional[ConceptStoryHook | dict] = None,
        visual_teaching: Optional[ConceptVisualTeaching | dict] = None,
        teaching_sequence: Optional[list[str]] = None,
        teaching_sequence_mode: Optional[str] = None,
        vtse_template: Optional[ConceptVtseTemplate | dict] = None,
        vtse_visuals: Optional[dict] = None,
        legacy_concept_key: Optional[str] = None,
        canonical_runtime_key: Optional[str] = None,
    ) -> CurriculumConcept:
        cluster = await self._cluster_service.get(curriculum_cluster_id, ctx)
        zone = await self._zones.get_by_id(cluster.curriculum_zone_id)
        if zone is not None and zone.zone_number == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "ZONE_0_NO_CONCEPTS",
                    "message": "Curriculum Zone 0 cannot contain concepts",
                },
            )
        demote_published_to_draft(cluster)
        await cluster.save()
        slug_val = normalize_slug(slug or display_name)
        if await self._concepts.slug_exists(
            ctx.topic_id, ctx.topic_source, slug_val
        ):
            raise HTTPException(
                status_code=409,
                detail=f"Concept slug '{slug_val}' already exists for this topic",
            )
        siblings = await self._concepts.list_by_cluster(
            cluster.id, organization_id=ctx.organization_id
        )
        order = sort_order if sort_order is not None else len(siblings)
        diff = difficulty_level if difficulty_level in ("basic", "medium", "hard") else "medium"

        try:
            runtime_key = assign_canonical_runtime_key(
                explicit=canonical_runtime_key,
                legacy_concept_key=legacy_concept_key,
                display_name=display_name,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        if await self._concepts.canonical_runtime_key_exists(
            ctx.topic_id, ctx.topic_source, runtime_key
        ):
            raise HTTPException(
                status_code=409,
                detail=f"canonical_runtime_key '{runtime_key}' already exists for this topic",
            )

        hook = normalize_story_hook(story_hook)
        _assert_visual_storage_keys_valid(hook)
        vt_pkg = normalize_visual_teaching(visual_teaching)
        _assert_vt_storage_keys_valid(vt_pkg)
        sequence = validate_teaching_sequence(teaching_sequence)
        tmpl = normalize_vtse_template(vtse_template)
        from app.services.vtse_visuals.authored import normalize_vtse_visuals

        vtse_visual_pkg = normalize_vtse_visuals(vtse_visuals)
        if vtse_visual_pkg is not None:
            from app.services.storage.visual_teaching_storage import is_valid_storage_key

            for image in vtse_visual_pkg.get("images") or []:
                if not is_valid_storage_key(str(image.get("storage_key") or "")):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail={
                            "code": "INVALID_VTSE_VISUAL_STORAGE_KEY",
                            "message": "VTSE image storage_key is invalid. Upload the image again.",
                        },
                    )

        return await self._concepts.create(
            {
                "organization_id": ctx.organization_id,
                "topic_id": ctx.topic_id,
                "topic_source": ctx.topic_source,
                "curriculum_zone_id": cluster.curriculum_zone_id,
                "curriculum_cluster_id": cluster.id,
                "slug": slug_val,
                "display_name": display_name.strip(),
                "canonical_runtime_key": runtime_key,
                "sort_order": order,
                "difficulty_level": diff,
                "estimated_learning_minutes": estimated_learning_minutes,
                "study_points": _clean_bullet_list(study_points),
                "learning_outcomes": _clean_bullet_list(learning_outcomes),
                "story_hook": hook.model_dump() if hook is not None else None,
                "visual_teaching": vt_pkg.model_dump() if vt_pkg is not None else None,
                "teaching_sequence": sequence,
                "teaching_sequence_mode": normalize_teaching_sequence_mode(
                    teaching_sequence_mode
                ),
                "vtse_template": vtse_template_to_dict(tmpl),
                "vtse_visuals": vtse_visual_pkg,
                "legacy_concept_key": legacy_concept_key,
                "status": "draft",
            }
        )

    async def get(
        self,
        concept_id: PydanticObjectId,
        ctx: TopicContext,
    ) -> CurriculumConcept:
        concept = await self._concepts.get_by_id(concept_id)
        if concept is None or concept.deleted_at is not None:
            raise HTTPException(status_code=404, detail="Curriculum concept not found")
        if concept.topic_id != ctx.topic_id or concept.topic_source != ctx.topic_source:
            raise HTTPException(status_code=404, detail="Curriculum concept not found")
        return concept

    async def update(
        self,
        concept_id: PydanticObjectId,
        ctx: TopicContext,
        *,
        display_name: Optional[str] = None,
        sort_order: Optional[int] = None,
        difficulty_level: Optional[str] = None,
        estimated_learning_minutes: Optional[int] = None,
        study_points: Optional[list[str]] = None,
        learning_outcomes: Optional[list[str]] = None,
        story_hook: Optional[ConceptStoryHook | dict] = None,
        visual_teaching: Optional[ConceptVisualTeaching | dict] = None,
        teaching_sequence: Optional[list[str]] = None,
        teaching_sequence_mode: Optional[str] = None,
        vtse_template: Optional[ConceptVtseTemplate | dict] = None,
        vtse_visuals: Optional[dict] = None,
        canonical_runtime_key: Optional[str] = None,
    ) -> CurriculumConcept:
        concept = await self.get(concept_id, ctx)
        demote_published_to_draft(concept)
        dropped: set[str] = set()
        dropped_vt: set[str] = set()
        dropped_vtse: set[str] = set()
        if display_name is not None:
            concept.display_name = display_name.strip()
        if sort_order is not None:
            concept.sort_order = sort_order
        if difficulty_level is not None:
            if difficulty_level in ("basic", "medium", "hard"):
                concept.difficulty_level = difficulty_level
        if estimated_learning_minutes is not None:
            concept.estimated_learning_minutes = estimated_learning_minutes
        if study_points is not None:
            concept.study_points = _clean_bullet_list(study_points)
        if learning_outcomes is not None:
            concept.learning_outcomes = _clean_bullet_list(learning_outcomes)
        if story_hook is not None:
            previous_keys = _story_hook_storage_keys(concept.story_hook)
            hook = normalize_story_hook(story_hook)
            _assert_visual_storage_keys_valid(hook)
            concept.story_hook = hook.model_dump() if hook is not None else None
            dropped = previous_keys - _story_hook_storage_keys(concept.story_hook)
        if visual_teaching is not None:
            previous_vt = visual_teaching_storage_keys(concept.visual_teaching)
            previous_pkg = normalize_visual_teaching(concept.visual_teaching)
            vt_pkg = normalize_visual_teaching(visual_teaching)
            if vt_pkg is not None:
                vt_pkg = apply_server_replace_stale(previous_pkg, vt_pkg)
            _assert_vt_storage_keys_valid(vt_pkg)
            concept.visual_teaching = (
                vt_pkg.model_dump() if vt_pkg is not None else None
            )
            dropped_vt = previous_vt - visual_teaching_storage_keys(
                concept.visual_teaching
            )
        if teaching_sequence is not None:
            concept.teaching_sequence = validate_teaching_sequence(teaching_sequence)
        if teaching_sequence_mode is not None:
            concept.teaching_sequence_mode = normalize_teaching_sequence_mode(
                teaching_sequence_mode
            )
        if vtse_template is not None:
            tmpl = normalize_vtse_template(vtse_template)
            concept.vtse_template = vtse_template_to_dict(tmpl)
        if vtse_visuals is not None:
            from app.services.storage.visual_teaching_storage import is_valid_storage_key
            from app.services.vtse_visuals.authored import (
                apply_vtse_visual_replace_stale,
                normalize_vtse_visuals,
                vtse_visual_storage_keys,
            )

            previous_keys = vtse_visual_storage_keys(concept.vtse_visuals)
            stamped = apply_vtse_visual_replace_stale(concept.vtse_visuals, vtse_visuals)
            pkg = normalize_vtse_visuals(stamped)
            for image in (pkg or {}).get("images") or []:
                if not is_valid_storage_key(str(image.get("storage_key") or "")):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail={
                            "code": "INVALID_VTSE_VISUAL_STORAGE_KEY",
                            "message": "VTSE image storage_key is invalid. Upload the image again.",
                        },
                    )
            concept.vtse_visuals = pkg
            dropped_vtse = previous_keys - vtse_visual_storage_keys(concept.vtse_visuals)
        if canonical_runtime_key is not None:
            await self._apply_runtime_key_change(
                concept,
                ctx,
                canonical_runtime_key.strip(),
            )
        await concept.save()
        # Binaries are removed only after the metadata commit succeeds, so a
        # failed save can never leave a visual pointing at deleted bytes.
        await _delete_orphaned_visual_binaries(dropped)
        await _delete_orphaned_vt_binaries(dropped_vt)
        await _delete_orphaned_vtse_visual_binaries(dropped_vtse)
        return concept

    async def move(
        self,
        concept_id: PydanticObjectId,
        ctx: TopicContext,
        *,
        target_cluster_id: PydanticObjectId,
        target_index: int,
    ) -> CurriculumConcept:
        """
        Move or reorder a concept within the same zone.

        Updates ``curriculum_cluster_id`` and reindexes ``sort_order`` for
        affected clusters. Does not recreate the concept or touch notes/questions.
        """
        if target_index < 0:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "INVALID_TARGET_INDEX",
                    "message": "target_index must be >= 0",
                },
            )

        concept = await self.get(concept_id, ctx)
        target_cluster = await self._cluster_service.get(target_cluster_id, ctx)

        if target_cluster.topic_id != concept.topic_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "CROSS_TOPIC_MOVE",
                    "message": "Concept cannot move to a cluster on a different topic",
                },
            )
        if target_cluster.topic_source != concept.topic_source:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "CROSS_SOURCE_MOVE",
                    "message": "Concept cannot move across catalog/teacher curriculum sources",
                },
            )
        if (target_cluster.organization_id or None) != (concept.organization_id or None):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "CROSS_ORGANIZATION_MOVE",
                    "message": "Concept cannot move across organizations",
                },
            )
        if target_cluster.curriculum_zone_id != concept.curriculum_zone_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "CROSS_ZONE_MOVE",
                    "message": (
                        "Concept movement is only allowed within the same curriculum zone"
                    ),
                },
            )

        source_cluster_id = concept.curriculum_cluster_id
        same_cluster = source_cluster_id == target_cluster_id

        source_siblings = await self._concepts.list_by_cluster(
            source_cluster_id, organization_id=ctx.organization_id
        )
        if same_cluster:
            ordered = [c for c in source_siblings if c.id != concept.id]
            insert_at = min(target_index, len(ordered))
            ordered.insert(insert_at, concept)
            demote_published_to_draft(concept)
            await self._reindex_sort_orders(ordered)
            refreshed = await self.get(concept_id, ctx)
            return refreshed

        target_siblings = await self._concepts.list_by_cluster(
            target_cluster_id, organization_id=ctx.organization_id
        )
        source_remaining = [c for c in source_siblings if c.id != concept.id]
        dest_ordered = [c for c in target_siblings if c.id != concept.id]
        insert_at = min(target_index, len(dest_ordered))

        demote_published_to_draft(concept)
        concept.curriculum_cluster_id = target_cluster_id
        concept.curriculum_zone_id = target_cluster.curriculum_zone_id
        # Ensure sort_order is unique enough before batch reindex; final values set below.
        concept.sort_order = insert_at
        await concept.save()

        source_cluster = await self._clusters.get_by_id(source_cluster_id)
        if source_cluster is not None and source_cluster.deleted_at is None:
            demote_published_to_draft(source_cluster)
            await source_cluster.save()
        demote_published_to_draft(target_cluster)
        await target_cluster.save()

        dest_ordered.insert(insert_at, concept)
        await self._reindex_sort_orders(source_remaining)
        await self._reindex_sort_orders(dest_ordered)

        return await self.get(concept_id, ctx)

    async def _reindex_sort_orders(self, concepts: List[CurriculumConcept]) -> None:
        for index, row in enumerate(concepts):
            changed = demote_published_to_draft(row)
            if int(row.sort_order or 0) != index:
                row.sort_order = index
                changed = True
            if changed:
                await row.save()

    async def _apply_runtime_key_change(
        self,
        concept: CurriculumConcept,
        ctx: TopicContext,
        raw_key: str,
    ) -> None:
        try:
            new_key = normalize_runtime_key(raw_key)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        old_key = normalize_runtime_key(concept.canonical_runtime_key)
        if new_key == old_key:
            return

        if await self._concepts.canonical_runtime_key_exists(
            ctx.topic_id,
            ctx.topic_source,
            new_key,
            exclude_id=concept.id,
        ):
            raise HTTPException(
                status_code=409,
                detail=f"canonical_runtime_key '{new_key}' already exists for this topic",
            )

        concept.canonical_runtime_key = new_key
        await self._sync_linked_content_runtime_key(concept.id, new_key)

    async def _sync_linked_content_runtime_key(
        self,
        concept_id: PydanticObjectId,
        runtime_key: str,
    ) -> None:
        """Keep note/question concept strings aligned after a runtime key rename."""
        notes = await TopicNote.find({"concept_id": concept_id}).to_list()
        for note in notes:
            note.concept = runtime_key
            if note.concept_source is None:
                note.concept_source = "structured"
            await note.save()

        questions = await TopicQuestionBank.find({"concept_id": concept_id}).to_list()
        for question in questions:
            question.concept = runtime_key
            if question.concept_source is None:
                question.concept_source = "structured"
            await question.save()

    async def delete(
        self,
        concept_id: PydanticObjectId,
        ctx: TopicContext,
    ) -> None:
        concept = await self.get(concept_id, ctx)
        self._assert_editable(concept)
        await self._concepts.soft_delete(concept_id)
