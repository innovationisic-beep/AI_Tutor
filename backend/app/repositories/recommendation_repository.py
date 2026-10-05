from typing import Any, Dict

from app.models.learning.recommendation_logs import RecommendationLog
from app.repositories.base_repository import BaseRepository


class RecommendationRepository(BaseRepository[RecommendationLog]):
    """Repository for RecommendationLog document operations."""

    def __init__(self) -> None:
        super().__init__(RecommendationLog)

    async def create_log(self, data: Dict[str, Any]) -> RecommendationLog:
        """Create a recommendation log entry."""
        return await self.create(data)


def get_recommendation_repository() -> RecommendationRepository:
    """FastAPI dependency: return a RecommendationRepository instance."""
    return RecommendationRepository()
