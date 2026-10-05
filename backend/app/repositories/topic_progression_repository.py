from typing import List

from beanie.odm.fields import PydanticObjectId

from app.models.curriculum.topic_progression_map import TopicProgressionMap
from app.repositories.base_repository import BaseRepository


class TopicProgressionRepository(BaseRepository[TopicProgressionMap]):
    """Repository for TopicProgressionMap document operations."""

    def __init__(self) -> None:
        super().__init__(TopicProgressionMap)

    async def get_next_candidates(
        self,
        topic_id: PydanticObjectId,
        organization_id: PydanticObjectId,
        limit: int = 50,
    ) -> List[TopicProgressionMap]:
        """Return progression entries for the given topic (possible next topics)."""
        return await self.get_many(
            {
                "topic_id": topic_id,
                "organization_id": organization_id,
            },
            limit=limit,
        )


def get_topic_progression_repository() -> TopicProgressionRepository:
    """FastAPI dependency: return a TopicProgressionRepository instance."""
    return TopicProgressionRepository()
