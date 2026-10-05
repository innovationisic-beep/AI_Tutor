from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import logging
import math
import os
from typing import Any, Iterable

logger = logging.getLogger(__name__)


def utc_iso_z(dt: datetime | None = None) -> str:
    """
    Canonical UTC instant for InstructionTimelineV3 and other JSON APIs.

    Zod v4 ``z.string().datetime()`` accepts only a ``Z`` suffix, not ``+00:00``.
    Python's ``datetime.isoformat()`` for UTC uses ``+00:00``, which fails validation.
    """
    d = dt if dt is not None else datetime.now(timezone.utc)
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    else:
        d = d.astimezone(timezone.utc)
    return d.isoformat().replace("+00:00", "Z")


def _node_hint(nodes_data: list[dict[str, Any]], i: int, key: str) -> str:
    raw = nodes_data[i].get(key) if i < len(nodes_data) else None
    if raw is None:
        return ""
    return str(raw).strip().lower()


def _comparison_node_semantic(
    node: dict[str, Any],
    idx: int,
    n: int,
    nodes_data: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Deterministic comparison side/tier hints for frontend ``comparison_split`` layout."""
    pref = str(node.get("preferred_position") or "").strip().lower()
    grp = str(node.get("group") or "").strip().lower()
    role = str(node.get("semantic_role") or "").strip().lower()
    summary = str(node.get("summary") or "").strip()
    header_labels: list[str] = []
    if nodes_data and len(nodes_data) >= 2:
        for header_idx in (0, 1):
            label = str(nodes_data[header_idx].get("label") or "").strip()
            if label:
                header_labels.append(label.lower())

    tier = "row"
    if "header" in role or role in ("column_header", "title"):
        tier = "header"

    side = "left"
    if "right" in pref or grp in ("right", "b", "right_col"):
        side = "right"
    elif "left" in pref or grp in ("left", "a", "left_col"):
        side = "left"
    else:
        left_n = max(1, (n + 1) // 2)
        side = "left" if idx < left_n else "right"

    pair_index: int | None = None
    if tier == "row" and idx >= 2:
        pair_index = max(0, (idx - 2) // 2)

    dimension: str | None = None
    row_detail = summary
    if tier == "row":
        if summary and ":" in summary:
            head, tail = summary.split(":", 1)
            head = head.strip()
            tail = tail.strip()
            if head and len(head.split()) <= 4 and head.lower() not in header_labels:
                dimension = head[:80]
            row_detail = (tail or summary).strip()[:500]
        elif summary:
            row_detail = summary[:500]
        else:
            row_detail = str(node.get("label") or "").strip()[:500]

    semantic_role = str(node.get("semantic_role") or "").strip() or (
        "comparison_header" if tier == "header" else "comparison_row"
    )
    payload: dict[str, Any] = {
        "comparison_side": side,
        "comparison_tier": tier,
        "pair_index": pair_index if pair_index is not None else idx,
    }
    if tier == "row":
        payload["row_detail"] = row_detail
    if dimension:
        payload["comparison_dimension"] = dimension
    return {
        "role": semantic_role,
        "payload": payload,
    }


def _flow_process_node_semantic(
    node: dict[str, Any],
    idx: int,
    n: int,
) -> dict[str, Any]:
    """Deterministic process-step hints for vertical storyboard rendering."""
    role = str(node.get("semantic_role") or "").strip() or "process_step"
    identity = str(node.get("label") or "").strip()
    explanation = str(node.get("summary") or "").strip()
    return {
        "role": role,
        "payload": {
            "process_tier": "step",
            "sequence_index": idx,
            "process_step_count": n,
            "step_display_label": f"Step {idx + 1}",
            "process_identity": identity[:80] if identity else None,
            "process_explanation": explanation[:600] if explanation else None,
        },
    }


def _flow_storyboard_annotation(label: str, annotation: str, summary: str) -> str:
    """Explanation panel text only — never duplicate identity in annotation."""
    ann = (annotation or summary or "").strip()
    if not ann:
        return ""
    low_label = label.strip().lower()
    low_ann = ann.lower()
    if low_ann == low_label:
        return ""
    if low_label and low_ann.startswith(low_label) and len(ann) - len(label) < 20:
        return ""
    return ann[:600]


def _hierarchy_node_semantic(
    node: dict[str, Any],
    idx: int,
    n: int,
) -> dict[str, Any]:
    """Concise branch identity + explanation payload (mirrors process storyboard contract)."""
    from app.vtse.strategies.hierarchy_layout import hierarchy_node_parts

    role = str(node.get("semantic_role") or "").strip() or (
        "anchor_root" if idx == 0 else "trait"
    )
    identity, explanation = hierarchy_node_parts(
        str(node.get("label") or ""),
        str(node.get("summary") or ""),
    )
    tier = "root" if idx == 0 else "branch"
    return {
        "role": role,
        "payload": {
            "hierarchy_tier": tier,
            "branch_index": idx - 1 if idx > 0 else None,
            "hierarchy_branch_count": max(0, n - 1),
            "hierarchy_identity": identity[:80] if identity else None,
            "hierarchy_explanation": explanation[:600] if explanation else None,
        },
    }


def _hierarchy_storyboard_annotation(label: str, annotation: str, summary: str) -> str:
    """Hierarchy explanation panel text — full content, no duplication, no trailing ellipsis."""
    ann = (annotation or summary or "").strip()
    if not ann:
        return ""
    low_label = label.strip().lower()
    low_ann = ann.lower()
    if low_ann == low_label:
        return ""
    if low_label and low_ann.startswith(low_label) and len(ann) - len(label) < 20:
        return ""
    # Strip trailing ellipsis added by LLM when it runs out of tokens
    import re as _re
    ann = _re.sub(r"\s*\.{2,}$", "", ann).strip()
    ann = ann.rstrip("…").strip()
    return ann[:800]  # generous limit — frontend box auto-sizes


def _annotation_redundant_with_label(label: str, annotation: str) -> bool:
    a = (annotation or "").strip().lower()
    b = (label or "").strip().lower()
    if not a or not b:
        return False
    if a == b:
        return True
    return a.startswith(b) and len(a) - len(b) < 24


def _compute_cir_node_positions(
    *,
    representation_type: str,
    nodes_data: list[dict[str, Any]],
    layout_hints: dict[str, Any] | None,
) -> tuple[list[tuple[int, int]], str]:
    """
    Returns (positions aligned to node index order, layout_mode token for metadata).
    """
    n = len(nodes_data)
    if n == 0:
        return [], "empty"
    hints = layout_hints or {}
    preferred_layout = str(hints.get("preferred_layout") or "").strip().lower()
    grouping_hint = str(hints.get("grouping") or "").strip().lower()

    groups: dict[str, list[int]] = {}
    for i in range(n):
        g = _node_hint(nodes_data, i, "group") or "_default"
        groups.setdefault(g, []).append(i)
    rep = representation_type or "flow"
    multi_group = len([k for k in groups if k != "_default"]) > 1
    hierarchy_layout = preferred_layout.startswith("hierarchy") or str(
        hints.get("hierarchy_layout_contract") or "",
    ).strip().lower().startswith("hierarchy")
    use_clusters = (
        rep != "hierarchy"
        and not hierarchy_layout
        and (multi_group or grouping_hint in ("cluster", "clustered", "grouped"))
    )

    cx, cy = 480, 520

    if rep == "comparison":
        left_n = (n + 1) // 2
        positions: list[tuple[int, int]] = []
        for idx in range(n):
            left = idx < left_n
            row = idx if left else idx - left_n
            x = 120 if left else 560
            y = 100 + row * 120
            positions.append((int(x), int(y)))
        return positions, "comparison_columns"

    if rep == "hierarchy" or hierarchy_layout:
        positions = [(0, 0)] * n
        positions[0] = (480, 110)
        if n == 1:
            return positions, "hierarchy_root_only"
        children = list(range(1, n))
        m = len(children)
        width_span = min(760, max(280, (m - 1) * 210))
        start_x = int(480 - width_span / 2)
        gap = int(width_span / max(m - 1, 1)) if m > 1 else 0
        for j, idx in enumerate(children):
            x = 480 if m == 1 else start_x + j * gap
            positions[idx] = (int(x), 330)
        return positions, "hierarchy_root_children"

    if use_clusters:
        keys = [k for k in groups if k != "_default"] or list(groups.keys())
        cols = max(len(keys), 1)
        col_w = 780 // cols
        positions = [(0, 0)] * n
        for gi, key in enumerate(keys):
            idxs = groups[key]
            mx = 60 + gi * col_w + col_w // 2
            for row, idx in enumerate(idxs):
                positions[idx] = (int(mx), 140 + row * 130)
        return positions, "grouped_clusters"

    if rep == "cycle":
        if n == 1:
            return [(cx, cy)], "cycle_radial"
        r = min(280, 95 + n * 34)
        positions = []
        for idx in range(n):
            theta = -math.pi / 2 + (2 * math.pi * idx / n)
            positions.append(
                (int(cx + r * math.cos(theta)), int(cy + r * math.sin(theta)))
            )
        return positions, "cycle_radial"

    if rep == "flow":
        process_vertical = preferred_layout in ("vertical_flow", "vertical", "column") or str(
            hints.get("process_render_mode") or "",
        ).strip().lower().startswith("vertical")
        if process_vertical:
            positions = []
            center_x = 220
            row_h = 118
            for idx in range(n):
                y = 56 + idx * row_h
                positions.append((int(center_x), int(y)))
            return positions, "vertical_process_phaseA"
        span = min(260, max(150, 700 // max(n, 1)))
        base_y = 360
        positions = []
        for idx in range(n):
            x = 80 + idx * span
            y = base_y + (idx % 3) * 48 - 48
            positions.append((int(x), int(y)))
        return positions, "flow_progression"

    # Fallback for unknown representation_type strings
    span = min(260, max(150, 700 // max(n, 1)))
    return (
        [(int(80 + idx * span), 360) for idx in range(n)],
        "flow_progression",
    )


_CIR_EDGE_RELATIONS = frozenset({"causes", "part_of", "leads_to", "requires"})


def _parse_cir_edges_for_compile(cir: dict[str, Any]) -> list[dict[str, str]]:
    """
    Normalize validated CIR edges for deterministic compile scheduling.

    Returns list of dicts: from, to, relation, edge_id (stable order).
    """
    nodes_raw = cir.get("nodes") or []
    node_index: dict[str, int] = {}
    node_set: set[str] = set()
    for i, raw in enumerate(nodes_raw):
        if not isinstance(raw, dict):
            continue
        nid = str(raw.get("id") or "").strip()
        if not nid:
            continue
        node_set.add(nid)
        node_index[nid] = i

    edges_raw = cir.get("edges") if isinstance(cir.get("edges"), list) else []
    seen_pairs: set[tuple[str, str]] = set()
    parsed: list[dict[str, str]] = []
    for i, raw in enumerate(edges_raw):
        if not isinstance(raw, dict):
            continue
        fr = str(raw.get("from") or raw.get("from_") or "").strip()
        to = str(raw.get("to") or "").strip()
        if fr not in node_set or to not in node_set or fr == to:
            continue
        pair = (fr, to)
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        rel = str(raw.get("relation") or "leads_to").strip()
        if rel not in _CIR_EDGE_RELATIONS:
            rel = "leads_to"
        parsed.append(
            {
                "from": fr,
                "to": to,
                "relation": rel,
                "edge_id": f"edge_cir_{i:02d}_{fr}_{to}"[:96],
                "_sort_to": node_index[to],
                "_sort_from": node_index[fr],
            }
        )
    parsed.sort(key=lambda e: (e["_sort_to"], e["_sort_from"], e["edge_id"]))
    for e in parsed:
        del e["_sort_to"]
        del e["_sort_from"]
    return parsed


def _cir_edges_for_introduction_beat(
    *,
    nid: str,
    introduced: set[str],
    cir_edges: list[dict[str, str]],
    emitted_pairs: set[tuple[str, str]],
) -> list[dict[str, str]]:
    """
    CIR edges to emit when node ``nid`` is introduced on this beat.

    - Incoming: to==nid and from already introduced.
    - Outgoing back-edge: from==nid and to already introduced (e.g. cycle close).
    """
    scheduled: list[dict[str, str]] = []
    for edge in cir_edges:
        fr = edge["from"]
        to = edge["to"]
        if (fr, to) in emitted_pairs:
            continue
        if to == nid and fr in introduced:
            scheduled.append(edge)
        elif fr == nid and to in introduced:
            scheduled.append(edge)
    return scheduled


@dataclass(frozen=True)
class TimelinePlannerResult:
    timeline: dict[str, Any]
    planner_source: str = "timeline_v3_native"
    """Concise observability for Zone 1 finalize / frontend debug strip."""
    cir_instruction_debug: dict[str, Any] | None = None


class TimelinePlannerV3:
    """
    Compile validated CIR (and incremental overlays) into InstructionTimelineV3.

    Production Zone 1 openings use VTSE → CIR → ``compile_cir_v1_to_timeline``.
    Micro turns use ``plan_zone1_incremental``.
    """

    def __init__(self, planner_version: str = "v3.2.2-minimal") -> None:
        self._planner_version = planner_version

    def compile_cir_v1_to_timeline(
        self,
        *,
        cir: dict[str, Any],
        session_id: str,
        topic_id: str | None,
        concept: str,
        from_llm: bool = False,
    ) -> TimelinePlannerResult:
        """
        Map validated CIR v1 into the existing native InstructionTimelineV3 dict.

        Caller must run ``validate_cir_v1`` first; this method assumes a coherent
        document (equal node/beat counts, contiguous indices).
        """
        nodes_data: list[dict[str, Any]] = list(cir["nodes"])
        beats_raw: list[dict[str, Any]] = sorted(
            cir["beats"], key=lambda b: int(b["index"])
        )
        rep = str(cir.get("representation_type") or "flow")

        canonical_key = f"cir:{rep}:{cir.get('topic', '')}"
        timeline_id = f"tlm_{self._stable_short_id(session_id, canonical_key)}"

        raw_lh = cir.get("layout_hints")
        layout_hints_dict: dict[str, Any] | None = (
            dict(raw_lh) if isinstance(raw_lh, dict) else None
        )
        node_positions, layout_mode = _compute_cir_node_positions(
            representation_type=rep,
            nodes_data=nodes_data,
            layout_hints=layout_hints_dict,
        )

        beats_out: list[dict[str, Any]] = []
        prev_highlight_op_id: str | None = None
        op_counter = 1
        n = len(nodes_data)
        cir_edges_parsed = _parse_cir_edges_for_compile(cir)
        emitted_edge_pairs: set[tuple[str, str]] = set()
        edges_from_cir = 0
        edges_synthesized = 0

        for idx, beat in enumerate(beats_raw):
            beat_id = str(beat["beat_id"])
            nid = str(nodes_data[idx]["id"])
            label = str(nodes_data[idx]["label"])
            summary = str(nodes_data[idx].get("summary") or "")
            narration = str(beat.get("narration_text") or "").strip() or str(
                nodes_data[idx].get("narration") or ""
            ).strip() or str(nodes_data[idx].get("label") or "Step")
            ann = beat.get("annotation_text")
            if ann is not None and str(ann).strip():
                annotation = str(ann).strip()
            else:
                sup = str(nodes_data[idx].get("supporting_material") or "").strip()
                nar = str(nodes_data[idx].get("narration") or "").strip()
                annotation = (sup or nar or summary)[:500]

            x, y = node_positions[idx] if idx < len(node_positions) else (80 + idx * 240, 120)

            semantic_data = (
                _comparison_node_semantic(nodes_data[idx], idx, n, nodes_data)
                if rep == "comparison"
                else _flow_process_node_semantic(nodes_data[idx], idx, n)
                if rep == "flow"
                else _hierarchy_node_semantic(nodes_data[idx], idx, n)
                if rep == "hierarchy"
                else None
            )
            skip_row_annotate = (
                rep == "comparison"
                and semantic_data is not None
                and semantic_data.get("payload", {}).get("comparison_tier") in ("row", "header")
            )
            if rep == "flow":
                annotation = _flow_storyboard_annotation(label, annotation, summary)
            elif rep == "hierarchy":
                if semantic_data is not None:
                    payload = semantic_data.get("payload") or {}
                    identity = str(payload.get("hierarchy_identity") or "").strip()
                    if identity:
                        label = identity
                annotation = _hierarchy_storyboard_annotation(label, annotation, summary)
            skip_flow_annotate = rep == "flow" and not str(annotation or "").strip()
            skip_hierarchy_annotate = (
                rep == "hierarchy"
                and (
                    idx == 0  # root node never gets annotation — identity only
                    or not str(annotation or "").strip()
                    or _annotation_redundant_with_label(label, annotation)
                )
            )
            skip_annotate = skip_row_annotate or skip_flow_annotate or skip_hierarchy_annotate

            ops: list[dict[str, Any]] = []

            add_op_id = self._op_id(op_counter)
            op_counter += 1
            ops.append(
                self._add_entity_op(
                    operation_id=add_op_id,
                    beat_id=beat_id,
                    entity=self._node_entity(
                        entity_id=nid,
                        label=label,
                        x=x,
                        y=y,
                        created_by_op=add_op_id,
                        semantic=semantic_data,
                    ),
                    depends_on=[],
                )
            )

            introduced_before = set(
                str(nodes_data[j]["id"]) for j in range(idx)
            )
            cir_scheduled = _cir_edges_for_introduction_beat(
                nid=nid,
                introduced=introduced_before,
                cir_edges=cir_edges_parsed,
                emitted_pairs=emitted_edge_pairs,
            )
            connect_dep = add_op_id
            for edge_def in cir_scheduled:
                connect_op_id = self._op_id(op_counter)
                op_counter += 1
                fr_id = edge_def["from"]
                to_id = edge_def["to"]
                ops.append(
                    self._connect_entities_op(
                        operation_id=connect_op_id,
                        beat_id=beat_id,
                        from_id=fr_id,
                        to_id=to_id,
                        edge_id=edge_def["edge_id"],
                        relation=edge_def["relation"],
                        edge_source="cir",
                        depends_on=[connect_dep],
                    )
                )
                connect_dep = connect_op_id
                emitted_edge_pairs.add((fr_id, to_id))
                edges_from_cir += 1

            incoming_cir_to_nid = [e for e in cir_scheduled if e["to"] == nid]
            if (
                idx > 0
                and rep in {"hierarchy", "flow", "cycle"}
                and not incoming_cir_to_nid
            ):
                connect_op_id = self._op_id(op_counter)
                op_counter += 1
                prev_id = str(nodes_data[idx - 1]["id"])
                root_id = str(nodes_data[0]["id"])
                if rep == "flow" or rep == "cycle":
                    from_id, to_id = prev_id, nid
                    synth_relation = "leads_to"
                else:
                    from_id, to_id = root_id, nid
                    synth_relation = "part_of"
                synth_pair = (from_id, to_id)
                if synth_pair not in emitted_edge_pairs:
                    ops.append(
                        self._connect_entities_op(
                            operation_id=connect_op_id,
                            beat_id=beat_id,
                            from_id=from_id,
                            to_id=to_id,
                            edge_id=f"edge_{idx}",
                            relation=synth_relation,
                            edge_source="synthesized",
                            depends_on=[connect_dep],
                        )
                    )
                    connect_dep = connect_op_id
                    emitted_edge_pairs.add(synth_pair)
                    edges_synthesized += 1

            annotate_depends = [ops[-1]["operation_id"]] if ops else []
            if skip_annotate:
                annotate_op_id = ops[-1]["operation_id"]
            else:
                annotate_op_id = self._op_id(op_counter)
                op_counter += 1
                ops.append(
                    self._annotate_entity_op(
                        operation_id=annotate_op_id,
                        beat_id=beat_id,
                        target_id=nid,
                        annotation_id=f"ann_{idx + 1}",
                        text=annotation[:800],
                        depends_on=annotate_depends,
                    )
                )

            hl_raw = beat.get("highlight_node_ids") or []
            highlight_targets = [str(x) for x in hl_raw] if hl_raw else [nid]

            highlight_op_id = self._op_id(op_counter)
            op_counter += 1
            highlight_depends = [annotate_op_id]
            if prev_highlight_op_id:
                highlight_depends.append(prev_highlight_op_id)
            ops.append(
                self._highlight_entity_op(
                    operation_id=highlight_op_id,
                    beat_id=beat_id,
                    highlight_id=f"hl_{idx + 1}",
                    target_ids=highlight_targets,
                    depends_on=highlight_depends,
                )
            )
            prev_highlight_op_id = highlight_op_id

            if rep == "cycle" and n > 1 and idx == n - 1:
                last_id = str(nodes_data[-1]["id"])
                first_id = str(nodes_data[0]["id"])
                close_pair = (last_id, first_id)
                if close_pair not in emitted_edge_pairs:
                    cycle_close_id = self._op_id(op_counter)
                    op_counter += 1
                    ops.append(
                        self._connect_entities_op(
                            operation_id=cycle_close_id,
                            beat_id=beat_id,
                            from_id=last_id,
                            to_id=first_id,
                            edge_id="edge_cycle_close",
                            relation="leads_to",
                            edge_source="synthesized",
                            depends_on=[highlight_op_id],
                        )
                    )
                    emitted_edge_pairs.add(close_pair)
                    edges_synthesized += 1

            pacing_mode = (
                "deliver"
                if idx == 0
                else ("reinforce" if idx == 1 else "visualize")
            )
            beats_out.append(
                self._beat(
                    beat_id=beat_id,
                    index=idx,
                    pacing_mode=pacing_mode,
                    goal=f"Explain: {label}",
                    operations=ops,
                    narration=narration,
                )
            )

        if rep == "cycle":
            layout_profile = "cycle_ring"
        elif rep == "comparison":
            layout_profile = "comparison_split"
        elif rep == "flow" and layout_mode == "vertical_process_phaseA":
            layout_profile = "vertical_process_phaseA"
        elif rep == "hierarchy":
            layout_profile = (
                "hierarchy_root_children"
                if layout_mode != "hierarchy_root_only"
                else "hierarchy_root_only"
            )
        else:
            layout_profile = layout_mode

        hierarchy_layout_meta: dict[str, Any] = {}
        process_phase_a: dict[str, Any] = {}
        if rep == "flow":
            cir_meta = cir.get("metadata") or {}
            vtse_meta = cir_meta.get("vtse") if isinstance(cir_meta.get("vtse"), dict) else {}
            plan_summary = vtse_meta.get("plan_summary") if isinstance(vtse_meta.get("plan_summary"), dict) else {}
            phase_src = plan_summary.get("process_phase_a") if isinstance(plan_summary.get("process_phase_a"), dict) else {}
            storyboard_src = plan_summary.get("process_storyboard") if isinstance(
                plan_summary.get("process_storyboard"), dict
            ) else phase_src
            lh = layout_hints_dict or {}
            process_phase_a = {
                "process_render_mode": str(
                    lh.get("process_render_mode") or "process_storyboard_lanes",
                ),
                "storyboard_lane_mode": str(
                    lh.get("storyboard_lane_mode")
                    or storyboard_src.get("storyboard_lane_mode")
                    or "center_node_right_explanation",
                ),
                "process_step_count": int(
                    storyboard_src.get("process_step_count") or phase_src.get("process_step_count") or n,
                ),
                "rendered_process_steps": n,
                "process_scene_count": int(
                    storyboard_src.get("process_scene_count") or phase_src.get("process_scene_count") or n,
                ),
                "explanation_panel_count": int(storyboard_src.get("explanation_panel_count") or n),
                "filtered_placeholder_count": int(
                    storyboard_src.get("filtered_placeholder_count")
                    or phase_src.get("filtered_placeholder_count")
                    or 0,
                ),
                "filtered_practice_nodes": int(
                    storyboard_src.get("filtered_practice_nodes")
                    or phase_src.get("filtered_practice_nodes")
                    or 0,
                ),
                "duplicate_content_suppressed": int(
                    storyboard_src.get("duplicate_content_suppressed") or 0,
                ),
                "dynamic_process_length": True,
                "layout_mode": layout_mode,
                "semantic_shape": str(
                    storyboard_src.get("semantic_shape") or phase_src.get("semantic_shape") or "linear_process",
                ),
                "edge_routing_policy": "vertical_sequential_compact",
            }
        cir_edge_count = len(cir_edges_parsed)
        if rep == "hierarchy":
            from app.vtse.strategies.hierarchy_layout import hierarchy_plan_observability

            lh = layout_hints_dict or {}
            sibling_chain = sum(
                1
                for e in cir_edges_parsed
                if str(e.get("relation") or "") == "leads_to"
            )
            contract = str(
                lh.get("hierarchy_layout_contract") or lh.get("preferred_layout") or layout_mode,
            )
            hierarchy_layout_meta = hierarchy_plan_observability(
                node_count=n,
                edge_count=cir_edge_count,
                layout_contract=contract,
                sibling_chain_edges=sibling_chain,
            )
            hierarchy_layout_meta["layout_mode"] = layout_mode
            hierarchy_layout_meta["edge_routing_policy"] = "root_trunk_to_children"
        config_hash = self._sha(f"planner-config:cir-v1:{rep}:{layout_mode}")
        timeline = {
            "schema_version": "3.0.0",
            "timeline_id": timeline_id,
            "session_id": session_id,
            "topic_id": topic_id or "",
            "concept_id": concept or canonical_key,
            "timeline_kind": "opening_arc",
            "created_at": utc_iso_z(),
            "planner": {
                "planner_version": self._planner_version,
                "planner_model": "cir-v1-compile",
                "planner_config_hash": config_hash,
            },
            "determinism": {
                "layout_seed": int(self._sha(canonical_key)[7:15], 16),
                "initial_scene_hash": self._sha("scene:bootstrap:empty"),
                "expected_final_scene_hash": self._sha(
                    f"scene:expected:cir:{canonical_key}:{n}"
                ),
            },
            "global_sync_policy": {
                "clock_mode": "timer_only",
                "fallback_clock_mode": "timer_only",
                "min_delay_ms": 350,
                "max_silence_before_fallback_ms": 1500,
            },
            "scene_bootstrap": {"entities": {}, "root_order": []},
            "beats": beats_out,
            "layout_metadata": {
                "layout_profile": layout_profile,
                "layout_mode": layout_mode,
                "viewport": {"min_width": 960, "min_height": 540},
                "spacing_tokens": {"node_gap": 220, "section_gap": 64},
                "constraints_hash": self._sha(f"layout:cir:{rep}:{n}:{layout_mode}"),
                **(
                    {
                        "comparison_render_mode": "row_aligned",
                        "comparison_row_count": max(0, (n - 2 + 1) // 2),
                        "detached_annotation_count": 0,
                    }
                    if rep == "comparison"
                    else process_phase_a
                    if rep == "flow"
                    else hierarchy_layout_meta
                    if rep == "hierarchy"
                    else {}
                ),
            },
            "replay_metadata": {
                "snapshot_interval_ops": 20,
                "record_event_log": True,
                "hash_algorithm": "sha256",
                "replay_mode_default": "exact_timing",
            },
            "compatibility": {
                "source_pipeline": "native_v3",
                "legacy_payload_ref": "cir_v1",
            },
            "metadata": {
                "cir_version": cir.get("version"),
                "representation_type": rep,
                "mode": "cir_v1_compile",
                "cir_compile_source": "llm" if from_llm else "template_or_manual",
                "cir_layout_mode": layout_mode,
                "ops_supported": [
                    "add_entity",
                    "connect_entities",
                    "annotate_entity",
                    "highlight_entity",
                ],
            },
        }
        src = (
            "timeline_v3_from_cir_llm_v1"
            if from_llm
            else "timeline_v3_from_cir_v1"
        )
        edge_source = "cir" if edges_from_cir and not edges_synthesized else (
            "synthesized" if edges_synthesized and not edges_from_cir else "mixed"
        )
        if not edges_from_cir and not edges_synthesized:
            edge_source = "none"
        cir_instruction_debug: dict[str, Any] = {
            "planner_source": src,
            "representation_type": rep,
            "node_count": n,
            "edge_count": cir_edge_count,
            "edges_emitted_from_cir": edges_from_cir,
            "edges_emitted_synthesized": edges_synthesized,
            "edge_compile_source": edge_source,
            "fallback_used": False,
            "layout_mode": layout_mode,
        }
        if rep == "hierarchy" and hierarchy_layout_meta:
            cir_instruction_debug.update(hierarchy_layout_meta)
        return TimelinePlannerResult(
            timeline=timeline,
            planner_source=src,
            cir_instruction_debug=cir_instruction_debug,
        )

    def plan_zone1_incremental(
        self,
        *,
        prior_timeline: dict[str, Any],
        next_beat_index: int,
        goal: str,
        narration: str,
        focus_entity_id: str,
        annotation_text: str,
        pacing_mode: str = "question",
    ) -> TimelinePlannerResult:
        """
        Single beat: annotate + highlight on an existing entity. Returns a merge
        fragment ``{timeline_id, beats: [one]}`` matching ``prior_timeline``.
        """
        tid = str(prior_timeline.get("timeline_id") or "")
        beat_id = f"beat_{int(next_beat_index):04d}"
        op_counter = 50_000 + int(next_beat_index) * 10
        annotate_op_id = self._op_id(op_counter)
        op_counter += 1
        highlight_op_id = self._op_id(op_counter)
        ops: list[dict[str, Any]] = [
            self._annotate_entity_op(
                operation_id=annotate_op_id,
                beat_id=beat_id,
                target_id=focus_entity_id,
                annotation_id=f"ann_inc_{next_beat_index}",
                text=str(annotation_text or "")[:500],
                depends_on=[],
            ),
            self._highlight_entity_op(
                operation_id=highlight_op_id,
                beat_id=beat_id,
                highlight_id=f"hl_inc_{next_beat_index}",
                target_ids=[focus_entity_id],
                depends_on=[annotate_op_id],
            ),
        ]
        beat = self._beat(
            beat_id=beat_id,
            index=int(next_beat_index),
            pacing_mode=pacing_mode,
            goal=str(goal or "")[:500],
            operations=ops,
            narration=str(narration or "")[:800],
        )
        return TimelinePlannerResult(
            timeline={"timeline_id": tid, "beats": [beat]},
            planner_source="timeline_v3_incremental",
            cir_instruction_debug={
                "planner_source": "timeline_v3_incremental",
                "representation_type": "incremental",
                "node_count": 0,
                "edge_count": 0,
                "fallback_used": False,
                "layout_mode": "incremental_overlay",
            },
        )

    @staticmethod
    def _bindings_for_beat_orchestration(
        beat_id: str,
        segment_id: str,
        operations: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """
        One narration segment per beat; operations choreographed by relation.

        add_entity → on_segment_start; annotate_entity → during_segment;
        connect_entities → on_segment_end; highlight_entity → after_segment.
        """
        relation_by_op: dict[str, str] = {
            "add_entity": "on_segment_start",
            "annotate_entity": "during_segment",
            "connect_entities": "on_segment_end",
            "highlight_entity": "after_segment",
        }
        bindings: list[dict[str, Any]] = []
        bind_idx = 0
        for op in operations:
            op_type = str(op.get("op_type") or "")
            relation = relation_by_op.get(op_type)
            if not relation:
                continue
            bindings.append(
                {
                    "binding_id": f"bind_{beat_id}_{bind_idx:02d}",
                    "segment_id": segment_id,
                    "operation_id": op["operation_id"],
                    "relation": relation,
                }
            )
            bind_idx += 1
        if not bindings and operations:
            bindings.append(
                {
                    "binding_id": f"bind_{beat_id}_00",
                    "segment_id": segment_id,
                    "operation_id": operations[0]["operation_id"],
                    "relation": "on_segment_start",
                }
            )
        return bindings

    def _beat(
        self,
        *,
        beat_id: str,
        index: int,
        pacing_mode: str,
        goal: str,
        operations: list[dict[str, Any]],
        narration: str,
    ) -> dict[str, Any]:
        segment_id = f"seg_{beat_id}"
        bindings = self._bindings_for_beat_orchestration(
            beat_id, segment_id, operations
        )
        orchestrated = len(bindings) > 1
        return {
            "beat_id": beat_id,
            "index": index,
            "pacing_mode": pacing_mode,
            "pedagogy": {
                "zone": 1,
                "goal": goal,
                "difficulty_profile": "low",
                "interaction_expected": False,
            },
            "sync": {
                "completion_policy": "all_ops_and_narration_done",
                "allow_parallel_ops": False,
                "barrier_after_beat": True,
            },
            "operations": operations,
            "narration_segments": [
                {
                    "segment_id": segment_id,
                    "beat_id": beat_id,
                    "text": narration,
                    "speech": {
                        "required": True,
                        "interruptible": False,
                    },
                    "timing": {
                        "mode": "timer_only",
                        "min_visible_ms": 300,
                        "fallback_delay_ms": 450,
                    },
                    "anchor": "during_ops",
                    "metadata": {
                        "orchestration_v1": True,
                        "pause_after_ms": 280,
                        "reveal_offset_ms": 360,
                        "reveal_during_speech": True,
                    },
                }
            ],
            "bindings": bindings,
            "interaction_gate": {
                "type": "none",
                "required": False,
                "resume_policy": "continue_same_timeline",
            },
            "metadata": {
                "narration_bound": True,
                "orchestration_v1": orchestrated,
            },
        }

    def _node_entity(
        self,
        *,
        entity_id: str,
        label: str,
        x: int,
        y: int,
        created_by_op: str,
        semantic: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "entity_id": entity_id,
            "entity_type": "Node",
            "kind": "primitive",
            "version": 1,
            "spatial": {"x": x, "y": y, "w": 180, "h": 90},
            "semantic": semantic or {"role": "concept_step"},
            "render": {"layer": 2, "style_token": "concept-node", "visible": True},
            "lifecycle": {"state": "active", "created_by_op": created_by_op},
            "label": label,
        }

    def _add_entity_op(
        self,
        *,
        operation_id: str,
        beat_id: str,
        entity: dict[str, Any],
        depends_on: Iterable[str],
    ) -> dict[str, Any]:
        return self._op_base(
            operation_id=operation_id,
            beat_id=beat_id,
            op_type="add_entity",
            depends_on=list(depends_on),
            payload={"entity": entity},
        )

    def _connect_entities_op(
        self,
        *,
        operation_id: str,
        beat_id: str,
        from_id: str,
        to_id: str,
        edge_id: str,
        depends_on: Iterable[str],
        relation: str | None = None,
        edge_source: str = "synthesized",
    ) -> dict[str, Any]:
        rel = (relation or "leads_to").strip()
        if rel not in _CIR_EDGE_RELATIONS:
            rel = "leads_to"
        style = {
            "causes": "concept-edge-cause",
            "part_of": "concept-edge-part",
            "leads_to": "concept-edge",
            "requires": "concept-edge-require",
        }.get(rel, "concept-edge")
        payload: dict[str, Any] = {
            "edge_id": edge_id,
            "from_id": from_id,
            "to_id": to_id,
            "style_token": style,
            "relation": rel,
            "edge_source": edge_source,
        }
        return self._op_base(
            operation_id=operation_id,
            beat_id=beat_id,
            op_type="connect_entities",
            depends_on=list(depends_on),
            targets=[from_id, to_id],
            payload=payload,
        )

    def _annotate_entity_op(
        self,
        *,
        operation_id: str,
        beat_id: str,
        target_id: str,
        annotation_id: str,
        text: str,
        depends_on: Iterable[str],
    ) -> dict[str, Any]:
        return self._op_base(
            operation_id=operation_id,
            beat_id=beat_id,
            op_type="annotate_entity",
            depends_on=list(depends_on),
            targets=[target_id],
            payload={
                "annotation_id": annotation_id,
                "target_id": target_id,
                "text": text,
                "style_token": "concept-annotation",
            },
        )

    def _highlight_entity_op(
        self,
        *,
        operation_id: str,
        beat_id: str,
        highlight_id: str,
        target_ids: list[str],
        depends_on: Iterable[str],
    ) -> dict[str, Any]:
        return self._op_base(
            operation_id=operation_id,
            beat_id=beat_id,
            op_type="highlight_entity",
            depends_on=list(depends_on),
            targets=target_ids,
            payload={
                "highlight_id": highlight_id,
                "target_ids": target_ids,
                "style_token": "concept-highlight",
                "ttl_ms": 800,
            },
        )

    def _op_base(
        self,
        *,
        operation_id: str,
        beat_id: str,
        op_type: str,
        depends_on: list[str],
        payload: dict[str, Any],
        targets: list[str] | None = None,
    ) -> dict[str, Any]:
        out: dict[str, Any] = {
            "operation_id": operation_id,
            "op_type": op_type,
            "beat_id": beat_id,
            "depends_on": sorted(depends_on),
            "payload": payload,
            "sync": {"execution_mode": "instant_commit", "binding_mode": "on_segment_start"},
            "reversibility": {"reversible": True, "inverse_op_type": None},
            "preconditions": [],
            "postconditions": [],
            "determinism_key": self._sha(f"{beat_id}:{operation_id}:{op_type}:{payload}"),
        }
        if targets:
            out["targets"] = targets
        return out

    def _op_id(self, n: int) -> str:
        return f"op_{n:06d}"

    def _sha(self, text: str) -> str:
        return f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"

    def _stable_short_id(self, session_id: str, canonical: str) -> str:
        digest = hashlib.sha256(f"{session_id}:{canonical}".encode("utf-8")).hexdigest()
        return digest[:12]
