"""Flow checkpoint continue ack + pending-gate contracts."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.handlers.flow_checkpoint_handler import (
    handle_flow_checkpoint_continue,
    handle_flow_checkpoint_pause,
)
from app.services.pedagogy.concept_teaching_orchestrator import (
    ConceptTeachingOrchestrator,
)


@pytest.mark.asyncio
async def test_continue_ack_accepted_when_pending() -> None:
    session = SimpleNamespace(
        flow_checkpoint_pending=True,
        flow_checkpoint_resolved=False,
        flow_checkpoint_step_labels=["A", "B"],
        flow_checkpoint_index=0,
        flow_completed_node_count=0,
        zone1_last_completed_beat_index=-1,
        save=AsyncMock(),
    )
    out = await handle_flow_checkpoint_continue(session)  # type: ignore[arg-type]
    assert out["type"] == "flow_checkpoint_continue_ack"
    assert out["outcome"] == "accepted"
    assert out["flow_checkpoint_pending"] == 0
    assert session.flow_checkpoint_pending is False
    assert session.flow_checkpoint_resolved is True
    session.save.assert_awaited()


@pytest.mark.asyncio
async def test_continue_ack_already_cleared_is_idempotent_success() -> None:
    session = SimpleNamespace(
        flow_checkpoint_pending=False,
        flow_checkpoint_resolved=True,
        save=AsyncMock(),
    )
    out = await handle_flow_checkpoint_continue(session)  # type: ignore[arg-type]
    assert out["type"] == "flow_checkpoint_continue_ack"
    assert out["outcome"] == "already_cleared"
    assert out["flow_checkpoint_pending"] == 0
    assert session.flow_checkpoint_pending is False


@pytest.mark.asyncio
async def test_pause_sets_pending_before_continue_clears() -> None:
    session = SimpleNamespace(
        flow_checkpoint_pending=False,
        flow_checkpoint_resolved=True,
        flow_checkpoint_step_labels=[],
        flow_checkpoint_index=0,
        flow_completed_node_count=0,
        zone1_last_completed_beat_index=-1,
        save=AsyncMock(),
    )
    pause = await handle_flow_checkpoint_pause(
        session,  # type: ignore[arg-type]
        labels=["Mouth", "Esophagus"],
    )
    assert pause["type"] == "noop"
    assert session.flow_checkpoint_pending is True

    cont = await handle_flow_checkpoint_continue(session)  # type: ignore[arg-type]
    assert cont["outcome"] == "accepted"
    assert session.flow_checkpoint_pending is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "flow_state",
    [
        "concept_visual_teaching",
        "concept_story_hook",
        "concept_vtse_opening",
        "explaining",
    ],
)
async def test_cto_passes_flow_checkpoint_actions_through(flow_state: str) -> None:
    """Continue/pause must not be swallowed as noop while another stage owns flow."""
    orch = ConceptTeachingOrchestrator(concept_repo=SimpleNamespace())
    session = SimpleNamespace(
        current_zone=1,
        zone0_phase="done",
        flow_state=flow_state,
        concept_vtse_opening_status="ready",
        concept_teaching_await_vtse_done=True,
    )
    assert (
        await orch.maybe_emit(session, action="flow_checkpoint_continue")  # type: ignore[arg-type]
        is None
    )
    assert (
        await orch.maybe_emit(
            session,  # type: ignore[arg-type]
            action="flow_checkpoint_pause|{}",
        )
        is None
    )
