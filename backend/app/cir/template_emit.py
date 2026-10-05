"""Emit CIR v1 from minimal template step rows (test/fixture helper)."""

from __future__ import annotations

from typing import Any, Literal

RepresentationTypeV1 = Literal["hierarchy", "flow", "comparison"]


def cir_v1_dict_from_template_steps(
    *,
    representation_type: RepresentationTypeV1,
    topic: str,
    canonical_tag: str,
    steps: list[dict[str, str]],
) -> dict[str, Any]:
    """
    Build a CIR v1 dict from step rows with title/annotation/narration.

    Node ids follow ``node_1..node_N`` so compile and incremental ops can target them.
    """
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    beats: list[dict[str, Any]] = []
    narration_segments: list[dict[str, Any]] = []

    for i, step in enumerate(steps):
        nid = f"node_{i + 1}"
        nodes.append(
            {
                "id": nid,
                "label": step["title"],
                "summary": step["annotation"],
                "kind": "process",
            }
        )
        bid = f"beat_{i:04d}"
        beats.append(
            {
                "beat_id": bid,
                "index": i,
                "narration_text": step["narration"],
                "annotation_text": step["annotation"],
                "highlight_node_ids": [nid],
            }
        )
        narration_segments.append(
            {
                "segment_id": f"seg_{bid}",
                "beat_id": bid,
                "text": step["narration"],
            }
        )

    for j in range(1, len(nodes)):
        root = nodes[0]["id"]
        child = nodes[j]["id"]
        if representation_type == "flow":
            prev = nodes[j - 1]["id"]
            edges.append({"from": prev, "to": child, "relation": "leads_to"})
        else:
            edges.append({"from": root, "to": child, "relation": "part_of"})

    return {
        "version": "1",
        "representation_type": representation_type,
        "topic": topic,
        "nodes": nodes,
        "edges": edges,
        "beats": beats,
        "narration_segments": narration_segments,
        "metadata": {"canonical_tag": canonical_tag, "source": "template_emit"},
    }


# Backward-friendly alias for callers / package exports
cir_v1_from_planner_steps = cir_v1_dict_from_template_steps
