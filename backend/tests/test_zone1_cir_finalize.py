"""Zone 1 finalize: VTSE success vs text-only failure (no generic board)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from beanie.odm.fields import PydanticObjectId

from app.services.handlers.zone1_timeline_finalize import (
    VTSE_AUTHORING_FAILED_SOURCE,
    finalize_zone1_tutor_payload,
)
from app.services.timeline_planner_v3 import TimelinePlannerV3


def _session(**kwargs: object) -> SimpleNamespace:
    defaults: dict[str, object] = {
        "id": PydanticObjectId(),
        "current_zone": 1,
        "topic_id": None,
        "current_cluster_index": 0,
        "zone1_timeline_cache": None,
        "zone1_board_cluster_index": None,
        "zone1_board_concept_id": None,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _seed_timeline(*, concept: str, beats: int = 3) -> dict[str, Any]:
    beat_list = []
    for i in range(beats):
        eid = f"n{i}"
        beat_list.append(
            {
                "beat_id": f"beat_{i:04d}",
                "index": i,
                "narration_text": f"Narration {i}",
                "operations": [
                    {
                        "op_type": "add_entity",
                        "payload": {
                            "entity": {
                                "entity_id": eid,
                                "label": f"N{i}",
                                "kind": "concept",
                            }
                        },
                    }
                ],
            }
        )
    return {
        "timeline_id": "tl_seed_test",
        "concept_id": concept,
        "beats": beat_list,
        "entities": [{"id": f"n{i}", "label": f"N{i}"} for i in range(beats)],
        "metadata": {},
    }


async def test_opening_without_template_is_text_only() -> None:
    """No authored VTSE template → text-only (no generic CIR board)."""
    session = _session()
    msg = "A short opening about leaves and light."
    out: dict = {"message": msg}
    out2 = await finalize_zone1_tutor_payload(
        session,
        out,
        beat_kind="opening",
        topic_name="Photosynthesis",
        concept="Photosynthesis",
        question="What is photosynthesis?",
        planner=TimelinePlannerV3(),
    )
    assert out2.get("instruction_timeline_v3") is None
    assert out2.get("message") == msg
    dbg = out2.get("cir_instruction_debug") or {}
    assert dbg.get("timeline_attached") is False
    assert dbg.get("emergency_fallback_used") is not True
    assert "cir_generic" not in str(out2.get("planner_source") or "")
    assert (
        out2.get("planner_source") == VTSE_AUTHORING_FAILED_SOURCE
        or dbg.get("planner_source") == VTSE_AUTHORING_FAILED_SOURCE
    )


async def test_living_things_opening_no_generic_board() -> None:
    session = _session()
    out = {"message": "Living things grow and respond to their environment."}
    await finalize_zone1_tutor_payload(
        session,
        out,
        beat_kind="opening",
        topic_name="Living Things",
        concept="Living Things",
        question="What makes something alive?",
        planner=TimelinePlannerV3(),
    )
    assert out.get("instruction_timeline_v3") is None
    assert "cir_generic" not in str(out.get("planner_source") or "")


async def test_unsupported_topic_text_only_no_board() -> None:
    session = _session()
    out: dict = {"message": "A short opening about renormalization in QFT."}
    out2 = await finalize_zone1_tutor_payload(
        session,
        out,
        beat_kind="opening",
        topic_name="Quantum field theory",
        concept="Renormalization",
        question="?",
        planner=TimelinePlannerV3(),
    )
    assert out2.get("instruction_timeline_v3") is None
    dbg = out2.get("cir_instruction_debug") or {}
    assert dbg.get("timeline_attached") is False
    assert dbg.get("emergency_fallback_used") is not True


async def test_authoring_fail_no_emergency_generic() -> None:
    session = _session()
    out: dict = {"message": "Opening about plants and sunlight here."}
    await finalize_zone1_tutor_payload(
        session,
        out,
        beat_kind="opening",
        topic_name="Photosynthesis",
        concept="Photosynthesis",
        question="?",
        planner=TimelinePlannerV3(),
    )
    assert out.get("instruction_timeline_v3") is None
    dbg = out.get("cir_instruction_debug") or {}
    assert dbg.get("emergency_fallback_used") is not True
    assert "cir_generic" not in str(out.get("planner_source") or "")


async def test_micro_reply_always_incremental_and_board_only() -> None:
    """Short tutor continuations extend a seeded board (no policy=none ghost prose)."""
    planner = TimelinePlannerV3()
    concept = "Living Things"
    session = _session(
        zone1_timeline_cache=_seed_timeline(concept=concept),
        zone1_board_concept_id=concept,
    )
    n0 = len((getattr(session, "zone1_timeline_cache", None) or {}).get("beats") or [])
    out2: dict = {"message": "Good point."}
    await finalize_zone1_tutor_payload(
        session,
        out2,
        beat_kind="micro_reply",
        topic_name="Living Things",
        concept=concept,
        question="?",
        planner=planner,
        micro={"mc_action": "probe", "force_exit": False, "prev_rounds": 0},
    )
    tl = out2.get("instruction_timeline_v3")
    assert isinstance(tl, dict)
    assert len(tl.get("beats") or []) > n0
    assert out2.get("message") == ""
    meta = out2.get("timeline_metadata") or {}
    assert meta.get("zone1_policy") == "incremental"
    assert meta.get("instruction_display_mode") == "board_only"
    assert meta.get("playback_start_beat_index") == n0


async def test_incremental_after_cache_preserves_merge() -> None:
    """Seeded cache; incremental merges one beat."""
    planner = TimelinePlannerV3()
    concept = "Photosynthesis"
    session = _session(
        zone1_timeline_cache=_seed_timeline(concept=concept),
        zone1_board_concept_id=concept,
    )
    n0 = len((getattr(session, "zone1_timeline_cache", None) or {}).get("beats") or [])
    out2: dict = {
        "message": "I think chlorophyll captures light energy in the leaf cells."
    }
    await finalize_zone1_tutor_payload(
        session,
        out2,
        beat_kind="micro_reply",
        topic_name="Photosynthesis",
        concept=concept,
        question="?",
        planner=planner,
        micro={"mc_action": "", "force_exit": False, "prev_rounds": 0},
    )
    cache2 = getattr(session, "zone1_timeline_cache", None)
    assert isinstance(cache2, dict)
    assert len(cache2.get("beats") or []) >= n0
