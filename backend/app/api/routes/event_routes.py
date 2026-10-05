from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.dependencies import get_current_user
from app.enums.learning_enums import SessionEventType
from app.models.identification.users import User
from app.models.learning.session_events import SessionEvent
from app.repositories.event_repository import EventRepository, get_event_repository
from app.repositories.session_repository import SessionRepository, get_session_repository
from app.services.event_service import EventService

router = APIRouter(prefix="/events", tags=["Events"])


class CreateEventRequest(BaseModel):
    session_id: str = Field(..., min_length=24, max_length=24)
    event_type: SessionEventType
    content: Optional[str] = None
    response_time_ms: Optional[int] = None
    is_correct: Optional[bool] = None
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)


@router.post("", response_model=SessionEvent)
async def create_event(
    body: CreateEventRequest,
    current_user: User = Depends(get_current_user),
    event_repository: EventRepository = Depends(get_event_repository),
    session_repository: SessionRepository = Depends(get_session_repository),
) -> SessionEvent:
    """Create a session event. Requires authentication; student_id is taken from the current user."""
    from beanie.odm.fields import PydanticObjectId

    try:
        session_id = PydanticObjectId(body.session_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid session_id")

    service = EventService(event_repository, session_repository)
    try:
        event = await service.create_event(
            session_id=session_id,
            student_id=current_user.id,
            event_type=body.event_type,
            content=body.content,
            response_time_ms=body.response_time_ms,
            is_correct=body.is_correct,
            metadata=body.metadata,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return event
