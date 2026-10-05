"""CIR v1 ↔ TeachingPlan bridge (pass-through faithful)."""

from __future__ import annotations

import hashlib
from typing import Any, Optional

from app.vtse.models.plan import (
    BeatInteraction,
    PedagogicalRole,
    PacingMode,
    RevealScript,
    RevealStep,
    SemanticEdge,
    SemanticGraph,
    SemanticNode,
    TeachingBeat,
    TeachingPlan,
    TeachingStrategyRef,
)
from app.vtse.registry.strategy_registry import resolve_strategy_id_for_representation

_ROLE_BY_INDEX: tuple[PedagogicalRole, ...] = (
    "anchor",
    "explain",
    "explain",
    "emphasize",
    "connect",
    "reflect",
)


def _default_role(index: int) -> PedagogicalRole:
    if index < len(_ROLE_BY_INDEX):
        return _ROLE_BY_INDEX[index]
    return "explain"


def _pacing_for_index(index: int) -> PacingMode:
    if index == 0:
        return "deliver"
    if index == 1:
        return "reinforce"
    if index >= 3:
        return "visualize"
    return "reinforce"


def _stable_plan_id(cir: dict[str, Any]) -> str:
    topic = str(cir.get("topic") or "")
    rep = str(cir.get("representation_type") or "")
    n = len(cir.get("nodes") or [])
    b = len(cir.get("beats") or [])
    digest = hashlib.sha256(f"{topic}|{rep}|{n}|{b}".encode()).hexdigest()[:16]
    return f"plan_{digest}"


def _infer_reveal_script(
    beat: dict[str, Any],
    node_by_id: dict[str, dict[str, Any]],
) -> RevealScript:
    """Minimal reveal script mirroring current CIR compile choreography."""
    steps: list[RevealStep] = []
    focus = beat.get("focus_node_id")
    if not focus and beat.get("index") is not None:
        idx = int(beat["index"])
        nodes = list(node_by_id.keys())
        if idx < len(nodes):
            focus = nodes[idx]
    if focus:
        steps.append(RevealStep(kind="show_node", node_id=str(focus)))
    ann = beat.get("annotation_text")
    if ann and focus:
        steps.append(
            RevealStep(kind="annotate", target_id=str(focus), text=str(ann)),
        )
    for hid in beat.get("highlight_node_ids") or []:
        steps.append(RevealStep(kind="highlight", target_ids=[str(hid)]))
    return RevealScript(steps=steps)


def teaching_plan_from_cir_dict(
    cir: dict[str, Any],
    *,
    session_id: str = "",
    topic_id: str = "",
    concept_id: str = "",
    strategy_id: Optional[str] = None,
) -> TeachingPlan:
    """Lift validated CIR JSON into a TeachingPlan without semantic changes."""
    rep = str(cir.get("representation_type") or "flow")
    layout_hints = cir.get("layout_hints")
    if layout_hints is not None and not isinstance(layout_hints, dict):
        layout_hints = None
    nodes_raw = cir.get("nodes") or []
    sid = strategy_id or resolve_strategy_id_for_representation(
        rep,
        layout_hints=layout_hints,
        node_count=len(nodes_raw),
    )
    from app.vtse.registry.strategy_registry import get_strategy

    strat_def = get_strategy(sid)

    node_by_id: dict[str, dict[str, Any]] = {}
    nodes: list[SemanticNode] = []
    for n in nodes_raw:
        if not isinstance(n, dict):
            continue
        nid = str(n.get("id") or "")
        node_by_id[nid] = n
        nodes.append(
            SemanticNode(
                id=nid,
                label=str(n.get("label") or nid),
                summary=str(n.get("summary") or ""),
                kind=n.get("kind") or "concept",
                semantic_role=str(n.get("semantic_role") or ""),
                group=str(n.get("group") or ""),
                preferred_position=str(n.get("preferred_position") or ""),
                narration=str(n.get("narration") or ""),
            ),
        )

    edges: list[SemanticEdge] = []
    for e in cir.get("edges") or []:
        if not isinstance(e, dict):
            continue
        edges.append(
            SemanticEdge(
                from_id=str(e.get("from") or e.get("from_") or ""),
                to=str(e.get("to") or ""),
                relation=e.get("relation") or "leads_to",
            ),
        )

    beats_out: list[TeachingBeat] = []
    for b in cir.get("beats") or []:
        if not isinstance(b, dict):
            continue
        idx = int(b.get("index", 0))
        beat_id = str(b.get("beat_id") or f"beat_{idx + 1}")
        focus = b.get("focus_node_id")
        beats_out.append(
            TeachingBeat(
                beat_id=beat_id,
                index=idx,
                pedagogical_role=_default_role(idx),
                pacing_mode=_pacing_for_index(idx),
                focus_node_id=str(focus) if focus else None,
                narration_text=str(b.get("narration_text") or ""),
                annotation_text=b.get("annotation_text"),
                highlight_node_ids=[str(x) for x in (b.get("highlight_node_ids") or [])],
                reveal_script=_infer_reveal_script(b, node_by_id),
                interaction=BeatInteraction(),
                metadata={"source": "cir_v1"},
            ),
        )

    provenance = {
        "source": "cir_v1",
        "cir_version": cir.get("version"),
        "cir_metadata": dict(cir.get("metadata") or {}),
    }

    return TeachingPlan(
        plan_id=_stable_plan_id(cir),
        session_id=session_id,
        topic_id=topic_id,
        concept_id=concept_id,
        learning_objective=str(cir.get("topic") or ""),
        strategy=TeachingStrategyRef(
            strategy_id=sid,
            strategy_version=strat_def.version,
            layout_family=strat_def.layout_family,
        ),
        semantic_graph=SemanticGraph(
            representation_type=rep,  # type: ignore[arg-type]
            topic=str(cir.get("topic") or ""),
            nodes=nodes,
            edges=edges,
            layout_hints=layout_hints,
        ),
        beats=beats_out,
        provenance=provenance,
    )
