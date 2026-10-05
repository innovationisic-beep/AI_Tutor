from datetime import datetime
from typing import Any, Dict, List, Optional

from beanie.odm.fields import PydanticObjectId
from pymongo.errors import DuplicateKeyError

from app.models.learning.sessions import Session
from app.repositories.base_repository import BaseRepository


class SessionRepository(BaseRepository[Session]):
    """Repository for Session document operations."""

    def __init__(self) -> None:
        super().__init__(Session)

    async def get_student_active_session(
        self,
        student_id: PydanticObjectId,
        organization_id: Optional[PydanticObjectId] = None,
    ) -> Optional[Session]:
        """Return one in-progress session for the student (any topic). Prefer topic-scoped lookup when possible."""
        filters: dict = {
            "student_id": student_id,
            "completion_status": "in_progress",
        }
        if organization_id is not None:
            filters["organization_id"] = organization_id
        return await self.get_one(filters)

    async def get_student_active_session_for_topic(
        self,
        student_id: PydanticObjectId,
        topic_id: PydanticObjectId,
        organization_id: Optional[PydanticObjectId] = None,
    ) -> Optional[Session]:
        """At most one in-progress session per (student, topic). completion_status in_progress = active."""
        filters: dict = {
            "student_id": student_id,
            "topic_id": topic_id,
            "completion_status": "in_progress",
        }
        if organization_id is not None:
            filters["organization_id"] = organization_id
        return await self.get_one(filters)

    async def insert_in_progress_session_or_return_existing(
        self, session_data: Dict[str, Any]
    ) -> Session:
        """
        Create a new in-progress session only if none exists for
        (student_id, topic_id, organization_id). Re-checks immediately before
        insert to narrow TOCTOU races; relies on a partial unique index for full safety.
        """
        student_id = session_data["student_id"]
        topic_id = session_data["topic_id"]
        organization_id = session_data["organization_id"]
        existing = await self.get_student_active_session_for_topic(
            student_id, topic_id, organization_id=organization_id
        )
        if existing is not None:
            return existing
        try:
            return await self.create(session_data)
        except DuplicateKeyError:
            fallback = await self.get_student_active_session_for_topic(
                student_id, topic_id, organization_id=organization_id
            )
            if fallback is not None:
                return fallback
            raise

    async def get_student_sessions(
        self,
        student_id: PydanticObjectId,
        limit: int = 100,
        skip: int = 0,
        organization_id: Optional[PydanticObjectId] = None,
    ) -> List[Session]:
        """Return session history for the student, newest first."""
        filters: dict = {"student_id": student_id}
        if organization_id is not None:
            filters["organization_id"] = organization_id
        return (
            await self.model.find(filters)
            .sort([("start_time", -1)])
            .skip(skip)
            .limit(limit)
            .to_list()
        )

    async def end_session(self, session_id: PydanticObjectId) -> Optional[Session]:
        """Set completion_status to completed and end_time to now. Return updated session."""
        return await self.update(
            session_id,
            {
                "completion_status": "completed",
                "end_time": datetime.utcnow(),
            },
        )


def get_session_repository() -> SessionRepository:
    """FastAPI dependency: return a SessionRepository instance."""
    return SessionRepository()
