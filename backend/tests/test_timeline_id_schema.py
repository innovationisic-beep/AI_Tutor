"""Full-rebuild timeline ids stay unique and match /^tlm_[A-Za-z0-9]+$/."""

from __future__ import annotations

import re
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.cir.compile_to_timeline_v3 import compile_cir_v1_to_timeline
from app.cir.validate import validate_cir_v1
from app.services.handlers.flow_checkpoint_handler import handle_flow_checkpoint_continue
from app.services.handlers.zone1_timeline_finalize import (
    merge_zone1_timeline_fragments,
    mint_full_rebuild_timeline_id,
)
from app.services.pedagogy.vtse_stage_completion import (
    apply_scoped_beat_cursor,
    can_complete_vtse_stage,
)
from app.services.timeline_planner_v3 import TimelinePlannerV3
from app.vtse.registry.strategy_registry import resolve_strategy_id_for_representation

_TIMELINE_ID = re.compile(r"^tlm_[A-Za-z0-9]+$")

# Layout profiles the frontend timeline schema accepts.
_LAYOUT_PROFILES = {
    "flow_horizontal",
    "flow_vertical",
    "comparison_grid",
    "derivation_rail",
    "hybrid",
    "grouped_clusters",
    "comparison_columns",
    "comparison_split",
    "cycle_radial",
    "cycle_ring",
    "hierarchy_root_only",
    "hierarchy_root_children",
    "flow_progression",
    "vertical_process_phaseA",
    "empty",
}

# Strategy name → CIR representation used by that template.
_TEMPLATES = (
    ("hierarchy_concept_intro", "hierarchy", None),
    ("clustered_trait_list", "hierarchy", "cluster"),
    ("comparison_contrast", "comparison", None),
    ("cycle_process", "cycle", None),
    ("linear_process", "flow", None),
)


def _cir(rep: str, *, grouping: str | None) -> dict:
    count = 4 if grouping else 3
    nodes = []
    beats = []
    for i in range(count):
        nid = f"node_{i + 1}"
        nodes.append(
            {"id": nid, "label": f"N{i}", "summary": f"S{i}", "kind": "concept"}
        )
        beats.append(
            {
                "beat_id": f"beat_{i:04d}",
                "index": i,
                "narration_text": f"Narration {i}",
                "highlight_node_ids": [nid],
            }
        )
    edges = []
    if rep == "cycle":
        for i in range(count):
            edges.append(
                {
                    "from": f"node_{i + 1}",
                    "to": f"node_{(i + 1) % count + 1}",
                    "relation": "leads_to",
                }
            )
    elif rep == "flow":
        for i in range(1, count):
            edges.append(
                {
                    "from": f"node_{i}",
                    "to": f"node_{i + 1}",
                    "relation": "leads_to",
                }
            )
    else:
        for i in range(1, count):
            edges.append(
                {"from": "node_1", "to": f"node_{i + 1}", "relation": "part_of"}
            )
    doc: dict = {
        "version": "1",
        "representation_type": rep,
        "topic": "Cells",
        "nodes": nodes,
        "edges": edges,
        "beats": beats,
        "narration_segments": [],
        "metadata": {},
    }
    if grouping:
        doc["layout_hints"] = {"grouping": grouping}
    return doc


def _ready_session(timeline_id: str):
    return SimpleNamespace(
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
        flow_checkpoint_pending=True,
        zone1_board_concept_id="cell",
        zone1_last_completed_beat_index=0,
        zone1_timeline_cache={
            "timeline_id": timeline_id,
            "beats": [{"beat_id": "b0", "index": 0}, {"beat_id": "b1", "index": 1}],
        },
        save=AsyncMock(),
    )


def test_minted_ids_match_schema_and_differ_per_rebuild() -> None:
    stable = "tlm_9ba5143c9f89"
    first = mint_full_rebuild_timeline_id(stable)
    second = mint_full_rebuild_timeline_id(stable)
    assert _TIMELINE_ID.fullmatch(first)
    assert _TIMELINE_ID.fullmatch(second)
    assert first != stable
    assert second != stable
    assert first != second
    assert first.startswith(stable)
    assert second.startswith(stable)


def test_invalid_base_still_mints_a_schema_id() -> None:
    minted = mint_full_rebuild_timeline_id("tlm")
    assert _TIMELINE_ID.fullmatch(minted)


def test_incremental_fragment_keeps_parent_timeline_id() -> None:
    parent = mint_full_rebuild_timeline_id("tlm_9ba5143c9f89")
    prior = {
        "timeline_id": parent,
        "beats": [{"beat_id": "beat_0000", "index": 0}],
    }
    frag = TimelinePlannerV3().plan_zone1_incremental(
        prior_timeline=prior,
        next_beat_index=1,
        goal="focus",
        narration="Stay on this step.",
        focus_entity_id="node_1",
        annotation_text="note",
    ).timeline
    assert frag["timeline_id"] == parent
    merged = merge_zone1_timeline_fragments(prior, frag)
    assert merged["timeline_id"] == parent
    assert [b["beat_id"] for b in merged["beats"]] == ["beat_0000", "beat_0001"]


def test_stale_board_checkpoint_rejected() -> None:
    active = mint_full_rebuild_timeline_id("tlm_9ba5143c9f89")
    stale = mint_full_rebuild_timeline_id("tlm_9ba5143c9f89")
    session = _ready_session(active)
    assert (
        apply_scoped_beat_cursor(session, 1, timeline_id=stale, allow_final=True)
        is False
    )
    assert session.zone1_last_completed_beat_index == 0
    assert (
        apply_scoped_beat_cursor(session, 1, timeline_id=active, allow_final=True)
        is True
    )


def test_stale_stage_done_rejected() -> None:
    active = mint_full_rebuild_timeline_id("tlm_9ba5143c9f89")
    stale = mint_full_rebuild_timeline_id("tlm_9ba5143c9f89")
    session = _ready_session(active)
    session.flow_checkpoint_pending = False
    session.zone1_last_completed_beat_index = 1
    identity = {"concept_index": 0, "concept_id": "cell", "timeline_id": stale}
    ok, reason = can_complete_vtse_stage(session, identity)
    assert ok is False
    assert reason == "timeline_mismatch"
    ok_now, reason_now = can_complete_vtse_stage(
        session, {**identity, "timeline_id": active}
    )
    assert ok_now is True
    assert reason_now == "ok"


@pytest.mark.asyncio
async def test_stale_flow_checkpoint_continue_rejected() -> None:
    active = mint_full_rebuild_timeline_id("tlm_9ba5143c9f89")
    stale = mint_full_rebuild_timeline_id("tlm_9ba5143c9f89")
    session = _ready_session(active)
    out = await handle_flow_checkpoint_continue(
        session,  # type: ignore[arg-type]
        expected_timeline_id=stale,
    )
    assert out["outcome"] == "timeline_mismatch"
    assert session.flow_checkpoint_pending is True
    session.save.assert_not_awaited()


@pytest.mark.parametrize(
    ("strategy", "representation", "grouping"),
    _TEMPLATES,
)
def test_each_vtse_template_full_rebuild_id_validates(
    strategy: str, representation: str, grouping: str | None
) -> None:
    raw = _cir(representation, grouping=grouping)
    hints = {"grouping": grouping} if grouping else None
    assert (
        resolve_strategy_id_for_representation(
            representation,
            layout_hints=hints,
            node_count=len(raw["nodes"]),
        )
        == strategy
    )
    validated = validate_cir_v1(raw)
    assert validated.ok and validated.cir is not None, validated.errors
    compiled = compile_cir_v1_to_timeline(
        cir=validated.cir.model_dump(mode="json", by_alias=True),
        session_id="sess_schema",
        topic_id="topic_schema",
        concept="Cells",
        planner=TimelinePlannerV3(),
    ).timeline
    stable = str(compiled["timeline_id"])
    assert _TIMELINE_ID.fullmatch(stable)
    rebuilt = mint_full_rebuild_timeline_id(stable)
    again = mint_full_rebuild_timeline_id(stable)
    assert _TIMELINE_ID.fullmatch(rebuilt)
    assert rebuilt != again
    assert rebuilt != stable
    profile = compiled["layout_metadata"]["layout_profile"]
    assert profile in _LAYOUT_PROFILES
    assert compiled["beats"]
