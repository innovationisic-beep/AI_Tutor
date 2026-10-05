from datetime import datetime
from typing import List, Optional

from beanie.odm.fields import PydanticObjectId

from app.models.learning.mastery_records import (
    MasteryRecord,
    mastery_record_filter,
    normalize_concept,
)
from app.repositories.base_repository import BaseRepository


class MasteryRepository(BaseRepository[MasteryRecord]):
    """Repository for MasteryRecord document operations."""

    def __init__(self) -> None:
        super().__init__(MasteryRecord)

    async def get_student_mastery(
        self,
        student_id: PydanticObjectId,
        organization_id: Optional[PydanticObjectId] = None,
        limit: int = 100,
        skip: int = 0,
    ) -> List[MasteryRecord]:
        """Return all mastery records for the student."""
        filters: dict = {"student_id": student_id}
        if organization_id is not None:
            filters["organization_id"] = organization_id
        return await self.get_many(filters, limit=limit, skip=skip)

    async def get_topic_mastery(
        self,
        student_id: PydanticObjectId,
        topic_id: PydanticObjectId,
        organization_id: Optional[PydanticObjectId] = None,
        concept: Optional[str] = None,
    ) -> Optional[MasteryRecord]:
        """Return mastery for student–topic, optionally scoped to a concept (None = topic-level)."""
        if organization_id is not None:
            return await self.get_one(
                mastery_record_filter(
                    organization_id,
                    student_id,
                    topic_id,
                    concept,
                )
            )
        filters: dict = {"student_id": student_id, "topic_id": topic_id}
        c = normalize_concept(concept)
        if c is None:
            filters["$or"] = [{"concept": None}, {"concept": {"$exists": False}}]
        else:
            filters["concept"] = c
        return await self.get_one(filters)

    async def update_mastery(
        self,
        student_id: PydanticObjectId,
        topic_id: PydanticObjectId,
        mastery_score: float,
        organization_id: Optional[PydanticObjectId] = None,
    ) -> Optional[MasteryRecord]:
        """Update mastery_score (and last_updated) for the student–topic record. Returns updated record or None."""
        record = await self.get_topic_mastery(
            student_id, topic_id, organization_id=organization_id
        )
        if record is None:
            return None
        return await self.update(
            record.id,
            {"mastery_score": mastery_score, "last_updated": datetime.utcnow()},
        )


def get_mastery_repository() -> MasteryRepository:
    """FastAPI dependency: return a MasteryRepository instance."""
    return MasteryRepository()
