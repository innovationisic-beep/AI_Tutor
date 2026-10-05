from datetime import datetime, timezone

from app.cir.compile_to_timeline_v3 import compile_cir_v1_to_timeline
from app.cir.validate import validate_cir_v1
from app.services.timeline_planner_v3 import TimelinePlannerV3, utc_iso_z


def test_utc_iso_z_uses_z_suffix_not_offset() -> None:
    s = utc_iso_z(datetime(2026, 5, 8, 14, 30, 45, 123456, tzinfo=timezone.utc))
    assert s.endswith("Z")
    assert "+00:00" not in s
    assert s.startswith("2026-05-08T14:30:45")


def _minimal_hierarchy_cir() -> dict:
    nodes = []
    beats = []
    for i in range(3):
        nid = f"node_{i + 1}"
        nodes.append({"id": nid, "label": f"N{i}", "summary": f"S{i}", "kind": "concept"})
        beats.append(
            {
                "beat_id": f"beat_{i:04d}",
                "index": i,
                "narration_text": f"Narration {i}",
                "highlight_node_ids": [nid],
            }
        )
    return {
        "version": "1",
        "representation_type": "hierarchy",
        "topic": "Living Things",
        "nodes": nodes,
        "edges": [
            {"from": "node_1", "to": "node_2", "relation": "part_of"},
            {"from": "node_1", "to": "node_3", "relation": "part_of"},
        ],
        "beats": beats,
        "narration_segments": [],
        "metadata": {},
    }


def test_compile_cir_emits_valid_timeline_shape() -> None:
    planner = TimelinePlannerV3()
    raw = _minimal_hierarchy_cir()
    v = validate_cir_v1(raw)
    assert v.ok and v.cir is not None
    dumped = v.cir.model_dump(mode="json", by_alias=True)
    out = compile_cir_v1_to_timeline(
        cir=dumped,
        session_id="sess_1",
        topic_id="topic_1",
        concept="Living Things",
        planner=planner,
    )
    timeline = out.timeline

    assert timeline["schema_version"] == "3.0.0"
    assert timeline["timeline_id"].startswith("tlm_")
    assert len(timeline["beats"]) == 3
    op_types = [op["op_type"] for beat in timeline["beats"] for op in beat["operations"]]
    assert "add_entity" in op_types
    assert "annotate_entity" in op_types or "highlight_entity" in op_types

    created = timeline["created_at"]
    assert isinstance(created, str)
    assert created.endswith("Z"), f"Zod v4 datetime requires Z suffix, got {created!r}"
    assert "+00:00" not in created


def test_plan_zone1_incremental_fragment() -> None:
    planner = TimelinePlannerV3()
    prior = {
        "timeline_id": "tlm_inc_seed",
        "beats": [
            {
                "beat_id": "beat_0000",
                "index": 0,
                "operations": [
                    {
                        "op_type": "add_entity",
                        "payload": {
                            "entity": {"entity_id": "node_1", "label": "Root", "kind": "concept"}
                        },
                    }
                ],
            }
        ],
    }
    n = len(prior["beats"])
    inc = planner.plan_zone1_incremental(
        prior_timeline=prior,
        next_beat_index=n,
        goal="Socratic focus",
        narration="Focus here before you answer.",
        focus_entity_id="node_1",
        annotation_text="Quick board note.",
    )
    frag = inc.timeline
    assert frag["timeline_id"] == prior["timeline_id"]
    assert len(frag["beats"]) == 1
    assert frag["beats"][0]["beat_id"] == f"beat_{n:04d}"
    op_types = [op["op_type"] for op in frag["beats"][0]["operations"]]
    assert op_types == ["annotate_entity", "highlight_entity"]
