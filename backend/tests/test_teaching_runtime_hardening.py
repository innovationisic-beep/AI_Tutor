"""Chaos-style contracts for attempt identity, checkpoint scope, and load bar."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.handlers.flow_checkpoint_handler import (
    handle_flow_checkpoint_continue,
)
from app.services.handlers.zone1_timeline_finalize import mint_full_rebuild_timeline_id
from app.services.pedagogy.load_pass_criteria import (
    LOAD_TARGET_SESSIONS,
    meets_load_bar,
)
from app.services.pedagogy.teaching_runtime_metrics import incr, reset, snapshot
from app.services.pedagogy.vtse_stage_completion import (
    can_complete_vtse_stage,
    reject_vtse_stage_done,
)
from app.services.tts.stream_sessions import (
    clear_all_speech_stream_sessions,
    create_speech_stream_session,
    take_speech_stream_session,
    ticket_store_mode,
)


def test_full_rebuild_mints_a_new_timeline_id() -> None:
    import re

    pattern = re.compile(r"^tlm_[A-Za-z0-9]+$")
    a = mint_full_rebuild_timeline_id("tlm_abc")
    b = mint_full_rebuild_timeline_id("tlm_abc")
    assert pattern.fullmatch(a)
    assert pattern.fullmatch(b)
    assert a.startswith("tlm_abc")
    assert "_" not in a[4:]
    assert a != b


def test_load_bar_requires_1k_and_zero_stuck() -> None:
    assert meets_load_bar(stuck_sessions=0, completed_sessions=LOAD_TARGET_SESSIONS)
    assert not meets_load_bar(
        stuck_sessions=1, completed_sessions=LOAD_TARGET_SESSIONS - 1
    )
    assert not meets_load_bar(stuck_sessions=0, completed_sessions=999)


def test_reject_counter_increments() -> None:
    reset()
    reject_vtse_stage_done("timeline_mismatch", timeline_id="tlm_old")
    assert snapshot()["vtse_stage_done_rejected"] >= 1
    incr("board_checkpoint_ignored")
    assert snapshot()["board_checkpoint_ignored"] == 1
    reset()


@pytest.mark.asyncio
async def test_continue_wrong_timeline_does_not_clear_pending() -> None:
    session = SimpleNamespace(
        id=None,
        flow_checkpoint_pending=True,
        flow_checkpoint_resolved=False,
        current_concept_index=0,
        zone1_timeline_cache={"timeline_id": "tlm_attempt_b"},
        save=AsyncMock(),
    )
    out = await handle_flow_checkpoint_continue(
        session,  # type: ignore[arg-type]
        expected_timeline_id="tlm_attempt_a",
    )
    assert out["outcome"] == "timeline_mismatch"
    assert session.flow_checkpoint_pending is True
    session.save.assert_not_awaited()


def _ready_session(**overrides):
    session = SimpleNamespace(
        current_zone=1,
        zone0_phase="done",
        current_concept_index=0,
        current_concept="cell",
        concept_teaching_for_index=0,
        concept_teaching_sequence_snapshot=["vtse"],
        concept_teaching_stage_index=0,
        concept_teaching_await_vtse_done=True,
        concept_questions_active=False,
        concept_vtse_opening_status="ready",
        concept_vtse_opening_for_index=0,
        flow_state="explaining",
        flow_checkpoint_pending=False,
        zone1_board_concept_id="cell",
        zone1_last_completed_beat_index=1,
        zone1_timeline_cache={
            "timeline_id": "tlm_attempt_b",
            "beats": [{"beat_id": "b0", "index": 0}, {"beat_id": "b1", "index": 1}],
        },
        save=AsyncMock(),
    )
    for key, value in overrides.items():
        setattr(session, key, value)
    return session


@pytest.mark.asyncio
async def test_late_attempt_stage_done_and_duplicate_are_rejected() -> None:
    identity_b = {
        "concept_index": 0,
        "concept_id": "cell",
        "timeline_id": "tlm_attempt_b",
    }
    session = _ready_session()
    ok, reason = can_complete_vtse_stage(session, identity_b)
    assert ok is True and reason == "ok"
    late = _ready_session()
    ok_late, reason_late = can_complete_vtse_stage(
        late,
        {**identity_b, "timeline_id": "tlm_attempt_a"},
    )
    assert ok_late is False
    assert reason_late == "timeline_mismatch"
    session.concept_teaching_await_vtse_done = False
    session.concept_teaching_stage_index = 1
    ok_dup, reason_dup = can_complete_vtse_stage(session, identity_b)
    assert ok_dup is False
    assert reason_dup in {"not_awaiting", "stage_consumed"}


@pytest.mark.asyncio
async def test_tts_memory_ticket_is_single_use(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TTS_TICKET_STORE", raising=False)
    assert ticket_store_mode() == "memory"
    await clear_all_speech_stream_sessions()
    sid, ticket = await create_speech_stream_session(text="hello", user_id="u1")
    first = await take_speech_stream_session(sid, ticket)
    second = await take_speech_stream_session(sid, ticket)
    assert first is not None and first.text == "hello"
    assert second is None


@pytest.mark.asyncio
async def test_tts_redis_mode_falls_back_without_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TTS_TICKET_STORE", "redis")
    import app.services.tts.stream_sessions as store

    monkeypatch.setattr(store, "_redis_unavailable", True)
    monkeypatch.setattr(store, "_redis_client", None)
    await clear_all_speech_stream_sessions()
    sid, ticket = await create_speech_stream_session(text="fallback", user_id="u1")
    taken = await take_speech_stream_session(sid, ticket)
    assert taken is not None and taken.text == "fallback"
