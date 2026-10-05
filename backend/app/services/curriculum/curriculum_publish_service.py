from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict

from fastapi import HTTPException, status

from app.models.curriculum.curriculum_cluster import CurriculumCluster
from app.models.curriculum.curriculum_concept import CurriculumConcept
from app.models.curriculum.curriculum_zone import CurriculumZone
from app.repositories.curriculum_cluster_repository import CurriculumClusterRepository
from app.repositories.curriculum_concept_repository import CurriculumConceptRepository
from app.repositories.curriculum_zone_repository import CurriculumZoneRepository
from app.services.curriculum.curriculum_validation_service import (
    CurriculumValidationService,
)
from app.services.curriculum.topic_context_service import (
    TopicContext,
    save_topic_curriculum_metadata,
)
from app.services.curriculum.curriculum_edit_helpers import demote_published_to_draft
from app.services.runtime.curriculum_resolution_service import (
    CurriculumResolutionError,
    CurriculumResolutionService,
)


logger = logging.getLogger(__name__)


class CurriculumPublishService:
    def __init__(
        self,
        validation_service: CurriculumValidationService | None = None,
        zone_repo: CurriculumZoneRepository | None = None,
        cluster_repo: CurriculumClusterRepository | None = None,
        concept_repo: CurriculumConceptRepository | None = None,
    ) -> None:
        self._validation = validation_service or CurriculumValidationService()
        self._zones = zone_repo or CurriculumZoneRepository()
        self._clusters = cluster_repo or CurriculumClusterRepository()
        self._concepts = concept_repo or CurriculumConceptRepository()

    async def _sync_runtime_cache(self, ctx: TopicContext) -> None:
        """Derive legacy key_concepts cache from published structured tree."""
        if ctx.curriculum_schema_version != "v2" or ctx.curriculum_published_at is None:
            return
        try:
            manifest = await CurriculumResolutionService().resolve_published_topic_v2(
                ctx
            )
        except CurriculumResolutionError:
            return

        if ctx.topic_source == "teacher":
            from app.models.teacher_topic import TeacherTopic

            doc = await TeacherTopic.get(ctx.topic_id)
            if doc is None:
                return
            doc.key_concepts = list(manifest.key_concepts)
            doc.concept_clusters = manifest.concept_clusters
            await doc.save()
            return

        from app.models.curriculum.topics import Topic

        doc = await Topic.get(ctx.topic_id)
        if doc is None:
            return
        doc.key_concepts = list(manifest.key_concepts)
        doc.concept_clusters = manifest.concept_clusters
        await doc.save()

    async def _has_draft_entities(self, ctx: TopicContext) -> bool:
        zones = await self._zones.list_by_topic(
            ctx.topic_id,
            ctx.topic_source,
            organization_id=ctx.organization_id,
        )
        if any(z.status == "draft" for z in zones):
            return True
        zone_ids = [z.id for z in zones]
        clusters = await self._clusters.list_by_topic(
            ctx.topic_id,
            ctx.topic_source,
            organization_id=ctx.organization_id,
            zone_ids=zone_ids,
        )
        if any(c.status == "draft" for c in clusters):
            return True
        cluster_ids = [c.id for c in clusters]
        concepts = await self._concepts.list_by_topic(
            ctx.topic_id,
            ctx.topic_source,
            organization_id=ctx.organization_id,
            cluster_ids=cluster_ids,
        )
        return any(c.status == "draft" for c in concepts)

    async def _publish_entities(self, ctx: TopicContext) -> None:
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
            zone_ids=zone_ids,
        )
        cluster_ids = [c.id for c in clusters]
        concepts = await self._concepts.list_by_topic(
            ctx.topic_id,
            ctx.topic_source,
            organization_id=ctx.organization_id,
            cluster_ids=cluster_ids,
        )

        now = datetime.utcnow()
        for doc in zones:
            if isinstance(doc, CurriculumZone) and doc.status == "draft":
                doc.status = "published"
                doc.updated_at = now
                await doc.save()
        for doc in clusters:
            if isinstance(doc, CurriculumCluster) and doc.status == "draft":
                doc.status = "published"
                doc.updated_at = now
                await doc.save()
        for doc in concepts:
            if isinstance(doc, CurriculumConcept) and doc.status == "draft":
                doc.status = "published"
                doc.published_revision = int(doc.published_revision or 0) + 1
                doc.updated_at = now
                await doc.save()

    async def _unpublish_entities(self, ctx: TopicContext) -> None:
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
            zone_ids=zone_ids,
        )
        cluster_ids = [c.id for c in clusters]
        concepts = await self._concepts.list_by_topic(
            ctx.topic_id,
            ctx.topic_source,
            organization_id=ctx.organization_id,
            cluster_ids=cluster_ids,
        )

        for doc in zones:
            if isinstance(doc, CurriculumZone) and demote_published_to_draft(doc):
                await doc.save()
        for doc in clusters:
            if isinstance(doc, CurriculumCluster) and demote_published_to_draft(doc):
                await doc.save()
        for doc in concepts:
            if isinstance(doc, CurriculumConcept) and demote_published_to_draft(doc):
                await doc.save()

    async def _refresh_auto_teaching_orders(self, ctx: TopicContext) -> None:
        """Resolve stale Auto orders before validation. Never calls the model for Manual."""
        from app.services.pedagogy.stage_order_planner import resolve_auto_teaching_order

        concepts = await self._concepts.list_by_topic(
            ctx.topic_id,
            ctx.topic_source,
            organization_id=ctx.organization_id,
        )
        for concept in concepts:
            mode = str(getattr(concept, "teaching_sequence_mode", None) or "manual").strip().lower()
            if mode != "auto":
                continue
            try:
                await resolve_auto_teaching_order(concept, regenerate=False)
                await concept.save()
            except Exception:
                logger.exception(
                    "[STAGE_ORDER] publish_refresh_failed concept_id=%s",
                    getattr(concept, "id", None),
                )
                concept.teaching_sequence_auto_status = "fallback"
                concept.teaching_sequence_auto_reason = ""
                try:
                    await concept.save()
                except Exception:
                    logger.exception(
                        "[STAGE_ORDER] publish_fallback_save_failed concept_id=%s",
                        getattr(concept, "id", None),
                    )

    async def publish(self, ctx: TopicContext) -> Dict[str, Any]:
        already_published = ctx.curriculum_published_at is not None
        if already_published:
            if not await self._has_draft_entities(ctx):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "code": "NO_DRAFT_CHANGES",
                        "message": (
                            "Curriculum is published with no draft changes to republish. "
                            "Edit content to create draft revisions, then republish."
                        ),
                    },
                )

        await self._refresh_auto_teaching_orders(ctx)
        validation = await self._validation.validate(ctx)
        if not validation.ready_to_publish:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=validation.to_dict(),
            )

        await self._publish_entities(ctx)
        new_revision = int(ctx.curriculum_revision or 0) + 1
        published_at = datetime.utcnow()
        await save_topic_curriculum_metadata(
            ctx,
            curriculum_revision=new_revision,
            curriculum_published_at=published_at,
        )
        if ctx.topic_source == "teacher":
            from app.models.teacher_topic import TeacherTopic

            doc = await TeacherTopic.get(ctx.topic_id)
            if doc is not None and ctx.curriculum_schema_version == "v2":
                doc.supports_class_sessions = True
                await doc.save()
        elif ctx.topic_source == "catalog":
            from app.models.curriculum.topics import Topic

            doc = await Topic.get(ctx.topic_id)
            if doc is not None and ctx.curriculum_schema_version == "v2":
                doc.supports_class_sessions = True
                await doc.save()

        republished = already_published
        await self._sync_runtime_cache(
            TopicContext(
                topic_id=ctx.topic_id,
                topic_source=ctx.topic_source,
                organization_id=ctx.organization_id,
                topic_name=ctx.topic_name,
                curriculum_schema_version=ctx.curriculum_schema_version,
                curriculum_revision=new_revision,
                curriculum_published_at=published_at,
                supports_class_sessions=True,
                is_catalog=ctx.is_catalog,
            )
        )

        return {
            "topic_id": str(ctx.topic_id),
            "topic_source": ctx.topic_source,
            "curriculum_schema_version": ctx.curriculum_schema_version,
            "curriculum_revision": new_revision,
            "curriculum_published_at": published_at.isoformat(),
            "republished": republished,
        }

    async def unpublish(self, ctx: TopicContext) -> Dict[str, Any]:
        if ctx.curriculum_published_at is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "NOT_PUBLISHED",
                    "message": "Curriculum is not published.",
                },
            )

        await self._unpublish_entities(ctx)
        revision = int(ctx.curriculum_revision or 0)
        await save_topic_curriculum_metadata(
            ctx,
            clear_curriculum_published_at=True,
        )

        if ctx.topic_source == "teacher":
            from app.models.teacher_topic import TeacherTopic

            doc = await TeacherTopic.get(ctx.topic_id)
            if doc is not None:
                doc.supports_class_sessions = False
                await doc.save()
        elif ctx.topic_source == "catalog":
            from app.models.curriculum.topics import Topic

            doc = await Topic.get(ctx.topic_id)
            if doc is not None:
                doc.supports_class_sessions = False
                await doc.save()

        return {
            "topic_id": str(ctx.topic_id),
            "topic_source": ctx.topic_source,
            "curriculum_schema_version": ctx.curriculum_schema_version,
            "curriculum_revision": revision,
            "curriculum_published_at": None,
            "unpublished": True,
        }
