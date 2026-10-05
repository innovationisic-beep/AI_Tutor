"""Tests for VTSE template → RAG context helper and template-only Zone1 gate."""

from __future__ import annotations

import pytest

from app.services.curriculum.concept_vtse_context import (
    format_vtse_template_as_rag_context,
    soft_normalize_vtse_template,
)
from app.services.curriculum.concept_vtse_template import normalize_vtse_template


def test_format_hierarchy_template_contains_points():
    tmpl = normalize_vtse_template(
        {
            "strategy_id": "hierarchy_concept_intro",
            "payload": {
                "steps": [
                    {"label": "Grow", "summary": "Living things grow"},
                    {"label": "Breathe", "summary": "Living things breathe"},
                    {"label": "Reproduce", "summary": "Living things reproduce"},
                ]
            },
        }
    )
    text = format_vtse_template_as_rag_context(tmpl, concept_label="Living things")
    assert "Living things" in text
    assert "Grow" in text
    assert "Breathe" in text
    assert "Reproduce" in text
    assert "VTSE template" in text


def test_format_comparison_template():
    tmpl = normalize_vtse_template(
        {
            "strategy_id": "comparison_contrast",
            "payload": {
                "left_label": "Humans",
                "right_label": "Robots",
                "rows": [
                    {"dimension": "Living", "left": "Living", "right": "Non-living"},
                    {"dimension": "Growth", "left": "Grow", "right": "Do not grow"},
                ],
            },
        }
    )
    text = format_vtse_template_as_rag_context(tmpl, concept_label="Compare")
    assert "Humans" in text
    assert "Robots" in text
    assert "Living" in text


def test_soft_normalize_invalid_returns_none():
    assert soft_normalize_vtse_template(None) is None
    assert soft_normalize_vtse_template({"strategy_id": "nope", "payload": {}}) is None


@pytest.mark.asyncio
async def test_zone1_returns_none_without_template():
    from app.vtse.authoring.zone1 import try_zone1_vtse_authoring

    class _Planner:
        pass

    result = await try_zone1_vtse_authoring(
        planner=_Planner(),  # type: ignore[arg-type]
        session_id="s1",
        topic_id_str="t1",
        topic_name="Topic",
        concept="Living things",
        vtse_template=None,
        compile_validated_cir=lambda **kwargs: None,
    )
    assert result is None
