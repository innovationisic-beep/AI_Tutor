from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from beanie.odm.fields import PydanticObjectId

from app.models.curriculum.curriculum_cluster import CurriculumCluster
from app.repositories.base_repository import BaseRepository


def _active_filter(extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    base: Dict[str, Any] = {"deleted_at": None}
    if extra:
        base.update(extra)
    return base


class CurriculumClusterRepository(BaseRepository[CurriculumCluster]):
    def __init__(self) -> None:
        super().__init__(CurriculumCluster)

    async def list_by_topic(
        self,
        topic_id: PydanticObjectId,
        topic_source: str,
        *,
        organization_id: Optional[PydanticObjectId] = None,
        zone_ids: Optional[List[PydanticObjectId]] = None,
        limit: int = 500,
    ) -> List[CurriculumCluster]:
        filters = _active_filter(
            {"topic_id": topic_id, "topic_source": topic_source}
        )
        if organization_id is not None:
            filters["organization_id"] = organization_id
        if zone_ids is not None:
            filters["curriculum_zone_id"] = {"$in": zone_ids}
        return (
            await self.model.find(filters)
            .sort("+sort_order")
            .limit(limit)
            .to_list()
        )

    async def list_by_zone(
        self,
        zone_id: PydanticObjectId,
        *,
        organization_id: Optional[PydanticObjectId] = None,
    ) -> List[CurriculumCluster]:
        filters = _active_filter({"curriculum_zone_id": zone_id})
        if organization_id is not None:
            filters["organization_id"] = organization_id
        return await self.model.find(filters).sort("+sort_order").to_list()

    async def soft_delete(self, cluster_id: PydanticObjectId) -> bool:
        doc = await self.get_by_id(cluster_id)
        if doc is None or doc.deleted_at is not None:
            return False
        doc.deleted_at = datetime.utcnow()
        doc.status = "archived"
        await doc.save()
        return True

    async def cluster_numbers_in_zone(self, zone_id: PydanticObjectId) -> List[int]:
        rows = await self.list_by_zone(zone_id)
        return [int(r.cluster_number) for r in rows]


def get_curriculum_cluster_repository() -> CurriculumClusterRepository:
    return CurriculumClusterRepository()
