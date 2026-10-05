"""comparison_contrast — side-by-side comparison TeachingPlan authoring."""

from __future__ import annotations

from app.vtse.authoring.comparison_rows import ComparisonRow, _row_from_trait_pair
from app.vtse.authoring.semantic_shape import ComparisonSidesDraft
from app.vtse.models.plan import (
    InteractionPolicy,
    PedagogicalRole,
    SemanticGraph,
    SemanticNode,
    TeachingPlan,
    TeachingStrategyRef,
)
from app.vtse.registry.strategy_registry import get_strategy
from app.cir.limits import COMPARISON_MAX_ROW_PAIRS
from app.services.vtse_visuals.slots import column_slot_key, make_vtse_slot, row_slot_key
from app.vtse.strategies.common import CIR_MAX_NODES, make_beat, node_id, stable_plan_id

STRATEGY_ID = "comparison_contrast"
_AUTHORING_SOURCE = "vtse_comparison_contrast_v2"
# Single zero-width space — satisfies plan schema; TTS layer treats as silent.
_SUPPRESSED_ROW_NARRATION = "\u200b"


def _effective_rows(sides: ComparisonSidesDraft) -> tuple[ComparisonRow, ...]:
    if sides.rows:
        return sides.rows
    rows: list[ComparisonRow] = []
    for left_trait, right_trait in zip(sides.left_traits, sides.right_traits):
        row = _row_from_trait_pair(
            left_trait,
            right_trait,
            left_label=sides.left_label,
            right_label=sides.right_label,
        )
        if row:
            rows.append(row)
    return tuple(rows)


def _row_summary(dimension: str, detail: str) -> str:
    detail = detail.strip()
    dim = dimension.strip()
    if dim and detail:
        return f"{dim}: {detail}"
    return detail or dim


def _comparison_node_plan(
    sides: ComparisonSidesDraft,
) -> list[tuple[SemanticNode, PedagogicalRole, str | None]]:
    """Build node list and per-node role in deterministic reveal order."""
    rows: list[tuple[SemanticNode, PedagogicalRole, str | None]] = []
    comparison_rows = _effective_rows(sides)

    rows.append(
        (
            SemanticNode(
                id=node_id(0),
                label=sides.left_label,
                summary=f"Compare {sides.left_label}.",
                kind="concept",
                semantic_role="column_header",
                group="left_col",
                preferred_position="left_col",
                narration=(sides.opening_narration or "").strip() or sides.left_label,
            ),
            "anchor",
            None,
        ),
    )
    rows.append(
        (
            SemanticNode(
                id=node_id(1),
                label=sides.right_label,
                summary=f"Compare {sides.right_label}.",
                kind="concept",
                semantic_role="column_header",
                group="right_col",
                preferred_position="right_col",
                narration=sides.right_label,
            ),
            "anchor",
            None,
        ),
    )

    max_pairs = min(len(comparison_rows), (CIR_MAX_NODES - 2) // 2, COMPARISON_MAX_ROW_PAIRS)
    idx = 2
    for pair_i in range(max_pairs):
        row = comparison_rows[pair_i]
        rows.append(
            (
                SemanticNode(
                    id=node_id(idx),
                    label=row.left_title,
                    summary=_row_summary(row.dimension, row.left_card_detail()),
                    kind="property",
                    semantic_role="comparison_row",
                    group="left",
                    preferred_position="left",
                    narration=row.pair_narration(sides.left_label, sides.right_label),
                ),
                "compare",
                row.left_annotation(),
            ),
        )
        idx += 1
        rows.append(
            (
                SemanticNode(
                    id=node_id(idx),
                    label=row.right_title,
                    summary=_row_summary(row.dimension, row.right_card_detail()),
                    kind="property",
                    semantic_role="comparison_row",
                    group="right",
                    preferred_position="right",
                    narration="",
                ),
                "compare",
                row.right_annotation(),
            ),
        )
        idx += 1
        _ = pair_i

    return rows


def build_comparison_contrast_plan(
    *,
    topic_label: str,
    sides: ComparisonSidesDraft,
    session_id: str = "",
    topic_id: str = "",
    concept_id: str = "",
    authoring_source: str = _AUTHORING_SOURCE,
) -> TeachingPlan:
    strat = get_strategy(STRATEGY_ID)
    comparison_rows = _effective_rows(sides)
    max_pairs = min(len(comparison_rows), (CIR_MAX_NODES - 2) // 2, COMPARISON_MAX_ROW_PAIRS)
    rows_clipped = max(0, len(comparison_rows) - max_pairs)
    node_rows = _comparison_node_plan(sides)
    nodes = [r[0] for r in node_rows]

    beats = []
    last_i = len(node_rows) - 1
    for i, (node, role, ann) in enumerate(node_rows):
        pair_index = max(0, (i - 2) // 2) if i >= 2 else None
        beat_role: PedagogicalRole = "reflect" if i == last_i and last_i > 1 else role
        row_highlight = [node.id]
        if (
            pair_index is not None
            and node.group == "right"
            and pair_index < len(comparison_rows)
        ):
            left_idx = 2 + pair_index * 2
            if left_idx < len(nodes):
                row_highlight = [nodes[left_idx].id, node.id]

        narration_text = node.narration or node.label
        if pair_index is not None and role == "compare" and node.group == "right":
            narration_text = _SUPPRESSED_ROW_NARRATION
        narration_owner = (
            "comparison_row_pair"
            if pair_index is not None and role == "compare" and node.group == "left"
            else (
                "comparison_row_suppressed"
                if pair_index is not None and role == "compare" and node.group == "right"
                else "comparison_column"
            )
        )
        if pair_index is None:
            vtse_slot = make_vtse_slot(
                slot_kind="column",
                slot_key=column_slot_key(node.label),
                slot_index=0 if node.group == "left_col" else 1,
                side="left" if node.group == "left_col" else "right",
                label=node.label,
                narration_owner=narration_owner,
            )
        else:
            row = comparison_rows[pair_index]
            vtse_slot = make_vtse_slot(
                slot_kind="row",
                slot_key=row_slot_key(row.dimension),
                slot_index=pair_index,
                side="left" if node.group == "left" else "right",
                label=row.dimension,
                narration_owner=narration_owner,
                left_detail=row.left_detail,
                right_detail=row.right_detail,
            )

        beats.append(
            make_beat(
                index=i,
                focus_id=node.id,
                role=beat_role,
                narration=narration_text,
                annotation=None if role == "compare" else ann,
                highlight_ids=row_highlight,
                authoring_source=authoring_source,
                extra_metadata={
                    "comparison_side": node.group,
                    "pair_index": pair_index,
                    "comparison_dimension": (
                        comparison_rows[pair_index].dimension
                        if pair_index is not None and pair_index < len(comparison_rows)
                        else None
                    ),
                    "narration_mode": "comparison_teacher_expanded",
                    "narration_owner": narration_owner,
                    "vtse_slot": vtse_slot,
                },
            ),
        )

    key = f"{topic_label}|{sides.left_label}|{sides.right_label}|" + "|".join(
        f"{row.dimension}:{row.left_title}:{row.right_title}" for row in comparison_rows
    )
    stats = sides.row_stats
    comparison_debug = {
        "comparison_dimension_count": stats.comparison_dimension_count if stats else len(comparison_rows),
        "paired_rows_generated": stats.paired_rows_generated if stats else len(comparison_rows),
        "orphan_rows_detected": stats.orphan_rows_detected if stats else 0,
        "placeholder_filtered": stats.placeholder_filtered if stats else 0,
        "narration_mode": stats.narration_mode if stats else "comparison_teacher_expanded",
        "comparison_render_mode": "row_aligned",
        "comparison_row_count": len(comparison_rows),
        "detached_annotation_count": 0,
        "orphan_row_count": stats.orphan_row_count if stats else 0,
        "repaired_row_count": stats.repaired_row_count if stats else 0,
        "skipped_incomplete_rows": stats.skipped_incomplete_rows if stats else 0,
        "invalid_dimension_pairs": stats.invalid_dimension_pairs if stats else 0,
        "narration_owner": "comparison_row_unified",
        "rag_context_chars_used": stats.rag_context_chars_used if stats else 0,
        "rag_lines_ingested": stats.rag_lines_ingested if stats else 0,
        "comparison_rows_generated": stats.comparison_rows_generated if stats else len(comparison_rows),
        "rows_rendered": max_pairs,
        "rows_clipped_by_budget": max(
            stats.rows_clipped_by_budget if stats else 0,
            rows_clipped,
        ),
        "narration_detail_level": stats.narration_detail_level if stats else "deterministic_expanded",
        "semantic_compression_ratio": stats.semantic_compression_ratio if stats else 0.0,
        "dropped_context_sections": stats.dropped_context_sections if stats else 0,
    }

    return TeachingPlan(
        plan_id=stable_plan_id("cmp", key),
        session_id=session_id,
        topic_id=topic_id,
        concept_id=concept_id,
        learning_objective=topic_label,
        strategy=TeachingStrategyRef(
            strategy_id=STRATEGY_ID,
            strategy_version=strat.version,
            layout_family=strat.layout_family,
        ),
        interaction_policy=InteractionPolicy(),
        semantic_graph=SemanticGraph(
            representation_type="comparison",
            topic=topic_label,
            nodes=nodes,
            edges=[],
            layout_hints={
                "grouping": "comparison",
                "preferred_layout": "comparison_split",
                "emphasis": "contrast_pairs",
            },
        ),
        beats=beats,
        provenance={
            "authoring_source": authoring_source,
            "plan_summary": {
                "mode": "comparison_row_centric",
                "left_label": sides.left_label,
                "right_label": sides.right_label,
                "paired_rows": len(comparison_rows),
                "node_count": len(nodes),
                "beat_count": len(beats),
            },
            "comparison_authoring": comparison_debug,
            "semantic_pairing": [
                {
                    "pair_index": pi,
                    "dimension": row.dimension,
                    "left_title": row.left_title,
                    "left_detail": row.left_detail,
                    "right_title": row.right_title,
                    "right_detail": row.right_detail,
                }
                for pi, row in enumerate(comparison_rows)
            ],
        },
    )
