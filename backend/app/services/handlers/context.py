"""
Shared dependency container injected into extracted handler functions.

Each handler module receives a HandlerContext instead of a SessionService
instance, which keeps handlers decoupled from the monolith and avoids
circular imports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from app.repositories.event_repository import EventRepository
    from app.repositories.session_repository import SessionRepository
    from app.repositories.topic_repository import TopicRepository
    from app.services.mastery_service import MasteryService
    from app.services.rag_service import RAGService


@dataclass
class HandlerContext:
    """Lightweight dependency container for handler functions."""

    session_repository: SessionRepository
    topic_repository: TopicRepository
    mastery_service: Optional[MasteryService] = None
    rag_service: Optional[RAGService] = None
    event_repository: Optional[EventRepository] = None
    student_profile: Optional[Any] = None
