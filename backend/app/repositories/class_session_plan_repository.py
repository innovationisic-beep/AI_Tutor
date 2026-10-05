from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from beanie.odm.fields import PydanticObjectId

from app.models.classroom.class_session_plan import ClassSessionPlan
from app.repositories.base_repository import BaseRepository


def _active(extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    base: Dict[str, Any] = {"deleted_at": None}
    if extra:
        base.update(extra)
    return base


class ClassSessionPlanRepository(BaseRepository[ClassSessionPlan]):
    def __init__(self) -> None:
        super().__init__(ClassSessionPlan)

    async def list_for_topic_class(
        self,
        *,
        organization_id: PydanticObjectId,
        teacher_topic_id: PydanticObjectId,
        class_id: str,
        status: Optional[str] = None,
        limit: int = 200,
    ) -> List[ClassSessionPlan]:
        filters = _active(
            {
                "organization_id": organization_id,
                "teacher_topic_id": teacher_topic_id,
                "class_id": class_id,
            }
        )
        if status:
            filters["status"] = status
        return (
            await self.model.find(filters)
            .sort("+sequence_number")
            .limit(limit)
            .to_list()
        )

    async def list_published_before_sequence(
        self,
        *,
        teacher_topic_id: PydanticObjectId,
        class_id: str,
        sequence_number: int,
    ) -> List[ClassSessionPlan]:
        return (
            await self.model.find(
                _active(
                    {
                        "teacher_topic_id": teacher_topic_id,
                        "class_id": class_id,
                        "status": "published",
                        "sequence_number": {"$lt": sequence_number},
                    }
                )
            )
            .sort("+sequence_number")
            .to_list()
        )

    async def list_for_catalog_topic(
        self,
        *,
        catalog_topic_id: PydanticObjectId,
        status: Optional[str] = None,
        limit: int = 200,
    ) -> List[ClassSessionPlan]:
        filters = _active(
            {
                "plan_scope": "catalog",
                "catalog_topic_id": catalog_topic_id,
            }
        )
        if status:
            filters["status"] = status
        return (
            await self.model.find(filters)
            .sort("+sequence_number")
            .limit(limit)
            .to_list()
        )

    async def list_published_catalog_before_sequence(
        self,
        *,
        catalog_topic_id: PydanticObjectId,
        sequence_number: int,
    ) -> List[ClassSessionPlan]:
        return (
            await self.model.find(
                _active(
                    {
                        "plan_scope": "catalog",
                        "catalog_topic_id": catalog_topic_id,
                        "status": "published",
                        "sequence_number": {"$lt": sequence_number},
                    }
                )
            )
            .sort("+sequence_number")
            .to_list()
        )

    async def soft_delete(self, plan_id: PydanticObjectId) -> bool:
        doc = await self.get_by_id(plan_id)
        if doc is None or doc.deleted_at is not None:
            return False
        doc.deleted_at = datetime.utcnow()
        doc.status = "archived"
        await doc.save()
        return True


def get_class_session_plan_repository() -> ClassSessionPlanRepository:
    return ClassSessionPlanRepository()
