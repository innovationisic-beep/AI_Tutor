from datetime import datetime
from typing import Any, Optional

from beanie.odm.fields import PydanticObjectId

from app.enums.learning_enums import SessionEventType
from app.models.learning.session_events import SessionEvent
from app.repositories.event_repository import EventRepository
from app.repositories.session_repository import SessionRepository


class EventService:
    """Validates and creates session events. Uses EventRepository and SessionRepository only."""

    def __init__(
        self,
        event_repository: EventRepository,
        session_repository: SessionRepository,
    ) -> None:
        self.event_repository = event_repository
        self.session_repository = session_repository

    async def create_event(
        self,
        session_id: PydanticObjectId,
        student_id: PydanticObjectId,
        event_type: SessionEventType,
        content: Optional[str] = None,
        response_time_ms: Optional[int] = None,
        is_correct: Optional[bool] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> SessionEvent:
        """
        Validate session and create a session event.
        Raises ValueError if session does not exist, does not belong to the student,
        or is not in_progress (completed or abandoned).
        """
        session = await self.session_repository.get_by_id(session_id)
        if session is None:
            raise ValueError("Session not found")

        if session.student_id != student_id:
            raise ValueError("Session does not belong to this student")

        if session.completion_status != "in_progress":
            raise ValueError(
                "Session is not in progress; events cannot be added to completed or abandoned sessions"
            )

        event_data = {
            "organization_id": session.organization_id,
            "student_id": session.student_id,
            "session_id": session_id,
            "event_type": event_type,
            "content": content,
            "response_time_ms": response_time_ms,
            "is_correct": is_correct,
            "metadata": metadata if metadata is not None else {},
            "timestamp": datetime.utcnow(),
        }
        return await self.event_repository.create_event(event_data)
