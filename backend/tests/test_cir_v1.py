"""CIR v1 foundation — validation + compile smoke tests."""

from __future__ import annotations

from app.cir import (
    compile_cir_v1_to_timeline,
    photosynthesis_cir_v1,
    validate_cir_v1,
)


def test_photosynthesis_cir_validates() -> None:
    raw = photosynthesis_cir_v1()
    res = validate_cir_v1(raw)
    assert res.ok, res.errors
    assert res.cir is not None
    assert res.cir.version == "1"
    assert len(res.cir.nodes) == 3


def test_photosynthesis_compile_ops_match_beats() -> None:
    raw = photosynthesis_cir_v1()
    res = validate_cir_v1(raw)
    assert res.ok
    assert res.cir is not None
    dumped = res.cir.model_dump(mode="json", by_alias=True)
    out = compile_cir_v1_to_timeline(
        cir=dumped,
        session_id="sess_test",
        topic_id=None,
        concept="photosynthesis",
    )
    tl = out.timeline
    assert len(tl["beats"]) == 3
    assert tl["beats"][0]["operations"][0]["op_type"] == "add_entity"
    assert out.planner_source == "timeline_v3_from_cir_v1"
    assert isinstance(out.cir_instruction_debug, dict)
    assert out.cir_instruction_debug.get("layout_mode")


def test_invalid_duplicate_node_id() -> None:
    raw = photosynthesis_cir_v1()
    raw["nodes"][1]["id"] = raw["nodes"][0]["id"]
    res = validate_cir_v1(raw)
    assert not res.ok
    assert any("duplicate node" in e for e in res.errors)


def test_invalid_edge_endpoint() -> None:
    raw = photosynthesis_cir_v1()
    raw["edges"].append({"from": "node_1", "to": "missing", "relation": "leads_to"})
    res = validate_cir_v1(raw)
    assert not res.ok


def test_invalid_beat_count_mismatch() -> None:
    raw = photosynthesis_cir_v1()
    raw["beats"].pop()
    res = validate_cir_v1(raw)
    assert not res.ok
    assert any("len(nodes)" in e for e in res.errors)


def test_narration_segment_unknown_beat() -> None:
    raw = photosynthesis_cir_v1()
    raw["narration_segments"][0]["beat_id"] = "nope"
    res = validate_cir_v1(raw)
    assert not res.ok


def test_too_many_nodes_rejected() -> None:
    nodes = []
    beats = []
    for i in range(25):
        nid = f"n{i}"
        nodes.append({"id": nid, "label": "L", "summary": "", "kind": "concept"})
        beats.append(
            {
                "beat_id": f"beat_{i:04d}",
                "index": i,
                "narration_text": "x",
                "highlight_node_ids": [nid],
            }
        )
    raw = {
        "version": "1",
        "representation_type": "flow",
        "topic": "t",
        "nodes": nodes,
        "edges": [],
        "beats": beats,
        "narration_segments": [],
        "metadata": {},
    }
    res = validate_cir_v1(raw)
    assert not res.ok
    assert any("at most 24 nodes" in e for e in res.errors)


def test_more_than_seven_nodes_allowed() -> None:
    nodes = []
    beats = []
    for i in range(10):
        nid = f"n{i}"
        nodes.append({"id": nid, "label": "L", "summary": "", "kind": "concept"})
        beats.append(
            {
                "beat_id": f"beat_{i:04d}",
                "index": i,
                "narration_text": "x",
                "highlight_node_ids": [nid],
            }
        )
    raw = {
        "version": "1",
        "representation_type": "comparison",
        "topic": "Humans vs Robots",
        "nodes": nodes,
        "edges": [],
        "beats": beats,
        "narration_segments": [],
        "metadata": {},
    }
    res = validate_cir_v1(raw)
    assert res.ok, res.errors


def test_too_many_edges_rejected() -> None:
    raw = photosynthesis_cir_v1()
    for _ in range(25):
        raw["edges"].append({"from": "node_1", "to": "node_2", "relation": "part_of"})
    res = validate_cir_v1(raw)
    assert not res.ok
    assert any("at most 24 edges" in e for e in res.errors)


def test_cycle_representation_compiles() -> None:
    nodes = []
    beats = []
    for i in range(3):
        nid = f"node_{i + 1}"
        nodes.append({"id": nid, "label": f"S{i}", "summary": "", "kind": "process"})
        beats.append(
            {
                "beat_id": f"beat_{i:04d}",
                "index": i,
                "narration_text": f"N{i}",
                "highlight_node_ids": [nid],
            }
        )
    raw = {
        "version": "1",
        "representation_type": "cycle",
        "topic": "Cycle",
        "nodes": nodes,
        "edges": [],
        "beats": beats,
        "narration_segments": [],
        "metadata": {},
    }
    v = validate_cir_v1(raw)
    assert v.ok, v.errors
    dumped = v.cir.model_dump(mode="json", by_alias=True) if v.cir else {}
    out = compile_cir_v1_to_timeline(
        cir=dumped,
        session_id="s",
        topic_id=None,
        concept="c",
        from_llm=True,
    )
    assert out.planner_source == "timeline_v3_from_cir_llm_v1"
    last_ops = out.timeline["beats"][-1]["operations"]
    assert any(o.get("op_type") == "connect_entities" for o in last_ops)
    lm = out.timeline.get("layout_metadata") or {}
    assert lm.get("layout_mode") == "cycle_radial"
    assert lm.get("layout_profile") == "cycle_ring"
    # Nodes on a ring should not share one horizontal line (y differs).
    ys = []
    for beat in out.timeline["beats"]:
        for op in beat["operations"]:
            if op.get("op_type") == "add_entity":
                ent = (op.get("payload") or {}).get("entity") or {}
                sp = ent.get("spatial") or {}
                ys.append(int(sp.get("y") or 0))
    assert len(set(ys)) >= 2


def _minimal_cycle_cir(*, node_count: int) -> dict:
    nodes = []
    beats = []
    for i in range(node_count):
        nid = f"node_{i + 1}"
        nodes.append({"id": nid, "label": f"S{i}", "summary": "", "kind": "process"})
        beats.append(
            {
                "beat_id": f"beat_{i:04d}",
                "index": i,
                "narration_text": f"N{i}",
                "highlight_node_ids": [nid],
            }
        )
    return {
        "version": "1",
        "representation_type": "cycle",
        "topic": "Cycle",
        "nodes": nodes,
        "edges": [],
        "beats": beats,
        "narration_segments": [],
        "metadata": {},
    }


def test_cycle_ring_layout_profile_for_node_counts() -> None:
    for n in (3, 5, 7):
        raw = _minimal_cycle_cir(node_count=n)
        v = validate_cir_v1(raw)
        assert v.ok, v.errors
        dumped = v.cir.model_dump(mode="json", by_alias=True) if v.cir else {}
        out = compile_cir_v1_to_timeline(
            cir=dumped,
            session_id="s",
            topic_id=None,
            concept="c",
            from_llm=True,
        )
        lm = out.timeline.get("layout_metadata") or {}
        assert lm.get("layout_profile") == "cycle_ring"
        assert lm.get("layout_mode") == "cycle_radial"
        last_ops = out.timeline["beats"][-1]["operations"]
        assert any(o.get("op_type") == "connect_entities" for o in last_ops)


def _connect_ops(timeline: dict) -> list[dict]:
    out: list[dict] = []
    for beat in timeline.get("beats") or []:
        for op in beat.get("operations") or []:
            if op.get("op_type") == "connect_entities":
                out.append(op)
    return out


def test_photosynthesis_uses_cir_hub_edges_not_synthesized_duplicates() -> None:
    raw = photosynthesis_cir_v1()
    res = validate_cir_v1(raw)
    assert res.ok and res.cir is not None
    dumped = res.cir.model_dump(mode="json", by_alias=True)
    out = compile_cir_v1_to_timeline(
        cir=dumped,
        session_id="sess_edges",
        topic_id=None,
        concept="photosynthesis",
    )
    dbg = out.cir_instruction_debug or {}
    assert dbg.get("edges_emitted_from_cir", 0) >= 2
    assert dbg.get("edge_compile_source") in {"cir", "mixed"}
    connects = _connect_ops(out.timeline)
    assert len(connects) == 2
    for op in connects:
        payload = op.get("payload") or {}
        assert payload.get("edge_source") == "cir"
        assert payload.get("relation") == "part_of"
        assert str(payload.get("from_id")) == "node_1"


def test_custom_cir_edge_skips_chain_synthesis() -> None:
    nodes = []
    beats = []
    for i in range(3):
        nid = f"node_{i + 1}"
        nodes.append({"id": nid, "label": f"N{i}", "summary": "", "kind": "process"})
        beats.append(
            {
                "beat_id": f"beat_{i:04d}",
                "index": i,
                "narration_text": f"step {i}",
                "highlight_node_ids": [nid],
            }
        )
    raw = {
        "version": "1",
        "representation_type": "flow",
        "topic": "Skip chain",
        "nodes": nodes,
        "edges": [{"from": "node_1", "to": "node_3", "relation": "causes"}],
        "beats": beats,
        "narration_segments": [],
        "metadata": {},
    }
    v = validate_cir_v1(raw)
    assert v.ok, v.errors
    dumped = v.cir.model_dump(mode="json", by_alias=True) if v.cir else {}
    out = compile_cir_v1_to_timeline(
        cir=dumped,
        session_id="s",
        topic_id=None,
        concept="c",
    )
    beat1_connects = [
        o
        for o in (out.timeline["beats"][1].get("operations") or [])
        if o.get("op_type") == "connect_entities"
    ]
    assert len(beat1_connects) == 1
    assert beat1_connects[0]["payload"]["from_id"] == "node_1"
    assert beat1_connects[0]["payload"]["to_id"] == "node_2"
    assert beat1_connects[0]["payload"]["edge_source"] == "synthesized"

    beat2_connects = [
        o
        for o in (out.timeline["beats"][2].get("operations") or [])
        if o.get("op_type") == "connect_entities"
    ]
    assert len(beat2_connects) == 1
    assert beat2_connects[0]["payload"]["edge_source"] == "cir"
    assert beat2_connects[0]["payload"]["relation"] == "causes"
    assert beat2_connects[0]["payload"]["to_id"] == "node_3"


def test_flow_cir_compiles_when_layout_hints_omitted() -> None:
    """Null-safe layout_hints: flow CIR without hints must compile."""
    nodes = []
    beats = []
    for i in range(3):
        nid = f"node_{i + 1}"
        nodes.append({"id": nid, "label": f"Step {i}", "summary": "", "kind": "process"})
        beats.append(
            {
                "beat_id": f"beat_{i:04d}",
                "index": i,
                "narration_text": f"step {i}",
                "highlight_node_ids": [nid],
            }
        )
    raw = {
        "version": "1",
        "representation_type": "flow",
        "topic": "No hints",
        "nodes": nodes,
        "edges": [],
        "beats": beats,
        "narration_segments": [],
        "metadata": {},
    }
    assert "layout_hints" not in raw
    v = validate_cir_v1(raw)
    assert v.ok, v.errors
    dumped = v.cir.model_dump(mode="json", by_alias=True) if v.cir else {}
    # Explicit None mirrors pydantic optional dump edge cases.
    dumped["layout_hints"] = None
    out = compile_cir_v1_to_timeline(
        cir=dumped,
        session_id="s",
        topic_id=None,
        concept="c",
    )
    assert out.timeline.get("timeline_id")
    assert len(out.timeline.get("beats") or []) == 3


def test_cycle_explicit_close_edge_avoids_duplicate_synth_close() -> None:
    raw = {
        "version": "1",
        "representation_type": "cycle",
        "topic": "Cycle close",
        "nodes": [
            {"id": "a", "label": "A", "summary": "", "kind": "process"},
            {"id": "b", "label": "B", "summary": "", "kind": "process"},
            {"id": "c", "label": "C", "summary": "", "kind": "process"},
        ],
        "edges": [
            {"from": "a", "to": "b", "relation": "leads_to"},
            {"from": "b", "to": "c", "relation": "leads_to"},
            {"from": "c", "to": "a", "relation": "leads_to"},
        ],
        "beats": [
            {
                "beat_id": "beat_0000",
                "index": 0,
                "narration_text": "A",
                "highlight_node_ids": ["a"],
            },
            {
                "beat_id": "beat_0001",
                "index": 1,
                "narration_text": "B",
                "highlight_node_ids": ["b"],
            },
            {
                "beat_id": "beat_0002",
                "index": 2,
                "narration_text": "C",
                "highlight_node_ids": ["c"],
            },
        ],
        "narration_segments": [],
        "metadata": {},
    }
    v = validate_cir_v1(raw)
    assert v.ok, v.errors
    dumped = v.cir.model_dump(mode="json", by_alias=True) if v.cir else {}
    out = compile_cir_v1_to_timeline(
        cir=dumped,
        session_id="s",
        topic_id=None,
        concept="c",
    )
    last_ops = out.timeline["beats"][-1]["operations"]
    close_ops = [
        o
        for o in last_ops
        if o.get("op_type") == "connect_entities"
        and (o.get("payload") or {}).get("to_id") == "a"
        and (o.get("payload") or {}).get("from_id") == "c"
    ]
    assert len(close_ops) == 1
    assert close_ops[0]["payload"]["edge_source"] == "cir"
    assert close_ops[0]["payload"]["edge_id"].startswith("edge_cir_")


def test_hierarchy_compile_unchanged_layout_profile() -> None:
    raw = photosynthesis_cir_v1()
    v = validate_cir_v1(raw)
    assert v.ok
    dumped = v.cir.model_dump(mode="json", by_alias=True) if v.cir else {}
    out = compile_cir_v1_to_timeline(
        cir=dumped,
        session_id="sess_h",
        topic_id=None,
        concept="photosynthesis",
    )
    lm = out.timeline.get("layout_metadata") or {}
    assert lm.get("layout_profile") == "hierarchy_root_children"
    assert lm.get("layout_profile") != "cycle_ring"


def _comparison_cir_v1() -> dict:
    nodes = [
        {
            "id": "left_h",
            "label": "Concept A",
            "summary": "",
            "kind": "concept",
            "semantic_role": "column_header",
            "preferred_position": "left_col",
        },
        {
            "id": "right_h",
            "label": "Concept B",
            "summary": "",
            "kind": "concept",
            "semantic_role": "column_header",
            "preferred_position": "right_col",
        },
        {
            "id": "left_r",
            "label": "Trait 1",
            "summary": "",
            "kind": "concept",
            "group": "left",
        },
        {
            "id": "right_r",
            "label": "Trait 1",
            "summary": "",
            "kind": "concept",
            "group": "right",
        },
    ]
    beats = [
        {
            "beat_id": f"beat_{i:04d}",
            "index": i,
            "narration_text": f"Step {i}",
            "highlight_node_ids": [nodes[i]["id"]],
        }
        for i in range(len(nodes))
    ]
    return {
        "version": "1",
        "representation_type": "comparison",
        "topic": "Generic comparison",
        "nodes": nodes,
        "beats": beats,
        "edges": [],
        "narration_segments": [],
    }


def test_beat_orchestration_bindings_on_compile() -> None:
    raw = photosynthesis_cir_v1()
    v = validate_cir_v1(raw)
    assert v.ok, v.errors
    dumped = v.cir.model_dump(mode="json", by_alias=True) if v.cir else {}
    out = compile_cir_v1_to_timeline(
        cir=dumped,
        session_id="sess_orch",
        topic_id=None,
        concept="photosynthesis",
    )
    beat0 = out.timeline["beats"][0]
    assert beat0["metadata"].get("orchestration_v1") is True
    assert len(beat0["narration_segments"]) == 1
    seg_id = beat0["narration_segments"][0]["segment_id"]
    assert all(b["segment_id"] == seg_id for b in beat0["bindings"])

    # Bindings track emitted operations only. Annotate may be skipped when
    # redundant with the label, so during_segment is not always present.
    relation_by_op = {
        "add_entity": "on_segment_start",
        "annotate_entity": "during_segment",
        "connect_entities": "on_segment_end",
        "highlight_entity": "after_segment",
    }
    ops = list(beat0.get("operations") or [])
    expected_relations = {
        relation_by_op[str(op.get("op_type"))]
        for op in ops
        if str(op.get("op_type")) in relation_by_op
    }
    relations = {b["relation"] for b in beat0["bindings"]}
    assert expected_relations <= relations
    assert "on_segment_start" in relations
    assert "after_segment" in relations

    seg_meta = beat0["narration_segments"][0].get("metadata") or {}
    assert seg_meta.get("reveal_offset_ms", 0) > 0
    assert seg_meta.get("pause_after_ms", 0) >= 0


def test_comparison_split_layout_profile_and_semantic_payload() -> None:
    raw = _comparison_cir_v1()
    v = validate_cir_v1(raw)
    assert v.ok, v.errors
    dumped = v.cir.model_dump(mode="json", by_alias=True) if v.cir else {}
    out = compile_cir_v1_to_timeline(
        cir=dumped,
        session_id="sess_cmp",
        topic_id=None,
        concept="compare",
    )
    lm = out.timeline.get("layout_metadata") or {}
    assert lm.get("layout_profile") == "comparison_split"
    assert lm.get("layout_mode") == "comparison_columns"
    assert lm.get("comparison_render_mode") == "row_aligned"
    assert lm.get("comparison_row_count", 0) >= 1

    entities = []
    annotate_targets: list[str] = []
    for beat in out.timeline["beats"]:
        for op in beat["operations"]:
            if op.get("op_type") == "add_entity":
                entities.append(op["payload"]["entity"])
            if op.get("op_type") == "annotate_entity":
                annotate_targets.append(op["payload"]["target_id"])

    left_h = next(e for e in entities if e["entity_id"] == "left_h")
    right_r = next(e for e in entities if e["entity_id"] == "right_r")
    assert left_h["semantic"]["payload"]["comparison_side"] == "left"
    assert left_h["semantic"]["payload"]["comparison_tier"] == "header"
    assert right_r["semantic"]["payload"]["comparison_side"] == "right"
    assert right_r["semantic"]["payload"]["comparison_tier"] == "row"
    assert right_r["semantic"]["payload"].get("row_detail")
    assert "right_r" not in annotate_targets
