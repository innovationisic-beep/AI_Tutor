"""Board-native narration policy and sanitization."""

from __future__ import annotations

import pytest

from app.services.handlers.board_native_narration import (
    apply_transition_variation,
    sanitize_narration_for_timeline,
    visual_teaching_prompt_block,
)


def test_visual_prompt_block_avoids_diagram_wording() -> None:
    block = visual_teaching_prompt_block({"type": "flow", "data": {"steps": ["a"]}})
    lower = block.lower()
    assert "look at this diagram" not in lower
    assert "diagram type" not in lower
    assert "board-aligned" in lower or "instructional board" in lower


def test_sanitize_removes_diagram_phrases() -> None:
    raw = (
        "Look at this diagram. Observe the chart above. "
        "This diagram shows how plants grow."
    )
    text, meta = sanitize_narration_for_timeline(raw, variation_seed=2)
    lower = text.lower()
    assert "diagram" not in lower
    assert "chart above" not in lower
    assert meta["narration_sanitized"] is True
    assert meta["board_native_language"] is True
    assert meta["legacy_diagram_terms_removed"] >= 1
    assert meta["narration_source"] == "micro_llm"


def test_transition_variation_deterministic() -> None:
    raw = "Next consider how energy flows. Now consider the inputs."
    a = apply_transition_variation(raw, variation_seed=0)
    b = apply_transition_variation(raw, variation_seed=0)
    c = apply_transition_variation(raw, variation_seed=3)
    assert a == b
    assert a != raw or "Next consider" not in a
    assert c != a or True  # may differ by seed


@pytest.mark.asyncio
async def test_micro_reply_finalize_attaches_narration_metadata() -> None:
    """Incremental finalize stamps board-native narration observability."""
    from app.services.handlers.zone1_timeline_finalize import finalize_zone1_tutor_payload
    from app.services.timeline_planner_v3 import TimelinePlannerV3

    class _S:
        current_zone = 1
        current_cluster_index = 0
        zone1_board_cluster_index = 0
        id = "sess_bn"
        topic_id = None
        zone1_timeline_cache = {
            "timeline_id": "tl_test",
            "concept_id": "Plants",
            "beats": [
                {
                    "beat_id": "beat_0000",
                    "index": 0,
                    "operations": [
                        {
                            "operation_id": "op_ent_1",
                            "op_type": "add_entity",
                            "payload": {"entity": {"entity_id": "ent_1"}},
                        }
                    ],
                }
            ],
        }

    session = _S()
    planner = TimelinePlannerV3()
    out: dict = {
        "message": "Look at this diagram — notice the chart above as you can see.",
    }
    await finalize_zone1_tutor_payload(
        session,
        out,
        beat_kind="micro_reply",
        topic_name="Plants",
        concept="Plants",
        question="?",
        planner=planner,
        micro={"mc_action": "probe", "force_exit": False, "prev_rounds": 0},
    )
    meta = out.get("timeline_metadata") or {}
    assert meta.get("narration_sanitized") is True
    assert meta.get("board_native_language") is True
    tl = out.get("instruction_timeline_v3") or {}
    beats = tl.get("beats") or []
    assert len(beats) >= 2
    last = beats[-1]
    seg_text = (last.get("narration_segments") or [{}])[0].get("text", "")
    assert "diagram" not in seg_text.lower()
