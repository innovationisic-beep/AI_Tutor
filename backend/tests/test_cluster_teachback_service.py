"""Tests for cluster teachback question generation."""

from types import SimpleNamespace

import pytest

from app.cir.compile_to_timeline_v3 import compile_cir_v1_to_timeline
from app.services.handlers.cluster_teachback_service import (
    fallback_cluster_teachback_question,
    teachback_coverage_from_ctx,
    validate_cluster_teachback_question,
)
from app.services.handlers.teaching_transcript_service import (
    extract_quizable_items_from_timeline,
    merge_transcript_into_taught_context,
)
from app.services.timeline_planner_v3 import TimelinePlannerV3
from app.vtse.authoring.semantic_extract import extract_authoring_semantics
from app.vtse.compiler.vtse_compiler import VTSECompiler
from app.vtse.strategies.clustered_trait_list import build_clustered_trait_list_plan_flat


def _living_things_timeline() -> dict:
    steps = [
        {
            "title": "Living Things",
            "annotation": "Living things share core life processes.",
            "narration": "Let us anchor the idea first.",
        },
        {
            "title": "Grow",
            "annotation": "Living things increase in size over time.",
            "narration": "They grow over time.",
        },
        {
            "title": "Breathe",
            "annotation": "Living things exchange gases for energy.",
            "narration": "They breathe.",
        },
        {
            "title": "Reproduce",
            "annotation": "Living things can make new organisms.",
            "narration": "They reproduce.",
        },
    ]
    semantic = extract_authoring_semantics(
        topic_name="Living Things",
        concept="life",
        trait_steps=steps,
        source="template_steps",
    )
    plan = build_clustered_trait_list_plan_flat(
        topic_label=semantic.topic_label,
        traits=semantic.traits,
    )
    cir = VTSECompiler().compile_to_cir_dict(plan).cir
    out = compile_cir_v1_to_timeline(
        cir=cir,
        session_id="s",
        topic_id="t",
        concept="life",
        planner=TimelinePlannerV3(),
    )
    return out.timeline


def test_fallback_lists_characteristics_not_topic_as_item() -> None:
    q = fallback_cluster_teachback_question(
        ["Living things"],
        ["Grow", "Breathe", "Reproduce"],
        topic_anchor="Living Things",
        coverage_facts=[
            "Living things increase in size over time.",
            "Living things exchange gases for energy.",
            "Living things can make new organisms.",
        ],
    )
    assert "grow" in q.lower()
    assert "breathe" in q.lower()
    assert "reproduce" in q.lower()
    assert "3 characteristics" in q.lower()
    assert "briefly explain" in q.lower() or "explain each" in q.lower()


def test_teachback_coverage_excludes_hierarchy_root() -> None:
    timeline = _living_things_timeline()
    items = extract_quizable_items_from_timeline(timeline)
    ctx = merge_transcript_into_taught_context(
        {"steps": [], "step_count": 0},
        "",
        structured=items,
    )
    coverage = teachback_coverage_from_ctx(ctx)
    assert coverage["topic_anchor"] == "Living Things"
    assert coverage["coverage_labels"] == ["Grow", "Breathe", "Reproduce"]
    assert coverage["coverage_count"] == 3
    assert "Living Things" not in coverage["coverage_labels"]


def test_validate_rejects_vague_connect_prompt() -> None:
    taught_ctx = {
        "step_count": 3,
        "topic_anchor": "Living Things",
        "teaching_facts": [
            "Living things increase in size over time.",
            "Living things exchange gases for energy.",
            "Living things can make new organisms.",
        ],
        "steps": ["Grow", "Breathe", "Reproduce"],
    }
    labels = taught_ctx["steps"]
    bad = "Can you walk me through how all these ideas connect?"
    assert validate_cluster_teachback_question(bad, taught_ctx, labels) is False

    good = fallback_cluster_teachback_question(
        ["Living things"],
        labels,
        topic_anchor="Living Things",
        coverage_facts=taught_ctx["teaching_facts"],
    )
    assert validate_cluster_teachback_question(good, taught_ctx, labels)


def test_cluster_teachback_tier_thresholds() -> None:
    from app.services.handlers.cluster_teachback_service import cluster_teachback_tier

    assert cluster_teachback_tier(85) == "excellent"
    assert cluster_teachback_tier(81) == "excellent"
    assert cluster_teachback_tier(80) == "excellent"
    assert cluster_teachback_tier(79) == "partial"
    assert cluster_teachback_tier(65) == "partial"
    assert cluster_teachback_tier(50) == "partial"
    assert cluster_teachback_tier(49) == "weak"


def test_format_weak_intro_is_empathetic() -> None:
    from app.services.handlers.cluster_teachback_service import (
        format_weak_teachback_intro,
    )

    intro = format_weak_teachback_intro(
        {"score": 35, "score_rationale": "Major gaps in your explanation."}
    )
    assert "haven't quite got" in intro.lower()
    assert "35 out of 100" in intro


def test_format_post_socratic_is_plain_explanation() -> None:
    from app.services.handlers.cluster_teachback_service import (
        format_post_socratic_explanation_message,
    )

    msg = format_post_socratic_explanation_message(
        "Living things grow, breathe, and reproduce — here's what each means..."
    )
    assert "grow" in msg.lower()
    assert "ready to move on" in msg.lower()


def test_format_score_announcement_includes_marks() -> None:
    from app.services.handlers.cluster_teachback_service import (
        format_excellent_teachback_message,
        format_score_announcement,
    )

    line = format_score_announcement(80, "You explained grow and breathe well.")
    assert "80 out of 100" in line
    msg = format_excellent_teachback_message(
        {
            "score": 88,
            "score_rationale": "You covered all three characteristics.",
            "feedback": "Well done!",
            "ideal_answer": "Living things grow, breathe, and reproduce.",
        }
    )
    assert "88 out of 100" in msg
    assert "grow, breathe, and reproduce" in msg


@pytest.mark.asyncio
async def test_eval_context_uses_characteristics_not_topic_anchor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.handlers import cluster_teachback_service as svc

    timeline = _living_things_timeline()
    items = extract_quizable_items_from_timeline(timeline)
    taught_ctx = merge_transcript_into_taught_context(
        {"steps": [], "step_count": 0},
        "",
        structured=items,
    )

    async def _fake_resolve(_session: object, _sid: object) -> dict:
        return taught_ctx

    monkeypatch.setattr(svc, "resolve_cluster_teachback_taught_context", _fake_resolve)

    session = SimpleNamespace(
        teachback_concepts=["Living things"],
        organization_id="org",
        student_id="stu",
    )
    block = await svc.build_cluster_teachback_eval_context(
        session,  # type: ignore[arg-type]
        "0" * 24,  # type: ignore[arg-type]
        "Explain living things in your own words.",
    )
    assert "TOPIC CONTEXT" in block
    assert "Grow" in block
    assert "REQUIRED COVERAGE" in block
    assert "CHARACTERISTICS" in block or "characteristics" in block.lower()
