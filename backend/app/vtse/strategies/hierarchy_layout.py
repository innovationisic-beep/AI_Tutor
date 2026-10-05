"""Hierarchy layout contract helpers (Phase B — tree topology, role separation)."""

from __future__ import annotations

from typing import Any


def hierarchy_concise_label(text: str, *, max_words: int = 6) -> str:
    """Node identity: short semantic label only (never a paragraph)."""
    t = (text or "").strip()
    if not t:
        return ""
    words = t.split()
    if len(words) <= max_words and len(t) <= 48:
        return t
    for sep in (".", ";", "—", "–", ":"):
        if sep in t:
            head = t.split(sep, 1)[0].strip()
            if head and len(head.split()) <= max_words:
                return head[:48]
    return " ".join(words[:max_words])[:48]


def hierarchy_node_parts(label: str, summary: str) -> tuple[str, str]:
    """Split concise identity from teaching explanation."""
    raw_label = (label or "").strip()
    raw_summary = (summary or "").strip()
    identity = hierarchy_concise_label(raw_label) or hierarchy_concise_label(raw_summary, max_words=4)
    explanation = raw_summary
    if not explanation and raw_label and raw_label != identity:
        explanation = raw_label
    if explanation.strip().lower() == identity.strip().lower():
        pass
    elif identity and explanation.lower().startswith(identity.lower()) and len(explanation) - len(identity) < 24:
        tail = explanation[len(identity) :].lstrip(" ,:;-")
        explanation = tail or explanation
    return identity[:80], explanation[:600]


def hierarchy_layout_hints(*, contract: str = "hierarchy_tree") -> dict[str, str]:
    return {
        "preferred_layout": "hierarchy_root_children",
        "hierarchy_layout_contract": contract,
        "topology_type": "root_to_children",
        "hierarchy_renderer_mode": "hierarchy_tree_lanes",
    }


def hierarchy_plan_observability(
    *,
    node_count: int,
    edge_count: int,
    layout_contract: str,
    sibling_chain_edges: int = 0,
) -> dict[str, Any]:
    branches = max(0, node_count - 1)
    depth = 1 if node_count <= 1 else 2
    return {
        "hierarchy_layout_contract": layout_contract,
        "hierarchy_branch_count": branches,
        "hierarchy_edge_crossings": 0 if sibling_chain_edges == 0 else sibling_chain_edges,
        "hierarchy_tree_depth": depth,
        "hierarchy_renderer_mode": "hierarchy_tree_lanes",
        "hierarchy_explanation_lane_count": node_count,
        "hierarchy_topology_type": "root_to_children",
        "hierarchy_sibling_chain_edges": sibling_chain_edges,
    }
