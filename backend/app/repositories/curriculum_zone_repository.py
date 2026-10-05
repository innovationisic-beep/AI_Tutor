from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from beanie.odm.fields import PydanticObjectId

from app.models.curriculum.curriculum_zone import CurriculumZone
from app.repositories.base_repository import BaseRepository


def _active_filter(extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    base: Dict[str, Any] = {"deleted_at": None}
    if extra:
        base.update(extra)
    return base


class CurriculumZoneRepository(BaseRepository[CurriculumZone]):
    def __init__(self) -> None:
        super().__init__(CurriculumZone)

    async def list_by_topic(
        self,
        topic_id: PydanticObjectId,
        topic_source: str,
        *,
        organization_id: Optional[PydanticObjectId] = None,
        limit: int = 20,
    ) -> List[CurriculumZone]:
        filters = _active_filter(
            {"topic_id": topic_id, "topic_source": topic_source}
        )
        if organization_id is not None:
            filters["organization_id"] = organization_id
        return (
            await self.model.find(filters)
            .sort("+sort_order", "+zone_number")
            .limit(limit)
            .to_list()
        )

    async def get_by_zone_number(
        self,
        topic_id: PydanticObjectId,
        topic_source: str,
        zone_number: int,
        *,
        organization_id: Optional[PydanticObjectId] = None,
    ) -> Optional[CurriculumZone]:
        filters = _active_filter(
            {
                "topic_id": topic_id,
                "topic_source": topic_source,
                "zone_number": zone_number,
            }
        )
        if organization_id is not None:
            filters["organization_id"] = organization_id
        return await self.get_one(filters)

    async def soft_delete(self, zone_id: PydanticObjectId) -> bool:
        doc = await self.get_by_id(zone_id)
        if doc is None or doc.deleted_at is not None:
            return False
        doc.deleted_at = datetime.utcnow()
        doc.status = "archived"
        await doc.save()
        return True


def get_curriculum_zone_repository() -> CurriculumZoneRepository:
    return CurriculumZoneRepository()
