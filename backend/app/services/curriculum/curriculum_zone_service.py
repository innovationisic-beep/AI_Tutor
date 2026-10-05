from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from beanie.odm.fields import PydanticObjectId
from fastapi import HTTPException, status

from app.models.curriculum.curriculum_zone import CurriculumZone
from app.repositories.curriculum_cluster_repository import CurriculumClusterRepository
from app.repositories.curriculum_concept_repository import CurriculumConceptRepository
from app.repositories.curriculum_zone_repository import CurriculumZoneRepository
from app.services.curriculum.curriculum_edit_helpers import (
    demote_published_to_draft,
    raise_published_locked,
)
from app.services.curriculum.curriculum_validators import (
    allows_vtse_for_zone,
    is_system_zone_for_number,
    purpose_for_zone_number,
)
from app.services.curriculum.topic_context_service import (
    TopicContext,
    set_topic_schema_version,
)


class CurriculumZoneService:
    def __init__(
        self,
        zone_repo: Optional[CurriculumZoneRepository] = None,
        cluster_repo: Optional[CurriculumClusterRepository] = None,
        concept_repo: Optional[CurriculumConceptRepository] = None,
    ) -> None:
        self._zones = zone_repo or CurriculumZoneRepository()
        self._clusters = cluster_repo or CurriculumClusterRepository()
        self._concepts = concept_repo or CurriculumConceptRepository()

    def _assert_editable(self, zone: CurriculumZone) -> None:
        if zone.status == "published":
            raise_published_locked("zones")

    async def create(
        self,
        ctx: TopicContext,
        *,
        zone_number: int,
        title: str,
        description: str = "",
        sort_order: Optional[int] = None,
    ) -> CurriculumZone:
        if zone_number < 0 or zone_number > 4:
            raise HTTPException(status_code=400, detail="zone_number must be 0–4")
        existing = await self._zones.get_by_zone_number(
            ctx.topic_id,
            ctx.topic_source,
            zone_number,
            organization_id=ctx.organization_id,
        )
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Curriculum zone {zone_number} already exists for this topic",
            )
        if ctx.curriculum_schema_version == "v1":
            await set_topic_schema_version(ctx, "v2")

        zones = await self._zones.list_by_topic(
            ctx.topic_id,
            ctx.topic_source,
            organization_id=ctx.organization_id,
        )
        order = sort_order if sort_order is not None else len(zones)

        zone = await self._zones.create(
            {
                "organization_id": ctx.organization_id,
                "topic_id": ctx.topic_id,
                "topic_source": ctx.topic_source,
                "zone_number": zone_number,
                "title": title.strip(),
                "description": (description or "").strip(),
                "purpose": purpose_for_zone_number(zone_number),
                "allows_vtse": allows_vtse_for_zone(zone_number),
                "is_system_zone": is_system_zone_for_number(zone_number),
                "sort_order": order,
                "status": "draft",
            }
        )
        return zone

    async def get(
        self,
        zone_id: PydanticObjectId,
        ctx: TopicContext,
    ) -> CurriculumZone:
        zone = await self._zones.get_by_id(zone_id)
        if zone is None or zone.deleted_at is not None:
            raise HTTPException(status_code=404, detail="Curriculum zone not found")
        if zone.topic_id != ctx.topic_id or zone.topic_source != ctx.topic_source:
            raise HTTPException(status_code=404, detail="Curriculum zone not found")
        return zone

    async def update(
        self,
        zone_id: PydanticObjectId,
        ctx: TopicContext,
        *,
        title: Optional[str] = None,
        description: Optional[str] = None,
        sort_order: Optional[int] = None,
    ) -> CurriculumZone:
        zone = await self.get(zone_id, ctx)
        demote_published_to_draft(zone)
        if title is not None:
            zone.title = title.strip()
        if description is not None:
            zone.description = description.strip()
        if sort_order is not None:
            zone.sort_order = sort_order
        zone.allows_vtse = allows_vtse_for_zone(int(zone.zone_number))
        await zone.save()
        return zone

    async def delete(
        self,
        zone_id: PydanticObjectId,
        ctx: TopicContext,
    ) -> None:
        zone = await self.get(zone_id, ctx)
        if zone.is_system_zone:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "SYSTEM_ZONE_PROTECTED",
                    "message": "System curriculum zones cannot be deleted",
                },
            )
        self._assert_editable(zone)
        clusters = await self._clusters.list_by_zone(
            zone_id, organization_id=ctx.organization_id
        )
        for cl in clusters:
            concepts = await self._concepts.list_by_cluster(
                cl.id, organization_id=ctx.organization_id
            )
            for c in concepts:
                await self._concepts.soft_delete(c.id)
            await self._clusters.soft_delete(cl.id)
        await self._zones.soft_delete(zone_id)
