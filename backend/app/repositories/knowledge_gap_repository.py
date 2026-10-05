from typing import List

from beanie.odm.fields import PydanticObjectId

from app.models.learning.knowledge_gaps import KnowledgeGap
from app.repositories.base_repository import BaseRepository


class KnowledgeGapRepository(BaseRepository[KnowledgeGap]):
    """Repository for KnowledgeGap document operations."""

    def __init__(self) -> None:
        super().__init__(KnowledgeGap)

    async def get_unresolved_for_student(
        self,
        student_id: PydanticObjectId,
        organization_id: PydanticObjectId,
        limit: int = 100,
    ) -> List[KnowledgeGap]:
        """Return unresolved knowledge gaps for the student in the organization."""
        return await self.get_many(
            {
                "student_id": student_id,
                "organization_id": organization_id,
                "resolved": False,
            },
            limit=limit,
        )


def get_knowledge_gap_repository() -> KnowledgeGapRepository:
    """FastAPI dependency: return a KnowledgeGapRepository instance."""
    return KnowledgeGapRepository()
