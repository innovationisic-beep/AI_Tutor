from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from beanie.odm.fields import PydanticObjectId

from app.models.classroom.class_session_instance import ClassSessionInstance
from app.repositories.base_repository import BaseRepository


class ClassSessionInstanceRepository(BaseRepository[ClassSessionInstance]):
    def __init__(self) -> None:
        super().__init__(ClassSessionInstance)

    async def list_for_class(
        self,
        *,
        organization_id: PydanticObjectId,
        class_id: str,
        status: Optional[str] = None,
        from_time: Optional[datetime] = None,
        to_time: Optional[datetime] = None,
        limit: int = 200,
    ) -> List[ClassSessionInstance]:
        filters: Dict[str, Any] = {
            "organization_id": organization_id,
            "class_id": class_id,
            # Guard against legacy/corrupt rows (e.g. plan-shaped docs) that lack
            # instance fields and break Beanie validation — which surfaces as CORS
            # in the browser when the handler 500s without CORS headers.
            "class_session_plan_id": {"$exists": True},
            "plan_snapshot": {"$exists": True},
            "scheduled_start": {"$exists": True},
        }
        if status:
            filters["status"] = status
        else:
            filters["status"] = {
                "$in": ["scheduled", "live", "completed", "cancelled"]
            }
        if from_time is not None or to_time is not None:
            time_filter: Dict[str, Any] = {}
            if from_time is not None:
                time_filter["$gte"] = from_time
            if to_time is not None:
                time_filter["$lte"] = to_time
            # Merge onto existing scheduled_start existence check.
            existing = filters.get("scheduled_start")
            if isinstance(existing, dict):
                filters["scheduled_start"] = {**existing, **time_filter}
            else:
                filters["scheduled_start"] = time_filter
        return (
            await self.model.find(filters)
            .sort("+scheduled_start")
            .limit(limit)
            .to_list()
        )


def get_class_session_instance_repository() -> ClassSessionInstanceRepository:
    return ClassSessionInstanceRepository()
