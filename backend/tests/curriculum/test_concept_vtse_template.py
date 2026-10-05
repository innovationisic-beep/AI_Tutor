"""Tests for authored VTSE template normalize + force strategy."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.services.curriculum.concept_vtse_template import (
    force_shape_for_strategy,
    materialize_vtse_template_inputs,
    normalize_vtse_template,
)
from app.vtse.authoring.context import build_authoring_context
from app.vtse.authoring.plan_builder import build_teaching_plan
from app.vtse.selectors.strategy_selector import (
    STRATEGY_COMPARISON,
    select_authoring_strategy,
)


def test_normalize_vtse_template_none_and_empty():
    assert normalize_vtse_template(None) is None
    assert normalize_vtse_template({"strategy_id": "", "payload": {}}) is None


def test_normalize_comparison_requires_rows():
    with pytest.raises(HTTPException) as ei:
        normalize_vtse_template(
            {
                "strategy_id": "comparison_contrast",
                "payload": {
                    "left_label": "Humans",
                    "right_label": "Robots",
                    "rows": [{"dimension": "Living", "left": "alive", "right": ""}],
                },
            }
        )
    assert ei.value.status_code == 400


def test_normalize_comparison_ok():
    tmpl = normalize_vtse_template(
        {
            "strategy_id": "comparison_contrast",
            "version": 1,
            "payload": {
                "left_label": "Humans",
                "right_label": "Robots",
                "rows": [
                    {"dimension": "Living", "left": "Living things", "right": "Non-living"},
                    {"dimension": "Growth", "left": "Grow", "right": "Do not grow"},
                ],
            },
        }
    )
    assert tmpl is not None
    assert tmpl.strategy_id == "comparison_contrast"
    assert len(tmpl.payload["rows"]) == 2


def test_normalize_rejects_bad_strategy():
    with pytest.raises(HTTPException):
        normalize_vtse_template({"strategy_id": "not_a_strategy", "payload": {"steps": []}})


def test_force_strategy_selection_comparison():
    tmpl = normalize_vtse_template(
        {
            "strategy_id": "comparison_contrast",
            "payload": {
                "left_label": "A",
                "right_label": "B",
                "rows": [
                    {"dimension": "X", "left": "left1", "right": "right1"},
                    {"dimension": "Y", "left": "left2", "right": "right2"},
                ],
            },
        }
    )
    assert tmpl is not None
    comp_json, _, _, forced = materialize_vtse_template_inputs(
        tmpl, topic_name="Topic", concept="A vs B"
    )
    ctx = build_authoring_context(
        topic_name="Topic",
        concept="Humans and Robots",
        comparison_llm_json=comp_json,
        force_shape=force_shape_for_strategy(forced),  # type: ignore[arg-type]
        source="authored_vtse_template",
    )
    selection = select_authoring_strategy(ctx, forced_strategy_id=forced)
    assert selection.strategy_id == STRATEGY_COMPARISON
    assert selection.strategy_reason == "forced:vtse_template"
    assert ctx.comparison is not None
    assert len(ctx.comparison.rows) == 2
    assert [r.left_detail for r in ctx.comparison.rows] == ["left1", "left2"]
    assert [r.right_detail for r in ctx.comparison.rows] == ["right1", "right2"]

    plan, sel = build_teaching_plan(
        ctx,
        session_id="s1",
        topic_id="t1",
        concept="Humans and Robots",
        forced_strategy_id=forced,
    )
    assert sel.strategy_id == STRATEGY_COMPARISON
    assert plan.strategy_id == STRATEGY_COMPARISON


def test_materialize_linear_steps():
    tmpl = normalize_vtse_template(
        {
            "strategy_id": "linear_process",
            "payload": {
                "steps": [
                    {"label": "Start", "summary": "Begin"},
                    {"label": "Middle", "summary": "Continue"},
                    {"label": "End", "summary": "Finish"},
                ]
            },
        }
    )
    assert tmpl is not None
    _, proc, traits, forced = materialize_vtse_template_inputs(
        tmpl, topic_name="Digestion", concept="Digestion process"
    )
    assert forced == "linear_process"
    assert proc is not None
    assert len(proc.steps) == 3
    assert traits is None

    ctx = build_authoring_context(
        topic_name="Digestion",
        concept="Digestion process",
        process_llm_draft=proc,
        force_shape="linear_process",
        source="authored_vtse_template",
    )
    selection = select_authoring_strategy(ctx, forced_strategy_id=forced)
    assert selection.strategy_id == "linear_process"
