"""VTSECompiler — TeachingPlan → CIR v1 (Phase 1 pass-through)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.vtse.models.plan import TeachingPlan


@dataclass(frozen=True)
class VTSECompileResult:
    cir: dict[str, Any]
    compiler_path: str
    strategy_id: str
    tdsl_version: str
    plan_id: str


class VTSECompiler:
    """
    Lowers a TeachingPlan to CIR-compatible JSON.

    Phase 1: structural pass-through — output must validate as CIR v1 and
    preserve fields needed by ``TimelinePlannerV3.compile_cir_v1_to_timeline``.
    """

    compiler_version: str = "vtse-compiler-1.0.0"

    def compile_to_cir_dict(self, plan: TeachingPlan) -> VTSECompileResult:
        nodes: list[dict[str, Any]] = []
        for n in plan.semantic_graph.nodes:
            nodes.append(
                {
                    "id": n.id,
                    "label": n.label,
                    "summary": n.summary,
                    "kind": n.kind,
                    "semantic_role": n.semantic_role,
                    "group": n.group,
                    "preferred_position": n.preferred_position,
                    "narration": n.narration,
                },
            )

        edges: list[dict[str, Any]] = []
        for e in plan.semantic_graph.edges:
            edges.append(
                {
                    "from": e.from_id,
                    "to": e.to,
                    "relation": e.relation,
                },
            )

        beats: list[dict[str, Any]] = []
        narration_segments: list[dict[str, Any]] = []
        for b in sorted(plan.beats, key=lambda x: x.index):
            beats.append(
                {
                    "beat_id": b.beat_id,
                    "index": b.index,
                    "narration_text": b.narration_text,
                    "annotation_text": b.annotation_text,
                    "highlight_node_ids": list(b.highlight_node_ids),
                    "focus_node_id": b.focus_node_id,
                },
            )
            narration_segments.append(
                {
                    "segment_id": f"seg_{b.beat_id}",
                    "beat_id": b.beat_id,
                    "text": b.narration_text,
                },
            )

        layout_hints = plan.semantic_graph.layout_hints
        cir_meta = dict(plan.provenance.get("cir_metadata") or {})
        cir_meta["vtse"] = {
            "plan_id": plan.plan_id,
            "strategy_id": plan.strategy.strategy_id,
            "tdsl_version": plan.tdsl_version,
            "compiler_version": self.compiler_version,
            "compiler_path": "teaching_plan_to_cir_v1",
            "authoring_source": plan.provenance.get("authoring_source"),
            "plan_summary": plan.provenance.get("plan_summary"),
        }
        for i, b in enumerate(sorted(plan.beats, key=lambda x: x.index)):
            cir_meta.setdefault("pedagogical_roles", {})[b.beat_id] = b.pedagogical_role

        cir: dict[str, Any] = {
            "version": "1",
            "representation_type": plan.semantic_graph.representation_type,
            "topic": plan.semantic_graph.topic,
            "nodes": nodes,
            "edges": edges,
            "beats": beats,
            "narration_segments": narration_segments,
            "metadata": cir_meta,
        }
        if layout_hints:
            cir["layout_hints"] = layout_hints

        return VTSECompileResult(
            cir=cir,
            compiler_path="teaching_plan_to_cir_v1",
            strategy_id=plan.strategy.strategy_id,
            tdsl_version=plan.tdsl_version,
            plan_id=plan.plan_id,
        )
