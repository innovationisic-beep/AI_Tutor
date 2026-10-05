"""Checkpoint actions during cluster-teachback reteach must not be graded."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services.handlers.cluster_teachback_orchestrator import (
    handle_cluster_teachback_input,
    handle_cluster_teachback_reteach,
)
from app.services.handlers.flow_checkpoint_handler import (
    maybe_dispatch_flow_checkpoint,
)
from app.services.handlers.teachback_handler import handle_teachback_input


def _session(**overrides):
    session = SimpleNamespace(
        id=None,
        current_mode="teachback",
        flow_state="teachback",
        teachback_concepts=["cell", "pore"],
        cluster_teachback_phase="main",
        cluster_teachback_active=True,
        concept_questions_active=False,
        concept_teaching_await_vtse_done=True,
        flow_checkpoint_pending=False,
        flow_checkpoint_resolved=True,
        flow_checkpoint_step_labels=[],
        flow_checkpoint_index=0,
        flow_completed_node_count=0,
        zone1_last_completed_beat_index=-1,
        current_concept_index=0,
        current_concept="cell",
        topic_id=None,
        zone1_timeline_cache={
            "timeline_id": "tlm_attemptb",
            "beats": [{"beat_id": "b0", "index": 0}, {"beat_id": "b1", "index": 1}],
        },
        save=AsyncMock(),
    )
    for key, value in overrides.items():
        setattr(session, key, value)
    return session


def _pause(timeline_id: str = "tlm_attemptb", count: int = 2) -> str:
    payload = {
        "labels": ["Mouth", "Esophagus"],
        "timeline_id": timeline_id,
        "completed_node_count": count,
    }
    return f"__action:flow_checkpoint_pause|{json.dumps(payload)}"


def _question(
    text: str = "Why does this step happen?",
    timeline_id: str = "tlm_attemptb",
    count: int = 2,
) -> str:
    payload = {
        "text": text,
        "timeline_id": timeline_id,
        "completed_node_count": count,
    }
    return f"__action:flow_checkpoint_question|{json.dumps(payload)}"


async def _teachback(session, text: str):
    return await handle_teachback_input(
        SimpleNamespace(),  # type: ignore[arg-type]
        session,  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
        text,
        SimpleNamespace(topic_id=None),
        AsyncMock(),
    )


@pytest.mark.asyncio
async def test_pause_during_teachback_sets_pending_without_evaluation() -> None:
    session = _session()
    with patch(
        "app.services.handlers.cluster_teachback_orchestrator.handle_cluster_teachback_input",
        new=AsyncMock(),
    ) as graded:
        out = await _teachback(session, _pause())
    graded.assert_not_awaited()
    assert out["type"] == "noop"
    assert session.flow_checkpoint_pending is True
    assert session.flow_completed_node_count == 2
    assert session.cluster_teachback_phase == "main"


@pytest.mark.asyncio
async def test_matching_question_is_clarification_not_teachback() -> None:
    session = _session(flow_checkpoint_pending=True, flow_completed_node_count=2)
    with patch(
        "app.services.handlers.cluster_teachback_orchestrator.handle_cluster_teachback_input",
        new=AsyncMock(),
    ) as graded, patch(
        "app.services.handlers.flow_checkpoint_handler._micro_build_rag_context",
        new=AsyncMock(return_value=(None, "", None, SimpleNamespace())),
    ), patch(
        "app.services.handlers.flow_checkpoint_handler.generate_tutor_rag_reply",
        new=AsyncMock(return_value="The pore opens for gas exchange."),
    ):
        out = await _teachback(session, _question())
    graded.assert_not_awaited()
    assert out["type"] == "flow_checkpoint_clarification"
    assert out.get("outcome") != "stale"
    assert "pore" in out["message"].lower() or "Hope that clears" in out["message"]
    assert session.cluster_teachback_phase == "main"
    assert session.flow_checkpoint_pending is True


@pytest.mark.asyncio
async def test_question_after_continue_is_stale_and_not_graded() -> None:
    session = _session(flow_checkpoint_pending=True, flow_completed_node_count=2)
    continued = await _teachback(
        session, "__action:flow_checkpoint_continue|tlm_attemptb"
    )
    assert continued["type"] == "flow_checkpoint_continue_ack"
    assert continued["outcome"] == "accepted"
    assert session.flow_checkpoint_pending is False
    with patch(
        "app.services.handlers.cluster_teachback_orchestrator.handle_cluster_teachback_input",
        new=AsyncMock(),
    ) as graded:
        late = await _teachback(session, _question())
    graded.assert_not_awaited()
    assert late["type"] == "flow_checkpoint_clarification"
    assert late["outcome"] == "stale"
    assert late["message"] == ""
    assert session.cluster_teachback_phase == "main"


@pytest.mark.asyncio
async def test_question_with_old_timeline_or_node_count_is_stale() -> None:
    session = _session(flow_checkpoint_pending=True, flow_completed_node_count=2)
    with patch(
        "app.services.handlers.cluster_teachback_orchestrator.handle_cluster_teachback_input",
        new=AsyncMock(),
    ) as graded:
        old_tid = await _teachback(
            session, _question(timeline_id="tlm_attempta")
        )
        other_count = await _teachback(session, _question(count=4))
    graded.assert_not_awaited()
    assert old_tid["outcome"] == "stale"
    assert other_count["outcome"] == "stale"
    assert session.cluster_teachback_phase == "main"


@pytest.mark.asyncio
async def test_continue_old_timeline_does_not_clear_pending() -> None:
    session = _session(flow_checkpoint_pending=True, flow_completed_node_count=2)
    out = await _teachback(
        session, "__action:flow_checkpoint_continue|tlm_attempta"
    )
    assert out["outcome"] == "timeline_mismatch"
    assert session.flow_checkpoint_pending is True


@pytest.mark.asyncio
async def test_plain_teachback_text_still_reaches_cluster_evaluation() -> None:
    session = _session()
    with patch(
        "app.services.handlers.cluster_teachback_orchestrator.handle_cluster_teachback_input",
        new=AsyncMock(return_value={"type": "teachback_retry", "message": "scored"}),
    ) as graded:
        out = await _teachback(session, "The leaf door lets air in.")
    graded.assert_awaited()
    assert out["type"] == "teachback_retry"


@pytest.mark.asyncio
async def test_stage_done_during_teachback_stays_noop() -> None:
    session = _session()
    action = (
        '__action:concept_vtse_stage_done|'
        + json.dumps({"timeline_id": "tlm_attemptb", "concept_index": 0})
    )
    with patch(
        "app.services.handlers.cluster_teachback_orchestrator.handle_cluster_teachback_input",
        new=AsyncMock(),
    ) as graded, patch(
        "app.services.pedagogy.concept_teaching_orchestrator.ConceptTeachingOrchestrator.maybe_emit",
        new=AsyncMock(),
    ) as complete:
        out = await _teachback(session, action)
    graded.assert_not_awaited()
    complete.assert_not_awaited()
    assert out["type"] == "noop"
    assert session.concept_questions_active is False
    assert session.concept_teaching_await_vtse_done is True


@pytest.mark.asyncio
async def test_non_checkpoint_text_is_not_dispatched() -> None:
    session = _session()
    out = await maybe_dispatch_flow_checkpoint(
        SimpleNamespace(),  # type: ignore[arg-type]
        session,  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
        SimpleNamespace(),
        "The leaf door lets air in.",
    )
    assert out is None


@pytest.mark.asyncio
async def test_reteach_returns_new_timeline_and_rearms_followup() -> None:
    session = _session(cluster_teachback_phase="reteach_pending")
    timeline = {"timeline_id": "tlm_attemptb", "beats": [{"beat_id": "b0"}]}
    with patch(
        "app.services.handlers.cluster_teachback_orchestrator._run_simplified_vtse_reteach",
        new=AsyncMock(
            return_value={"instruction_timeline_v3": timeline, "planner_source": "test"}
        ),
    ), patch(
        "app.services.handlers.cluster_teachback_orchestrator.generate_cluster_teachback_question",
        new=AsyncMock(return_value="Explain the pore in your own words."),
    ):
        out = await handle_cluster_teachback_reteach(
            SimpleNamespace(),  # type: ignore[arg-type]
            session,  # type: ignore[arg-type]
            object(),  # type: ignore[arg-type]
            object(),  # type: ignore[arg-type]
            SimpleNamespace(),
            AsyncMock(),
        )
    assert out["instruction_timeline_v3"]["timeline_id"] == "tlm_attemptb"
    assert session.cluster_teachback_phase == "main"
    assert session.current_mode == "teachback"
    assert session.cluster_teachback_question.startswith("Explain the pore")
    assert session.teachback_concepts == ["cell", "pore"]


@pytest.mark.asyncio
async def test_cluster_input_does_not_grade_checkpoint_question_after_continue() -> None:
    session = _session(flow_checkpoint_pending=False, flow_completed_node_count=2)
    with patch(
        "app.services.handlers.cluster_teachback_orchestrator.evaluate_cluster_teachback_answer",
        new=AsyncMock(),
    ) as graded:
        out = await handle_cluster_teachback_input(
            SimpleNamespace(),  # type: ignore[arg-type]
            session,  # type: ignore[arg-type]
            object(),  # type: ignore[arg-type]
            object(),  # type: ignore[arg-type]
            _question(),
            SimpleNamespace(),
            AsyncMock(),
        )
    graded.assert_not_awaited()
    assert out["outcome"] == "stale"
    assert session.cluster_teachback_phase == "main"
