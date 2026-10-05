from datetime import datetime
from typing import Any, List, Optional

from beanie.odm.fields import PydanticObjectId

from app.models.learning.board_turns import SessionBoardTurn
from app.repositories.base_repository import BaseRepository


class BoardTurnRepository(BaseRepository[SessionBoardTurn]):
    def __init__(self) -> None:
        super().__init__(SessionBoardTurn)

    async def next_turn_index(self, session_id: PydanticObjectId) -> int:
        last = (
            await SessionBoardTurn.find(
                SessionBoardTurn.session_id == session_id
            )
            .sort("-turn_index")
            .limit(1)
            .to_list()
        )
        if not last:
            return 0
        return int(last[0].turn_index) + 1

    async def create_turn(
        self,
        session_id: PydanticObjectId,
        *,
        turn_index: int,
        content: str = "",
        instruction_timeline_v3: Optional[dict[str, Any]] = None,
        timeline_metadata: Optional[dict[str, Any]] = None,
        planner_source: Optional[str] = None,
        visual: Optional[dict[str, Any]] = None,
        zone: Optional[int] = None,
        cluster_index: Optional[int] = None,
        concept_index: Optional[int] = None,
        concept_id: Optional[str] = None,
        response_type: Optional[str] = None,
    ) -> SessionBoardTurn:
        doc = SessionBoardTurn(
            session_id=session_id,
            turn_index=turn_index,
            content=content[:120_000],
            instruction_timeline_v3=instruction_timeline_v3,
            timeline_metadata=timeline_metadata,
            planner_source=planner_source,
            visual=visual,
            zone=zone,
            cluster_index=cluster_index,
            concept_index=concept_index,
            concept_id=concept_id,
            response_type=response_type,
            created_at=datetime.utcnow(),
        )
        await doc.insert()
        return doc

    async def get_turns(
        self,
        session_id: PydanticObjectId,
        limit: int = 100,
    ) -> List[SessionBoardTurn]:
        cap = max(1, min(limit, 200))
        return (
            await SessionBoardTurn.find(
                SessionBoardTurn.session_id == session_id
            )
            .sort("+turn_index")
            .limit(cap)
            .to_list()
        )

    async def upsert_timeline_turn(
        self,
        session_id: PydanticObjectId,
        *,
        content: str = "",
        instruction_timeline_v3: dict[str, Any],
        timeline_metadata: Optional[dict[str, Any]] = None,
        planner_source: Optional[str] = None,
        visual: Optional[dict[str, Any]] = None,
        zone: Optional[int] = None,
        cluster_index: Optional[int] = None,
        concept_index: Optional[int] = None,
        concept_id: Optional[str] = None,
        response_type: Optional[str] = None,
    ) -> SessionBoardTurn:
        """Update the last turn when timeline_id matches; otherwise insert."""
        timeline_id = str(instruction_timeline_v3.get("timeline_id") or "")
        concept_key = (concept_id or "").strip()
        last_turns = (
            await SessionBoardTurn.find(
                SessionBoardTurn.session_id == session_id
            )
            .sort("-turn_index")
            .limit(5)
            .to_list()
        )
        for turn in last_turns:
            existing = turn.instruction_timeline_v3 or {}
            existing_id = str(existing.get("timeline_id") or "")
            turn_concept = str(turn.concept_id or "").strip()
            if (
                timeline_id
                and existing_id == timeline_id
                and turn_concept == concept_key
            ):
                turn.content = content[:120_000]
                turn.instruction_timeline_v3 = instruction_timeline_v3
                turn.timeline_metadata = timeline_metadata
                turn.planner_source = planner_source
                turn.visual = visual
                if response_type:
                    turn.response_type = response_type
                await turn.save()
                return turn
        turn_index = await self.next_turn_index(session_id)
        return await self.create_turn(
            session_id,
            turn_index=turn_index,
            content=content,
            instruction_timeline_v3=instruction_timeline_v3,
            timeline_metadata=timeline_metadata,
            planner_source=planner_source,
            visual=visual,
            zone=zone,
            cluster_index=cluster_index,
            concept_index=concept_index,
            concept_id=concept_id,
            response_type=response_type,
        )

    async def update_last_timeline_metadata(
        self,
        session_id: PydanticObjectId,
        metadata_patch: dict[str, Any],
    ) -> None:
        turns = (
            await SessionBoardTurn.find(
                SessionBoardTurn.session_id == session_id,
                SessionBoardTurn.instruction_timeline_v3 != None,  # noqa: E711
            )
            .sort("-turn_index")
            .limit(1)
            .to_list()
        )
        if not turns:
            return
        turn = turns[0]
        meta = dict(turn.timeline_metadata or {})
        meta.update(metadata_patch)
        turn.timeline_metadata = meta
        await turn.save()


def get_board_turn_repository() -> BoardTurnRepository:
    return BoardTurnRepository()
