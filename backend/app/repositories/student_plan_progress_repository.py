from __future__ import annotations

from typing import List, Optional

from beanie.odm.fields import PydanticObjectId

from app.models.progression.student_plan_progress import StudentPlanProgress
from app.repositories.base_repository import BaseRepository


class StudentPlanProgressRepository(BaseRepository[StudentPlanProgress]):
    def __init__(self) -> None:
        super().__init__(StudentPlanProgress)

    async def get_by_track(
        self, student_id: PydanticObjectId, plan_track_key: str
    ) -> Optional[StudentPlanProgress]:
        return await self.model.find_one(
            {
                "student_id": student_id,
                "plan_track_key": plan_track_key,
            }
        )

    async def create(self, doc: StudentPlanProgress) -> StudentPlanProgress:
        await doc.insert()
        return doc

    async def save(self, doc: StudentPlanProgress) -> StudentPlanProgress:
        await doc.save()
        return doc

    async def list_for_topic(
        self, student_id: PydanticObjectId, topic_id: PydanticObjectId
    ) -> List[StudentPlanProgress]:
        return await self.model.find(
            {"student_id": student_id, "topic_id": topic_id}
        ).to_list()
