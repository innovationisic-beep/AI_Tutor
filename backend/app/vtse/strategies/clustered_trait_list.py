"""clustered_trait_list — deterministic TeachingPlan authoring (hierarchy tree)."""

from __future__ import annotations

import hashlib
from typing import Any

from app.vtse.authoring.semantic_extract import AuthoringSemanticDraft, TraitDraft
from app.vtse.models.plan import (
    BeatInteraction,
    InteractionPolicy,
    MicroQuestionIntent,
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
from app.vtse.registry.strategy_registry import get_strategy
from app.services.vtse_visuals.slots import make_vtse_slot, trait_slot_key
from app.vtse.strategies.hierarchy_layout import (
    hierarchy_layout_hints,
    hierarchy_node_parts,
    hierarchy_plan_observability,
)

STRATEGY_ID = "clustered_trait_list"


def _stable_plan_id(key: str) -> str:
    digest = hashlib.sha256(key.encode()).hexdigest()[:16]
    return f"plan_ctl_{digest}"


def _node_id(index: int) -> str:
    return f"node_{index + 1}"


def _beat_id(index: int) -> str:
    return f"beat_{index:04d}"


def _pacing_for_role(role: PedagogicalRole) -> PacingMode:
    mapping: dict[PedagogicalRole, PacingMode] = {
        "anchor": "deliver",
        "explain": "deliver",
        "reinforce": "reinforce",
        "emphasize": "visualize",
        "reflect": "reflect",
        "connect": "reinforce",
        "close": "close",
    }
    return mapping.get(role, "deliver")


def _hierarchy_explanation_text(label: str, summary: str, narration: str) -> str:
    """Explanation lane text — never duplicate concise node identity."""
    _identity, explanation = hierarchy_node_parts(label, summary)
    if explanation.strip():
        return explanation
    nar = (narration or "").strip()
    if nar and nar.lower() != _identity.strip().lower():
        return nar[:600]
    return ""


def _reveal_script(
    focus_id: str,
    annotation_text: str | None,
    highlight_ids: list[str],
) -> RevealScript:
    steps: list[RevealStep] = [RevealStep(kind="show_node", node_id=focus_id)]
    if annotation_text and str(annotation_text).strip():
        steps.append(
            RevealStep(kind="annotate", target_id=focus_id, text=str(annotation_text).strip()),
        )
    for hid in highlight_ids:
        steps.append(RevealStep(kind="highlight", target_ids=[hid]))
    return RevealScript(steps=steps)


def _role_for_flat_index(index: int, total: int) -> PedagogicalRole:
    if index == 0:
        return "anchor"
    if index == total - 1 and total >= 4:
        return "emphasize"
    return "explain" if index % 2 == 1 else "reinforce"


def _tree_edges_from_root(root_id: str, child_ids: list[str]) -> list[SemanticEdge]:
    return [
        SemanticEdge(from_id=root_id, to=cid, relation="part_of") for cid in child_ids
    ]


def build_clustered_trait_list_plan_flat(
    *,
    topic_label: str,
    traits: tuple[TraitDraft, ...],
    session_id: str = "",
    topic_id: str = "",
    concept_id: str = "",
    authoring_source: str = "vtse_clustered_trait_list_flat_v1",
) -> TeachingPlan:
    """Root + child branches (flat trait list → hierarchy tree, no sibling chain)."""
    strat = get_strategy(STRATEGY_ID)
    n = len(traits)
    if n < 3 or n > 7:
        raise ValueError(f"clustered_trait_list flat mode requires 3–7 traits, got {n}")

    root_id = _node_id(0)
    nodes: list[SemanticNode] = []
    for i, trait in enumerate(traits):
        identity, explanation = hierarchy_node_parts(trait.label, trait.summary)
        nodes.append(
            SemanticNode(
                id=_node_id(i),
                label=identity or trait.label,
                summary=explanation or trait.summary,
                kind="concept" if i == 0 else "property",
                semantic_role="anchor_root" if i == 0 else "trait",
                group="hierarchy",
                preferred_position="root" if i == 0 else ("left" if i % 2 else "right"),
                narration=trait.narration,
            ),
        )

    child_ids = [_node_id(i) for i in range(1, n)]
    edges = _tree_edges_from_root(root_id, child_ids)

    beats: list[TeachingBeat] = []
    for i, trait in enumerate(traits):
        nid = _node_id(i)
        role = _role_for_flat_index(i, n)
        identity, _ = hierarchy_node_parts(trait.label, trait.summary)
        ann = _hierarchy_explanation_text(trait.label, trait.summary, trait.narration)
        interaction = BeatInteraction()
        if role == "reflect":
            interaction = BeatInteraction(
                micro_question=MicroQuestionIntent(
                    prompt="What trait matters most here?",
                    kind="reflect",
                ),
            )
        beats.append(
            TeachingBeat(
                beat_id=_beat_id(i),
                index=i,
                pedagogical_role=role,
                pacing_mode=_pacing_for_role(role),
                focus_node_id=nid,
                narration_text=trait.narration,
                annotation_text=ann or None,
                highlight_node_ids=[nid],
                reveal_script=_reveal_script(nid, ann or None, [nid]),
                interaction=interaction,
                metadata={
                    "authoring_source": authoring_source,
                    "vtse_slot": make_vtse_slot(
                        slot_kind="trait",
                        slot_key=trait_slot_key(trait.label),
                        slot_index=i + 1,
                        label=trait.label,
                    ),
                },
            ),
        )

    layout_contract = "hierarchy_root_children"
    key = topic_label + "|" + "|".join(t.label for t in traits)
    return TeachingPlan(
        plan_id=_stable_plan_id(key),
        session_id=session_id,
        topic_id=topic_id,
        concept_id=concept_id,
        learning_objective=topic_label,
        strategy=TeachingStrategyRef(
            strategy_id=STRATEGY_ID,
            strategy_version=strat.version,
            layout_family=strat.layout_family,
        ),
        semantic_graph=SemanticGraph(
            representation_type="hierarchy",
            topic=topic_label,
            nodes=nodes,
            edges=edges,
            layout_hints=hierarchy_layout_hints(contract=layout_contract),
        ),
        beats=beats,
        provenance={
            "authoring_source": authoring_source,
            "plan_summary": {
                "mode": "flat",
                "trait_count": n,
                "trait_labels": [t.label for t in traits],
                "hierarchy_layout": hierarchy_plan_observability(
                    node_count=n,
                    edge_count=len(edges),
                    layout_contract=layout_contract,
                ),
            },
        },
    )


def build_clustered_trait_list_plan(
    draft: AuthoringSemanticDraft,
    *,
    session_id: str = "",
    topic_id: str = "",
    concept_id: str = "",
    authoring_source: str = "vtse_clustered_trait_list_v1",
) -> TeachingPlan:
    """
    Anchor root + trait child branches (tree topology, strict role separation).
    """
    strat = get_strategy(STRATEGY_ID)
    anchor_id = _node_id(0)
    trait_pairs: list[tuple[str, TraitDraft]] = [
        (_node_id(i + 1), t) for i, t in enumerate(draft.traits)
    ]

    anchor_identity, anchor_explanation = hierarchy_node_parts(
        draft.anchor_label,
        draft.anchor_summary,
    )
    nodes: list[SemanticNode] = [
        SemanticNode(
            id=anchor_id,
            label=anchor_identity or draft.anchor_label,
            summary=anchor_explanation or draft.anchor_summary,
            kind="concept",
            semantic_role="anchor_root",
            group="hierarchy",
            preferred_position="root",
            narration=draft.anchor_narration,
        ),
    ]
    for i, (nid, trait) in enumerate(trait_pairs):
        identity, explanation = hierarchy_node_parts(trait.label, trait.summary)
        nodes.append(
            SemanticNode(
                id=nid,
                label=identity or trait.label,
                summary=explanation or trait.summary,
                kind="property",
                semantic_role="trait",
                group="hierarchy",
                preferred_position="left" if i % 2 == 0 else "right",
                narration=trait.narration,
            ),
        )

    child_ids = [nid for nid, _ in trait_pairs]
    edges = _tree_edges_from_root(anchor_id, child_ids)

    beat_rows: list[tuple[str, str, str | None, PedagogicalRole, list[str]]] = [
        (
            anchor_id,
            draft.anchor_narration,
            _hierarchy_explanation_text(
                draft.anchor_label,
                draft.anchor_summary,
                draft.anchor_narration,
            )
            or None,
            "anchor",
            [anchor_id],
        ),
    ]
    for i, (nid, trait) in enumerate(trait_pairs):
        role: PedagogicalRole = "explain" if i % 2 == 0 else "reinforce"
        ann = _hierarchy_explanation_text(trait.label, trait.summary, trait.narration) or None
        beat_rows.append((nid, trait.narration, ann, role, [nid]))

    beats: list[TeachingBeat] = []
    for idx, (focus_id, narr, ann, role, highlights) in enumerate(beat_rows):
        beats.append(
            TeachingBeat(
                beat_id=_beat_id(idx),
                index=idx,
                pedagogical_role=role,
                pacing_mode=_pacing_for_role(role),
                focus_node_id=focus_id,
                narration_text=narr,
                annotation_text=ann,
                highlight_node_ids=highlights,
                reveal_script=_reveal_script(focus_id, ann, highlights),
                interaction=BeatInteraction(),
                metadata={
                    "authoring_source": authoring_source,
                    "vtse_slot": make_vtse_slot(
                        slot_kind="trait",
                        slot_key=trait_slot_key(
                            draft.anchor_label if focus_id == anchor_id else next(
                                (trait.label for nid, trait in trait_pairs if nid == focus_id),
                                focus_id,
                            )
                        ),
                        slot_index=idx,
                        label=(
                            draft.anchor_label
                            if focus_id == anchor_id
                            else next(
                                (trait.label for nid, trait in trait_pairs if nid == focus_id),
                                focus_id,
                            )
                        ),
                    ),
                },
            ),
        )

    layout_contract = "hierarchy_tree"
    key = f"{draft.topic_label}|{draft.anchor_label}|" + "|".join(t.label for t in draft.traits)
    return TeachingPlan(
        plan_id=_stable_plan_id(key),
        session_id=session_id,
        topic_id=topic_id,
        concept_id=concept_id or draft.concept_label,
        learning_objective=draft.topic_label,
        strategy=TeachingStrategyRef(
            strategy_id=STRATEGY_ID,
            strategy_version=strat.version,
            layout_family=strat.layout_family,
        ),
        interaction_policy=InteractionPolicy(),
        semantic_graph=SemanticGraph(
            representation_type="hierarchy",
            topic=draft.topic_label,
            nodes=nodes,
            edges=edges,
            layout_hints=hierarchy_layout_hints(contract=layout_contract),
        ),
        beats=beats,
        provenance={
            "authoring_source": authoring_source,
            "plan_summary": {
                "mode": "anchor_plus_traits",
                "anchor": draft.anchor_label,
                "trait_count": len(draft.traits),
                "trait_labels": [t.label for t in draft.traits],
                "beat_count": len(beats),
                "semantic_source": draft.source,
                "hierarchy_layout": hierarchy_plan_observability(
                    node_count=len(nodes),
                    edge_count=len(edges),
                    layout_contract=layout_contract,
                ),
            },
            "semantic_source": draft.source,
        },
    )
