from __future__ import annotations

from typing import Optional

from beanie.odm.fields import PydanticObjectId
from fastapi import HTTPException, status

from app.models.curriculum.curriculum_cluster import CurriculumCluster
from app.repositories.curriculum_cluster_repository import CurriculumClusterRepository
from app.repositories.curriculum_concept_repository import CurriculumConceptRepository
from app.repositories.curriculum_zone_repository import CurriculumZoneRepository
from app.services.curriculum.curriculum_edit_helpers import (
    demote_published_to_draft,
    raise_published_locked,
)
from app.services.curriculum.curriculum_validators import next_cluster_number
from app.services.curriculum.curriculum_zone_service import CurriculumZoneService
from app.services.curriculum.topic_context_service import TopicContext


class CurriculumClusterService:
    def __init__(
        self,
        cluster_repo: Optional[CurriculumClusterRepository] = None,
        concept_repo: Optional[CurriculumConceptRepository] = None,
        zone_repo: Optional[CurriculumZoneRepository] = None,
    ) -> None:
        self._clusters = cluster_repo or CurriculumClusterRepository()
        self._concepts = concept_repo or CurriculumConceptRepository()
        self._zones = zone_repo or CurriculumZoneRepository()
        self._zone_service = CurriculumZoneService(
            zone_repo=self._zones,
            cluster_repo=self._clusters,
            concept_repo=self._concepts,
        )

    def _assert_editable(self, cluster: CurriculumCluster) -> None:
        if cluster.status == "published":
            raise_published_locked("clusters")

    async def create(
        self,
        ctx: TopicContext,
        *,
        curriculum_zone_id: PydanticObjectId,
        title: str,
        cluster_number: Optional[int] = None,
        sort_order: Optional[int] = None,
        estimated_learning_minutes: Optional[int] = None,
    ) -> CurriculumCluster:
        zone = await self._zone_service.get(curriculum_zone_id, ctx)
        if zone.zone_number == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "ZONE_0_NO_CLUSTERS",
                    "message": "Curriculum Zone 0 cannot contain clusters",
                },
            )
        demote_published_to_draft(zone)
        await zone.save()
        existing_numbers = await self._clusters.cluster_numbers_in_zone(zone.id)
        cn = cluster_number if cluster_number is not None else next_cluster_number(
            existing_numbers
        )
        if cn in existing_numbers:
            raise HTTPException(
                status_code=409,
                detail=f"cluster_number {cn} already exists in this zone",
            )
        siblings = await self._clusters.list_by_zone(
            zone.id, organization_id=ctx.organization_id
        )
        order = sort_order if sort_order is not None else len(siblings)

        return await self._clusters.create(
            {
                "organization_id": ctx.organization_id,
                "topic_id": ctx.topic_id,
                "topic_source": ctx.topic_source,
                "curriculum_zone_id": zone.id,
                "cluster_number": cn,
                "title": title.strip(),
                "sort_order": order,
                "estimated_learning_minutes": estimated_learning_minutes,
                "status": "draft",
            }
        )

    async def get(
        self,
        cluster_id: PydanticObjectId,
        ctx: TopicContext,
    ) -> CurriculumCluster:
        cluster = await self._clusters.get_by_id(cluster_id)
        if cluster is None or cluster.deleted_at is not None:
            raise HTTPException(status_code=404, detail="Curriculum cluster not found")
        if cluster.topic_id != ctx.topic_id or cluster.topic_source != ctx.topic_source:
            raise HTTPException(status_code=404, detail="Curriculum cluster not found")
        return cluster

    async def update(
        self,
        cluster_id: PydanticObjectId,
        ctx: TopicContext,
        *,
        title: Optional[str] = None,
        description: Optional[str] = None,
        study_points: Optional[list[str]] = None,
        learning_outcomes: Optional[list[str]] = None,
        sort_order: Optional[int] = None,
        estimated_learning_minutes: Optional[int] = None,
    ) -> CurriculumCluster:
        cluster = await self.get(cluster_id, ctx)
        demote_published_to_draft(cluster)
        if title is not None:
            cluster.title = title.strip()
        if description is not None:
            cluster.description = description.strip()
        if study_points is not None:
            cluster.study_points = [
                str(s).strip() for s in study_points if str(s).strip()
            ]
        if learning_outcomes is not None:
            cluster.learning_outcomes = [
                str(s).strip() for s in learning_outcomes if str(s).strip()
            ]
        if sort_order is not None:
            cluster.sort_order = sort_order
        if estimated_learning_minutes is not None:
            cluster.estimated_learning_minutes = estimated_learning_minutes
        await cluster.save()
        return cluster

    async def delete(
        self,
        cluster_id: PydanticObjectId,
        ctx: TopicContext,
    ) -> None:
        cluster = await self.get(cluster_id, ctx)
        self._assert_editable(cluster)
        concepts = await self._concepts.list_by_cluster(
            cluster_id, organization_id=ctx.organization_id
        )
        for c in concepts:
            await self._concepts.soft_delete(c.id)
        await self._clusters.soft_delete(cluster_id)
