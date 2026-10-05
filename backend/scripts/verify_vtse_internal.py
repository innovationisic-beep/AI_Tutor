"""
Internal VTSE verification — run all test topics through TeachingPlan → CIR → Timeline.

Usage (from backend/):
  python scripts/verify_vtse_internal.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Allow `app` imports when run as script
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.cir.compile_to_timeline_v3 import compile_cir_v1_to_timeline
from app.cir.validate import validate_cir_v1
from app.services.timeline_planner_v3 import TimelinePlannerV3
from app.vtse.authoring.context import build_authoring_context
from app.vtse.authoring.plan_builder import build_teaching_plan
from app.vtse.authoring.zone1 import VTSE_AUTHORING_PLANNER_SOURCE
from app.vtse.compiler.vtse_compiler import VTSECompiler
from app.vtse.flags import (
    vtse_authoring_zone1_enabled,
    vtse_enabled,
    vtse_zone1_enabled,
)
from app.vtse.pipeline import build_vtse_observability
from app.vtse.selectors.strategy_selector import select_authoring_strategy

LIVING_THINGS_STEPS = [
    {
        "title": "Living Things",
        "annotation": "Living things share core life processes.",
        "narration": "Let us anchor the idea first: living things share a common set of life processes.",
    },
    {
        "title": "Grow",
        "annotation": "Living things increase in size over time.",
        "narration": "A core sign of living things is that they grow over time.",
    },
    {
        "title": "Breathe",
        "annotation": "Living things exchange gases for energy.",
        "narration": "Living things also breathe, exchanging gases to stay alive.",
    },
    {
        "title": "Reproduce",
        "annotation": "Living things can make new organisms.",
        "narration": "And living things reproduce to create new living organisms.",
    },
]

TOPICS = [
    {
        "name": "Characteristics of Living Things",
        "concept": "life processes",
        "strategy_id": "clustered_trait_list",
        "trait_steps": LIVING_THINGS_STEPS,
    },
    {
        "name": "Living vs Non-Living Things",
        "concept": "life characteristics",
        "strategy_id": "comparison_contrast",
        "force_shape": "comparison",
        "rag_context": "- Living things grow\n- Living things reproduce\n- Non-living things do not grow",
    },
    {
        "name": "Water Cycle",
        "concept": "hydrologic cycle",
        "strategy_id": "cycle_process",
        "force_shape": "cycle",
    },
    {
        "name": "Digestion Process",
        "concept": "digestion",
        "strategy_id": "linear_process",
        "force_shape": "linear_process",
    },
    {
        "name": "Butterfly Life Cycle",
        "concept": "metamorphosis",
        "strategy_id": "cycle_process",
        "force_shape": "cycle",
    },
    {
        "name": "Plant Cell vs Animal Cell",
        "concept": "cell structure",
        "strategy_id": "comparison_contrast",
        "force_shape": "comparison",
        "rag_context": "- Chloroplasts in plant cells\n- Centrioles in animal cells\n- Cell wall in plants only",
    },
]


def _orchestration_ok(timeline: dict) -> bool:
    beats = timeline.get("beats") or []
    if not beats:
        return False
    b0 = beats[0]
    return bool(b0.get("metadata", {}).get("orchestration_v1")) and bool(
        b0.get("narration_segments"),
    )


def verify_topic(spec: dict) -> dict:
    forced = str(spec["strategy_id"])
    force_shape = spec.get("force_shape")
    ctx = build_authoring_context(
        topic_name=spec["name"],
        concept=spec["concept"],
        rag_context=spec.get("rag_context"),
        trait_steps=spec.get("trait_steps"),
        force_shape=force_shape,
        source="verify_script",
    )
    selection = select_authoring_strategy(ctx, forced_strategy_id=forced)
    flat = bool(spec.get("trait_steps") and len(spec["trait_steps"]) >= 3)
    plan, sel = build_teaching_plan(
        ctx,
        session_id="verify_sess",
        topic_id="verify_topic",
        concept=spec["concept"],
        forced_strategy_id=forced,
        flat_from_steps=flat,
    )
    compiled = VTSECompiler().compile_to_cir_dict(plan)
    v = validate_cir_v1(compiled.cir)
    cir = compiled.cir
    timeline = None
    layout_profile = None
    layout_mode = None
    orchestration_ok = False
    if v.ok:
        out = compile_cir_v1_to_timeline(
            cir=cir,
            session_id="verify_sess",
            topic_id="verify_topic",
            concept=spec["concept"],
            planner=TimelinePlannerV3(),
        )
        timeline = out.timeline
        lm = timeline.get("layout_metadata") or {}
        layout_profile = lm.get("layout_profile")
        layout_mode = lm.get("layout_mode")
        orchestration_ok = _orchestration_ok(timeline)

    obs = build_vtse_observability(
        plan=plan,
        compile_result=compiled,
        authoring_source=str(plan.provenance.get("authoring_source") or "vtse"),
        compiler_path="teaching_plan_authoring_to_cir_v1",
        strategy_selection=sel,
    )
    summary = plan.provenance.get("plan_summary") or {}
    roles = [b.pedagogical_role for b in sorted(plan.beats, key=lambda x: x.index)]
    unique_roles = sorted(set(roles))

    return {
        "topic": spec["name"],
        "flags": {
            "vtse_enabled()": vtse_enabled(),
            "vtse_zone1_enabled()": vtse_zone1_enabled(),
            "vtse_authoring_zone1_enabled()": vtse_authoring_zone1_enabled(),
        },
        "selected_strategy": sel.strategy_id,
        "strategy_reason": sel.strategy_reason,
        "semantic_shape": sel.semantic_shape,
        "authoring_mode": sel.authoring_mode,
        "shape_cues": list(ctx.shape_cues),
        "plan_id": plan.plan_id,
        "plan_summary_mode": summary.get("mode"),
        "beat_count": len(plan.beats),
        "node_count": len(plan.semantic_graph.nodes),
        "beat_roles": roles,
        "unique_beat_roles": unique_roles,
        "edge_count": len(plan.semantic_graph.edges),
        "cir_representation_type": cir.get("representation_type"),
        "cir_layout_hints": cir.get("layout_hints"),
        "cir_valid": v.ok,
        "cir_errors": list(v.errors) if not v.ok else [],
        "compiler_path": compiled.compiler_path,
        "vtse_metadata_on_cir": (cir.get("metadata") or {}).get("vtse", {}),
        "timeline_layout_profile": layout_profile,
        "timeline_layout_mode": layout_mode,
        "planner_source_when_vtse_on": VTSE_AUTHORING_PLANNER_SOURCE,
        "orchestration_compatible": orchestration_ok,
        "observability_keys": sorted(obs.keys()),
    }


def main() -> None:
    results = [verify_topic(t) for t in TOPICS]
    strategies = {r["selected_strategy"] for r in results}
    shapes = {r["semantic_shape"] for r in results}
    print("=== VTSE INTERNAL VERIFICATION ===\n")
    print(
        json.dumps(
            {
                "distinct_strategies": sorted(strategies),
                "distinct_semantic_shapes": sorted(shapes),
                "strategy_count": len(strategies),
                "env_flags": results[0]["flags"] if results else {},
                "topics": results,
            },
            indent=2,
        ),
    )
    print("\n=== MARKDOWN TABLE ===\n")
    headers = [
        "Topic",
        "Strategy",
        "Reason",
        "Shape",
        "Beats",
        "Roles",
        "CIR rep",
        "Layout profile",
        "Orch OK",
    ]
    print("| " + " | ".join(headers) + " |")
    print("| " + " | ".join(["---"] * len(headers)) + " |")
    for r in results:
        print(
            "| "
            + " | ".join(
                [
                    r["topic"][:40],
                    r["selected_strategy"],
                    r["strategy_reason"][:28],
                    r["semantic_shape"],
                    str(r["beat_count"]),
                    ",".join(r["unique_beat_roles"][:5]),
                    r["cir_representation_type"] or "?",
                    r["timeline_layout_profile"] or "?",
                    "yes" if r["orchestration_compatible"] else "no",
                ],
            )
            + " |",
        )


if __name__ == "__main__":
    main()
