"""Publish gate: a sequenced Story Hook needs a seed the planner can ground on."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.curriculum.curriculum_validation_service import (
    CurriculumValidationService,
)

VTSE_TEMPLATE: Dict[str, Any] = {
    "strategy_id": "clustered_trait_list",
    "payload": {
        "steps": [
            {"label": "Stomata", "summary": "Tiny pores on the leaf surface."},
            {"label": "Guard cells", "summary": "They open and close each pore."},
            {"label": "Gas exchange", "summary": "CO2 in, O2 out."},
        ]
    },
}


async def _validate(
    *,
    story_hook: Optional[Dict[str, Any]],
    teaching_sequence: List[str],
):
    tree = {
        "zones": [
            {
                "zone_number": 1,
                "clusters": [
                    {
                        "cluster_number": 1,
                        "title": "Leaf structure",
                        "concepts": [
                            {
                                "slug": "stomata",
                                "display_name": "Stomata",
                                "vtse_template": VTSE_TEMPLATE,
                                "story_hook": story_hook,
                                "teaching_sequence": teaching_sequence,
                            }
                        ],
                    }
                ],
            }
        ]
    }
    tree_svc = MagicMock()
    tree_svc.get_tree = AsyncMock(return_value=tree)
    return await CurriculumValidationService(tree_service=tree_svc).validate(MagicMock())


@pytest.mark.asyncio
async def test_sequenced_story_hook_without_a_seed_blocks_publish():
    result = await _validate(
        story_hook={"title": "Leaf pores", "body": "   "},
        teaching_sequence=["story_hook", "vtse"],
    )

    assert result.ready_to_publish is False
    assert "STORY_HOOK_MISSING_SEED" in [e.code for e in result.errors]
    assert any("Stomata" in e.message for e in result.errors)


@pytest.mark.asyncio
async def test_sequenced_story_hook_with_a_seed_publishes():
    result = await _validate(
        story_hook={
            "title": "Leaf pores",
            "body": "A leaf breathing through thousands of tiny doors.",
            "teacher_intent": "Emphasise guard cell control.",
        },
        teaching_sequence=["story_hook", "vtse"],
    )

    assert result.ready_to_publish is True
    assert result.errors == []


@pytest.mark.asyncio
async def test_concept_without_a_story_hook_stage_is_unaffected():
    result = await _validate(story_hook=None, teaching_sequence=["vtse"])

    assert result.ready_to_publish is True
    assert [w.code for w in result.warnings if w.code.startswith("STORY_HOOK")] == []


@pytest.mark.asyncio
async def test_visuals_on_an_unsequenced_hook_warn_without_blocking():
    """Uploaded images that can never be shown are an authoring mistake, not a gate."""
    result = await _validate(
        story_hook={
            "body": "A leaf breathing through thousands of tiny doors.",
            "visuals": [
                {
                    "asset_key": "stomata_surface",
                    "storage_key": "abc.png",
                    "description": "Microscope view.",
                }
            ],
        },
        teaching_sequence=["vtse"],
    )

    assert result.ready_to_publish is True
    assert "STORY_HOOK_VISUALS_UNUSED" in [w.code for w in result.warnings]
