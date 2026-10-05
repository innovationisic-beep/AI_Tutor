from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from beanie.odm.fields import PydanticObjectId

from app.models.curriculum.curriculum_concept import CurriculumConcept
from app.repositories.base_repository import BaseRepository


def _active_filter(extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    base: Dict[str, Any] = {"deleted_at": None}
    if extra:
        base.update(extra)
    return base


class CurriculumConceptRepository(BaseRepository[CurriculumConcept]):
    def __init__(self) -> None:
        super().__init__(CurriculumConcept)

    async def list_by_topic(
        self,
        topic_id: PydanticObjectId,
        topic_source: str,
        *,
        organization_id: Optional[PydanticObjectId] = None,
        cluster_ids: Optional[List[PydanticObjectId]] = None,
        limit: int = 2000,
    ) -> List[CurriculumConcept]:
        filters = _active_filter(
            {"topic_id": topic_id, "topic_source": topic_source}
        )
        if organization_id is not None:
            filters["organization_id"] = organization_id
        if cluster_ids is not None:
            filters["curriculum_cluster_id"] = {"$in": cluster_ids}
        return (
            await self.model.find(filters)
            .sort("+sort_order")
            .limit(limit)
            .to_list()
        )

    async def list_by_cluster(
        self,
        cluster_id: PydanticObjectId,
        *,
        organization_id: Optional[PydanticObjectId] = None,
    ) -> List[CurriculumConcept]:
        filters = _active_filter({"curriculum_cluster_id": cluster_id})
        if organization_id is not None:
            filters["organization_id"] = organization_id
        return await self.model.find(filters).sort("+sort_order").to_list()

    async def list_by_ids_ordered(
        self,
        concept_ids: List[PydanticObjectId],
    ) -> List[CurriculumConcept]:
        """Return active concepts in the exact order of ``concept_ids`` (skips missing)."""
        if not concept_ids:
            return []
        rows = await self.model.find(
            _active_filter({"_id": {"$in": concept_ids}})
        ).to_list()
        by_id = {row.id: row for row in rows}
        return [by_id[cid] for cid in concept_ids if cid in by_id]

    async def soft_delete(self, concept_id: PydanticObjectId) -> bool:
        doc = await self.get_by_id(concept_id)
        if doc is None or doc.deleted_at is not None:
            return False
        doc.deleted_at = datetime.utcnow()
        doc.status = "archived"
        await doc.save()
        return True

    async def slug_exists(
        self,
        topic_id: PydanticObjectId,
        topic_source: str,
        slug: str,
        *,
        exclude_id: Optional[PydanticObjectId] = None,
    ) -> bool:
        filters = _active_filter(
            {
                "topic_id": topic_id,
                "topic_source": topic_source,
                "slug": slug,
            }
        )
        doc = await self.get_one(filters)
        if doc is None:
            return False
        if exclude_id is not None and doc.id == exclude_id:
            return False
        return True

    async def canonical_runtime_key_exists(
        self,
        topic_id: PydanticObjectId,
        topic_source: str,
        canonical_runtime_key: str,
        *,
        exclude_id: Optional[PydanticObjectId] = None,
    ) -> bool:
        filters = _active_filter(
            {
                "topic_id": topic_id,
                "topic_source": topic_source,
                "canonical_runtime_key": canonical_runtime_key,
            }
        )
        doc = await self.get_one(filters)
        if doc is None:
            return False
        if exclude_id is not None and doc.id == exclude_id:
            return False
        return True


def get_curriculum_concept_repository() -> CurriculumConceptRepository:
    return CurriculumConceptRepository()
