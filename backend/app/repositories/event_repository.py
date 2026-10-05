from typing import Any, Dict, List

from beanie.odm.fields import PydanticObjectId

from app.models.learning.session_events import SessionEvent
from app.repositories.base_repository import BaseRepository


class EventRepository(BaseRepository[SessionEvent]):
    """Repository for SessionEvent document operations."""

    def __init__(self) -> None:
        super().__init__(SessionEvent)

    async def create_event(self, data: Dict[str, Any]) -> SessionEvent:
        """Store a new session event."""
        return await self.create(data)

    async def get_session_events(
        self,
        session_id: PydanticObjectId,
        limit: int = 100,
        skip: int = 0,
    ) -> List[SessionEvent]:
        """Return all events for the given session_id, ordered by timestamp."""
        return (
            await self.model.find({"session_id": session_id})
            .sort([("timestamp", 1)])
            .skip(skip)
            .limit(limit)
            .to_list()
        )

    async def get_student_events(
        self,
        student_id: PydanticObjectId,
        limit: int = 100,
        skip: int = 0,
    ) -> List[SessionEvent]:
        """Return all events for the given student_id, ordered by timestamp."""
        return (
            await self.model.find({"student_id": student_id})
            .sort([("timestamp", 1)])
            .skip(skip)
            .limit(limit)
            .to_list()
        )


def get_event_repository() -> EventRepository:
    """FastAPI dependency: return an EventRepository instance."""
    return EventRepository()
