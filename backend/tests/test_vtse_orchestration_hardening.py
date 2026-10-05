"""VTSE orchestration hardening — concept-first shape detection and policy guards."""

from __future__ import annotations

import pytest
from types import SimpleNamespace

from app.services.handlers.zone1_timeline_finalize import (
    clear_zone1_board_for_concept_change,
    decide_zone1_timeline_policy,
    finalize_zone1_tutor_payload,
    _zone1_concepts_match,
)
from app.services.timeline_planner_v3 import TimelinePlannerV3
from app.vtse.authoring.context import build_authoring_context
from app.vtse.authoring.semantic_shape import detect_semantic_shape, resolve_comparison_split
from app.vtse.authoring.semantic_extract import extract_authoring_semantics


def test_concept_vs_split_detects_comparison_under_chapter_topic() -> None:
    split, signal = resolve_comparison_split(
        concept="Stomach vs Small Intestine",
        topic_name="Digestive System",
    )
    assert split is not None
    assert signal == "concept_vs_split"

    draft = extract_authoring_semantics(
        topic_name="Digestive System",
        concept="Stomach vs Small Intestine",
        rag_context="- Stomach breaks food down\n- Small intestine absorbs nutrients",
    )
    shape, cues, comparison, rep, meta = detect_semantic_shape(
        topic_name="Digestive System",
        concept="Stomach vs Small Intestine",
        rag_context="- Stomach breaks food down\n- Small intestine absorbs nutrients",
        trait_steps=None,
        draft=draft,
    )
    assert shape == "comparison"
    assert rep == "comparison"
    assert "concept_vs_split" in cues
    assert meta.winning_signal == "concept_vs_split"
    assert meta.concept_title_used == "Stomach vs Small Intestine"
    assert comparison is not None
    assert comparison.left_label.lower().startswith("stomach")


def test_digestion_process_linear_prefers_concept_over_chapter() -> None:
    ctx = build_authoring_context(
        topic_name="Digestive System",
        concept="Digestion Process",
        rag_context="Food enters the mouth.\nThen the stomach breaks food down.",
    )
    assert ctx.semantic_shape == "linear_process"
    assert ctx.shape_detection_meta is not None
    assert ctx.shape_detection_meta.winning_signal.startswith("concept:")


def test_linear_not_falsely_routed_to_hierarchy_with_many_rag_bullets() -> None:
    bullets = "\n".join(f"- Detail point {i} about digestion stage {i}" for i in range(1, 12))
    ctx = build_authoring_context(
        topic_name="Digestive System",
        concept="Digestion Process",
        rag_context=bullets,
    )
    assert ctx.semantic_shape == "linear_process"
    assert (ctx.resolved_strategy_step_count or 0) >= 3


def test_decide_policy_forces_full_on_concept_transition() -> None:
    session = SimpleNamespace(
        current_zone=1,
        current_cluster_index=0,
        zone1_board_cluster_index=0,
        zone1_board_concept_id="Digestion Process",
        zone1_timeline_cache={
            "timeline_id": "tl_1",
            "concept_id": "Digestion Process",
            "beats": [{"beat_id": "b0", "operations": []}],
        },
    )
    policy = decide_zone1_timeline_policy(
        beat_kind="micro_reply",
        session=session,
        message="short reply",
        topic_name="Digestive System",
        concept="Stomach vs Small Intestine",
        question="?",
        planner=TimelinePlannerV3(),
        micro={"prev_rounds": 1},
    )
    assert policy == "full"


def test_decide_policy_incremental_same_concept() -> None:
    session = SimpleNamespace(
        current_zone=1,
        current_cluster_index=0,
        zone1_board_cluster_index=0,
        zone1_board_concept_id="Digestion Process",
        zone1_timeline_cache={
            "timeline_id": "tl_1",
            "concept_id": "Digestion Process",
            "beats": [{"beat_id": "b0", "operations": []}],
        },
    )
    policy = decide_zone1_timeline_policy(
        beat_kind="micro_reply",
        session=session,
        message="short reply",
        topic_name="Digestive System",
        concept="Digestion Process",
        question="?",
        planner=TimelinePlannerV3(),
        micro={"prev_rounds": 1},
    )
    assert policy == "incremental"


def test_clear_zone1_board_for_concept_change() -> None:
    session = SimpleNamespace(
        zone1_timeline_cache={"beats": [{}]},
        zone1_board_concept_id="Old Concept",
    )
    clear_zone1_board_for_concept_change(session, concept="New Concept")
    assert session.zone1_timeline_cache is None
    assert session.zone1_board_concept_id == "New Concept"


def test_clear_zone1_board_skips_same_concept() -> None:
    cache = {"beats": [{"beat_id": "b0"}], "concept_id": "Digestion Process"}
    session = SimpleNamespace(
        zone1_timeline_cache=cache,
        zone1_board_concept_id="Digestion Process",
    )
    clear_zone1_board_for_concept_change(session, concept="digestion process")
    assert session.zone1_timeline_cache is cache
    assert session.zone1_board_concept_id == "Digestion Process"


def test_decide_policy_incremental_same_concept_case_insensitive() -> None:
    session = SimpleNamespace(
        current_zone=1,
        current_cluster_index=0,
        zone1_board_cluster_index=0,
        zone1_board_concept_id="Digestion Process",
        zone1_timeline_cache={
            "timeline_id": "tl_1",
            "concept_id": "Digestion Process",
            "beats": [{"beat_id": "b0", "operations": []}],
        },
    )
    policy = decide_zone1_timeline_policy(
        beat_kind="micro_reply",
        session=session,
        message="short reply",
        topic_name="Digestive System",
        concept="digestion process",
        question="?",
        planner=TimelinePlannerV3(),
        micro={"prev_rounds": 1},
    )
    assert policy == "incremental"
    assert _zone1_concepts_match("Digestion Process", "digestion process")


@pytest.mark.asyncio
async def test_finalize_recovers_cache_when_full_rebuild_missing_timeline(monkeypatch) -> None:
    cache = {
        "timeline_id": "tl_cached",
        "concept_id": "Digestion Process",
        "beats": [{"beat_id": "b0", "operations": []}],
    }
    session = SimpleNamespace(
        id="sess_1",
        current_zone=1,
        current_cluster_index=0,
        zone1_board_cluster_index=0,
        zone1_board_concept_id="Digestion Process",
        zone1_timeline_cache=cache,
        topic_id=None,
    )

    async def _fail_full(*args, **kwargs):
        return SimpleNamespace(timeline={}, planner_source="broken", cir_instruction_debug={})

    monkeypatch.setattr(
        "app.services.handlers.zone1_timeline_finalize._zone1_full_timeline_via_vtse_async",
        _fail_full,
    )

    out = await finalize_zone1_tutor_payload(
        session,
        {"message": "Warm opening prose while the board rebuilds."},
        beat_kind="opening",
        topic_name="Digestive System",
        concept="Digestion Process",
        question="?",
        planner=TimelinePlannerV3(),
    )
    tl = out.get("instruction_timeline_v3")
    assert isinstance(tl, dict)
    assert tl.get("timeline_id") == "tl_cached"
    dbg = out.get("cir_instruction_debug") or {}
    assert dbg.get("timeline_cache_recovered") is True
    assert dbg.get("fallback_reason") == "timeline_compile_missing"
    assert dbg.get("instruction_timeline_v3_present") is True
