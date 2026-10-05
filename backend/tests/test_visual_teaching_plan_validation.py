"""Tests for Visual Teaching plan validation + capabilities."""

import pytest

from app.services.visual_teaching.authored import ConceptVisualTeaching, VisualTeachingImage, VisualTeachingRegion
from app.services.visual_teaching.validate import (
    VisualTeachingPlanError,
    validate_plan_payload,
)


def _pkg():
    return ConceptVisualTeaching(
        images=[
            VisualTeachingImage(
                id="1",
                asset_key="leaf",
                storage_key="leaf.jpg",
                teaching_purpose="Show stomata",
                annotations_status="confirmed",
                regions=[
                    VisualTeachingRegion(
                        region_id="guard",
                        label="Guard cells",
                        shape="rect",
                        geometry={"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2},
                    )
                ],
            )
        ]
    )


def test_valid_plan():
    plan = validate_plan_payload(
        {
            "capabilities_used": ["highlights", "pointer"],
            "scenes": [
                {
                    "asset_key": "leaf",
                    "beats": [
                        {
                            "id": "b1",
                            "speak": "Look at the guard cells.",
                            "visual_state": {
                                "highlights": ["guard"],
                                "pointer": "guard",
                            },
                            "writes": [],
                        }
                    ],
                }
            ],
        },
        authored=_pkg(),
    )
    assert len(plan.scenes) == 1
    assert plan.scenes[0].beats[0].visual_state.pointer == "guard"


def test_reorder_rejected():
    with pytest.raises(VisualTeachingPlanError):
        validate_plan_payload(
            {
                "scenes": [
                    {
                        "asset_key": "wrong",
                        "beats": [{"id": "b1", "speak": "Hi.", "visual_state": {}}],
                    }
                ]
            },
            authored=_pkg(),
        )


def test_unknown_region_rejected():
    with pytest.raises(VisualTeachingPlanError):
        validate_plan_payload(
            {
                "scenes": [
                    {
                        "asset_key": "leaf",
                        "beats": [
                            {
                                "id": "b1",
                                "speak": "Hi.",
                                "visual_state": {"highlights": ["nope"]},
                            }
                        ],
                    }
                ]
            },
            authored=_pkg(),
        )
