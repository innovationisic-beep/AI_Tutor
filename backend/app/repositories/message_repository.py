from datetime import datetime
from typing import Any, List, Optional

from beanie.odm.fields import PydanticObjectId

from app.models.learning.messages import SessionChatMessage
from app.repositories.base_repository import BaseRepository


class MessageRepository(BaseRepository[SessionChatMessage]):
    def __init__(self) -> None:
        super().__init__(SessionChatMessage)

    async def create_message(
        self,
        session_id: PydanticObjectId,
        role: str,
        content: str,
        message_type: Optional[str] = None,
        *,
        metadata_json: Optional[str] = None,
    ) -> SessionChatMessage:
        doc = SessionChatMessage(
            session_id=session_id,
            role=role,  # type: ignore[arg-type]
            content=content,
            message_type=message_type,
            metadata_json=metadata_json,
            created_at=datetime.utcnow(),
        )
        await doc.insert()
        return doc

    async def get_messages(
        self,
        session_id: PydanticObjectId,
        limit: int = 200,
    ) -> List[SessionChatMessage]:
        cap = max(1, min(limit, 500))
        return (
            await SessionChatMessage.find(
                SessionChatMessage.session_id == session_id
            )
            .sort("+created_at")
            .limit(cap)
            .to_list()
        )


def get_message_repository() -> MessageRepository:
    return MessageRepository()
