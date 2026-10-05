"""Publish gate: every concept must have a valid VTSE template."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.curriculum.curriculum_validation_service import (
    CurriculumValidationService,
)


@pytest.mark.asyncio
async def test_missing_vtse_template_blocks_publish():
    tree = {
        "zones": [
            {
                "zone_number": 1,
                "clusters": [
                    {
                        "cluster_number": 1,
                        "title": "Cluster A",
                        "concepts": [
                            {
                                "slug": "living-things",
                                "display_name": "Living things",
                                "vtse_template": None,
                            }
                        ],
                    }
                ],
            }
        ]
    }
    tree_svc = MagicMock()
    tree_svc.get_tree = AsyncMock(return_value=tree)
    svc = CurriculumValidationService(tree_service=tree_svc)
    ctx = MagicMock()
    result = await svc.validate(ctx)
    assert result.ready_to_publish is False
    codes = [e.code for e in result.errors]
    assert "MISSING_VTSE_TEMPLATE" in codes
    assert any("Living things" in e.message for e in result.errors)


@pytest.mark.asyncio
async def test_valid_vtse_template_allows_publish_ready():
    tree = {
        "zones": [
            {
                "zone_number": 1,
                "clusters": [
                    {
                        "cluster_number": 1,
                        "title": "Cluster A",
                        "concepts": [
                            {
                                "slug": "living-things",
                                "display_name": "Living things",
                                "vtse_template": {
                                    "strategy_id": "hierarchy_concept_intro",
                                    "version": 1,
                                    "payload": {
                                        "steps": [
                                            {"label": "Grow", "summary": "They grow"},
                                            {
                                                "label": "Breathe",
                                                "summary": "They breathe",
                                            },
                                            {
                                                "label": "Reproduce",
                                                "summary": "They reproduce",
                                            },
                                        ]
                                    },
                                },
                            },
                            {
                                "slug": "cells",
                                "display_name": "Cells",
                                "vtse_template": {
                                    "strategy_id": "clustered_trait_list",
                                    "payload": {
                                        "steps": [
                                            {"label": "A", "summary": "a"},
                                            {"label": "B", "summary": "b"},
                                            {"label": "C", "summary": "c"},
                                        ]
                                    },
                                },
                            },
                        ],
                    }
                ],
            }
        ]
    }
    tree_svc = MagicMock()
    tree_svc.get_tree = AsyncMock(return_value=tree)
    svc = CurriculumValidationService(tree_service=tree_svc)
    result = await svc.validate(MagicMock())
    codes = [e.code for e in result.errors]
    assert "MISSING_VTSE_TEMPLATE" not in codes
    assert result.ready_to_publish is True
