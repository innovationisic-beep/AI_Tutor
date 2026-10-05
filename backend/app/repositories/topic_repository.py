from typing import List, Optional

from beanie.operators import In
from beanie.odm.fields import PydanticObjectId

from app.models.curriculum.prerequisite_graph import PrerequisiteGraph
from app.models.curriculum.topics import Topic
from app.repositories.base_repository import BaseRepository


class TopicRepository(BaseRepository[Topic]):
    """Repository for Topic document operations and prerequisite lookups."""

    def __init__(self) -> None:
        super().__init__(Topic)

    async def get_topic_by_slug(
        self,
        slug: str,
        organization_id: Optional[PydanticObjectId] = None,
    ) -> Optional[Topic]:
        """Return the topic with the given slug. Optionally scoped by organization_id."""
        filters: dict = {"topic_slug": slug.strip().lower()}
        if organization_id is not None:
            filters["organization_id"] = organization_id
        return await self.get_one(filters)

    async def get_topics_by_subject(
        self,
        subject_id: PydanticObjectId,
        limit: int = 100,
        skip: int = 0,
    ) -> List[Topic]:
        """Return topics belonging to the given subject."""
        return await self.get_many(
            {"subject_id": subject_id},
            limit=limit,
            skip=skip,
        )

    async def get_prerequisites(
        self,
        topic_id: PydanticObjectId,
        organization_id: Optional[PydanticObjectId] = None,
    ) -> List[Topic]:
        """Retrieve prerequisite topics for the given topic using PrerequisiteGraph."""
        filters: dict = {"topic_id": topic_id}
        if organization_id is not None:
            filters["organization_id"] = organization_id
        edges = await PrerequisiteGraph.find(filters).to_list()
        if not edges:
            return []
        prereq_ids = [e.prerequisite_topic_id for e in edges]
        return await Topic.find(In(Topic.id, prereq_ids)).to_list()


def get_topic_repository() -> TopicRepository:
    """FastAPI dependency: return a TopicRepository instance."""
    return TopicRepository()
