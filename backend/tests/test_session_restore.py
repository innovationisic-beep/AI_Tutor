"""Tests for session resume: board turns, restore API, noop persistence."""

from __future__ import annotations

import pytest
from beanie.odm.fields import PydanticObjectId

from app.models.learning.board_turns import SessionBoardTurn
from app.models.learning.messages import SessionChatMessage
from app.repositories.board_turn_repository import BoardTurnRepository
from app.repositories.message_repository import MessageRepository
from app.repositories.session_repository import SessionRepository
from app.repositories.topic_repository import TopicRepository
from app.services.session_service import SessionService


@pytest.mark.asyncio
async def test_noop_not_persisted_to_chat(db, session):
    service = SessionService(
        SessionRepository(),
        TopicRepository(),
        message_repository=MessageRepository(),
        board_turn_repository=BoardTurnRepository(),
    )
    session_id = PydanticObjectId(session.id)

    await service._persist_chat_assistant(session_id, {"type": "noop"})
    rows = await SessionChatMessage.find(
        SessionChatMessage.session_id == session_id
    ).to_list()
    assert len(rows) == 0


@pytest.mark.asyncio
async def test_board_turn_persisted_with_timeline(db, session):
    repo = BoardTurnRepository()
    service = SessionService(
        SessionRepository(),
        TopicRepository(),
        message_repository=MessageRepository(),
        board_turn_repository=repo,
    )
    session_id = PydanticObjectId(session.id)
    timeline = {"timeline_id": "t-1", "beats": [{"beat_id": "b0", "index": 0}]}
    await service._persist_board_turn_if_timeline(
        session_id,
        session,
        {
            "type": "explanation",
            "message": "Hello concept",
            "instruction_timeline_v3": timeline,
            "planner_source": "vtse",
        },
    )
    turns = await SessionBoardTurn.find(
        SessionBoardTurn.session_id == session_id
    ).to_list()
    assert len(turns) == 1
    assert turns[0].content == "Hello concept"
    assert turns[0].instruction_timeline_v3 == timeline


@pytest.mark.asyncio
async def test_get_session_restore_payload(db, session, student_user):
    msg_repo = MessageRepository()
    board_repo = BoardTurnRepository()
    service = SessionService(
        SessionRepository(),
        TopicRepository(),
        message_repository=msg_repo,
        board_turn_repository=board_repo,
    )
    session_id = PydanticObjectId(session.id)
    student_id = PydanticObjectId(student_user.id)

    await msg_repo.create_message(
        session_id,
        role="assistant",
        content="Prior teaching",
        message_type="explanation",
    )
    await board_repo.create_turn(
        session_id,
        turn_index=0,
        content="Prior teaching",
        instruction_timeline_v3={"timeline_id": "t-1", "beats": []},
    )

    payload = await service.get_session_restore_payload(session_id, student_id)
    assert payload["session_id"] == str(session_id)
    assert len(payload["messages"]) == 1
    assert len(payload["board_turns"]) == 1
    assert payload["board_turns"][0]["instruction_timeline_v3"]["timeline_id"] == "t-1"
    assert "flow_state" in payload["meta"]


@pytest.mark.asyncio
async def test_restore_static_beat_index_defaults_to_zero_mid_vtse(db, session):
    service = SessionService(
        SessionRepository(),
        TopicRepository(),
        message_repository=MessageRepository(),
        board_turn_repository=BoardTurnRepository(),
    )
    session.current_zone = 1
    session.concept_questions_active = False
    session.current_step_in_concept = 0
    session.zone1_last_completed_beat_index = None
    await session.save()
    assert SessionService._restore_static_beat_index(session) == 0


@pytest.mark.asyncio
async def test_restore_static_beat_index_none_during_concept_questions(db, session):
    session.concept_questions_active = True
    await session.save()
    assert SessionService._restore_static_beat_index(session) is None


@pytest.mark.asyncio
async def test_restore_supplements_zone0_from_messages(db, session, student_user):
    msg_repo = MessageRepository()
    board_repo = BoardTurnRepository()
    service = SessionService(
        SessionRepository(),
        TopicRepository(),
        message_repository=msg_repo,
        board_turn_repository=board_repo,
    )
    session_id = PydanticObjectId(session.id)
    student_id = PydanticObjectId(student_user.id)

    await msg_repo.create_message(
        session_id,
        role="assistant",
        content="Welcome anchor text",
        message_type="zone0_anchor",
    )
    await msg_repo.create_message(
        session_id,
        role="assistant",
        content="Curiosity hook",
        message_type="zone0_curiosity",
    )
    await board_repo.create_turn(
        session_id,
        turn_index=0,
        content="Concept VTSE",
        instruction_timeline_v3={
            "timeline_id": "t-1",
            "beats": [{"beat_id": "b0", "index": 0}, {"beat_id": "b1", "index": 1}],
        },
    )
    session.zone1_last_completed_beat_index = 1
    session.current_zone = 1
    await session.save()

    payload = await service.get_session_restore_payload(session_id, student_id)
    types = [t.get("response_type") for t in payload["board_turns"]]
    assert "zone0_anchor" in types
    assert "zone0_curiosity" in types
    last = payload["board_turns"][-1]
    assert last["timeline_metadata"]["restore_static_through_beat_index"] == 1


@pytest.mark.asyncio
async def test_restore_suppresses_stale_concept_questions(db, session, student_user):
    msg_repo = MessageRepository()
    board_repo = BoardTurnRepository()
    service = SessionService(
        SessionRepository(),
        TopicRepository(),
        message_repository=msg_repo,
        board_turn_repository=board_repo,
    )
    session_id = PydanticObjectId(session.id)
    student_id = PydanticObjectId(student_user.id)

    await msg_repo.create_message(
        session_id,
        role="assistant",
        content="Opening teach",
        message_type="explanation",
    )
    await board_repo.create_turn(
        session_id,
        turn_index=0,
        content="Opening teach",
        instruction_timeline_v3={
            "timeline_id": "t-1",
            "beats": [
                {"beat_id": "b0", "index": 0},
                {"beat_id": "b1", "index": 1},
                {"beat_id": "b2", "index": 2},
                {"beat_id": "b3", "index": 3},
            ],
        },
    )
    session.concept_questions_active = True
    session.concept_question_index = 0
    session.zone1_last_completed_beat_index = 3
    session.concept_teaching_await_vtse_done = True
    session.current_zone = 1
    await session.save()

    payload = await service.get_session_restore_payload(session_id, student_id)
    assert payload["restore_suppress_concept_questions"] is True
    assert payload["meta"]["concept_questions_active"] is False
    assert payload["restore_static_beat_index"] == 3


@pytest.mark.asyncio
async def test_restore_keeps_concept_questions_after_vtse_done(db, session, student_user):
    """flow_checkpoint_index > 0 alone must not suppress a completed VTSE → CQ arm."""
    msg_repo = MessageRepository()
    board_repo = BoardTurnRepository()
    service = SessionService(
        SessionRepository(),
        TopicRepository(),
        message_repository=msg_repo,
        board_turn_repository=board_repo,
    )
    session_id = PydanticObjectId(session.id)
    student_id = PydanticObjectId(student_user.id)

    await msg_repo.create_message(
        session_id,
        role="assistant",
        content="Opening teach",
        message_type="explanation",
    )
    session.concept_questions_active = True
    session.concept_question_index = 0
    session.current_question = "What is one step in blood flow?"
    session.flow_state = "concept_questions"
    session.concept_teaching_await_vtse_done = False
    session.flow_checkpoint_index = 2
    session.flow_checkpoint_pending = False
    session.zone1_last_completed_beat_index = 5
    session.current_zone = 1
    await session.save()

    payload = await service.get_session_restore_payload(session_id, student_id)
    assert payload["restore_suppress_concept_questions"] is False
    assert payload["meta"]["concept_questions_active"] is True


@pytest.mark.asyncio
async def test_save_student_scratchpad_notes(db, session, student_user):
    service = SessionService(
        SessionRepository(),
        TopicRepository(),
        message_repository=MessageRepository(),
        board_turn_repository=BoardTurnRepository(),
    )
    session_id = PydanticObjectId(session.id)
    student_id = PydanticObjectId(student_user.id)
    notes = "Remember: mitochondria = powerhouse of the cell"
    await service.save_student_scratchpad_notes(session_id, student_id, notes)
    reloaded = await SessionRepository().get_by_id(session_id)
    assert reloaded is not None
    assert reloaded.student_scratchpad_notes == notes

    payload = await service.get_session_restore_payload(session_id, student_id)
    assert payload["student_scratchpad_notes"] == notes


@pytest.mark.asyncio
async def test_save_board_playback_checkpoint(db, session, student_user):
    service = SessionService(
        SessionRepository(),
        TopicRepository(),
        message_repository=MessageRepository(),
        board_turn_repository=BoardTurnRepository(),
    )
    session_id = PydanticObjectId(session.id)
    student_id = PydanticObjectId(student_user.id)
    session.zone1_timeline_cache = {
        "timeline_id": "tl-active",
        "beats": [{"index": 0}, {"index": 1}, {"index": 2}],
    }
    await session.save()
    await service.save_board_playback_checkpoint(
        session_id, student_id, 2, timeline_id="tl-active"
    )
    reloaded = await SessionRepository().get_by_id(session_id)
    assert reloaded is not None
    assert reloaded.zone1_last_completed_beat_index == 2
    await service.save_board_playback_checkpoint(
        session_id, student_id, 2, timeline_id="tl-other"
    )
    reloaded = await SessionRepository().get_by_id(session_id)
    assert reloaded is not None
    assert reloaded.zone1_last_completed_beat_index == 2
