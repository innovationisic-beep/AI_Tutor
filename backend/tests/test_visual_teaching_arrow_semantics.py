"""Arrow semantic authoring + planner context + combined VisualState."""

from __future__ import annotations

from app.services.visual_teaching.authored import (
    ConceptVisualTeaching,
    VisualTeachingAnchor,
    VisualTeachingConnection,
    VisualTeachingImage,
    VisualTeachingRegion,
    normalize_visual_teaching_connections,
)
from app.services.visual_teaching.plan_schema import (
    VisualState,
    apply_visual_state_patch,
)
from app.services.visual_teaching.planner import (
    _PLANNER_SYSTEM,
    _images_for_prompt,
)
from app.services.visual_teaching.validate import (
    VisualTeachingPlanError,
    validate_plan_payload,
)
import pytest


def _pkg_with_arrow():
    return ConceptVisualTeaching(
        images=[
            VisualTeachingImage(
                id="1",
                asset_key="heart",
                storage_key="heart.jpg",
                teaching_purpose="Show blood flow into the heart",
                annotations_status="confirmed",
                regions=[
                    VisualTeachingRegion(
                        region_id="right_atrium",
                        label="Right atrium",
                        teaching_purpose="Chamber that receives blood from the body",
                        shape="rect",
                        geometry={"x": 0.4, "y": 0.3, "w": 0.2, "h": 0.2},
                    )
                ],
                anchors=[
                    VisualTeachingAnchor(
                        anchor_id="body_to_right_atrium_from",
                        point={"x": 0.1, "y": 0.5},
                    ),
                    VisualTeachingAnchor(
                        anchor_id="body_to_right_atrium_to",
                        point={"x": 0.45, "y": 0.4},
                    ),
                ],
                connections=[
                    VisualTeachingConnection(
                        connection_id="body_to_right_atrium",
                        from_anchor="body_to_right_atrium_from",
                        to_anchor="body_to_right_atrium_to",
                        label="Blood returning to the heart",
                        teaching_purpose=(
                            "Show deoxygenated blood moving from the body "
                            "into the right atrium"
                        ),
                        kind="flow",
                    )
                ],
            )
        ]
    )


def test_planner_semantic_context_includes_arrow_purpose_not_coords():
    ctx = _images_for_prompt(_pkg_with_arrow())
    assert len(ctx) == 1
    img = ctx[0]
    assert "connections" not in img
    assert "anchors" not in img
    arrows = img["arrows"]
    assert len(arrows) == 1
    arrow = arrows[0]
    assert arrow == {
        "arrow_id": "body_to_right_atrium",
        "label": "Blood returning to the heart",
        "teaching_purpose": (
            "Show deoxygenated blood moving from the body "
            "into the right atrium"
        ),
    }
    # No geometry / kind / endpoint ids in planner semantic context.
    assert "from_anchor" not in arrow
    assert "to_anchor" not in arrow
    assert "kind" not in arrow
    assert "x" not in arrow


def test_planner_prompt_allows_highlight_plus_arrow():
    assert "NOT mutually exclusive" in _PLANNER_SYSTEM
    assert "teaching_purpose" in _PLANNER_SYSTEM
    assert "right_atrium" in _PLANNER_SYSTEM
    assert "body_to_right_atrium" in _PLANNER_SYSTEM
    assert "labels_visible" in _PLANNER_SYSTEM
    assert "ALSO include that same region_id in labels_visible" in _PLANNER_SYSTEM


def test_normalize_arrow_defaults_kind_flow_and_keeps_purpose():
    out = normalize_visual_teaching_connections(
        [
            {
                "connection_id": "body_to_right_atrium",
                "from_anchor": "a1",
                "to_anchor": "a2",
                "label": "Blood returning to the heart",
                "teaching_purpose": "Show flow into the atrium",
                # kind omitted — must default to flow
            }
        ],
        anchor_ids=["a1", "a2"],
    )
    assert len(out) == 1
    assert out[0].kind == "flow"
    assert out[0].teaching_purpose == "Show flow into the atrium"
    assert out[0].connection_id == "body_to_right_atrium"


def test_normalize_invalid_kind_falls_back_to_flow():
    out = normalize_visual_teaching_connections(
        [
            {
                "connection_id": "a1",
                "from_anchor": "a1",
                "to_anchor": "a2",
                "kind": "not-a-real-kind",
            }
        ],
        anchor_ids=["a1", "a2"],
    )
    assert out[0].kind == "flow"


def test_visual_state_highlight_and_arrow_together():
    state = VisualState(
        highlights=["right_atrium"],
        arrows=["body_to_right_atrium"],
    )
    assert state.highlights == ["right_atrium"]
    assert state.arrows == ["body_to_right_atrium"]


def test_patch_arrows_omitting_highlights_preserves_highlights():
    base = VisualState(
        highlights=["right_atrium"],
        arrows=["old_arrow"],
        pointer="right_atrium",
    )
    out = apply_visual_state_patch(base, {"arrows": ["body_to_right_atrium"]})
    assert out.highlights == ["right_atrium"]
    assert out.arrows == ["body_to_right_atrium"]
    assert out.pointer == "right_atrium"


def test_patch_can_replace_highlights_and_arrows_together():
    base = VisualState(highlights=["a"], arrows=["x"])
    out = apply_visual_state_patch(
        base,
        {"highlights": ["right_atrium"], "arrows": ["body_to_right_atrium"]},
    )
    assert out.highlights == ["right_atrium"]
    assert out.arrows == ["body_to_right_atrium"]


def test_unknown_arrow_rejected():
    with pytest.raises(VisualTeachingPlanError, match="unknown arrow"):
        validate_plan_payload(
            {
                "capabilities_used": ["highlights", "arrows"],
                "scenes": [
                    {
                        "asset_key": "heart",
                        "beats": [
                            {
                                "id": "b1",
                                "speak": "Blood enters the right atrium.",
                                "visual_state": {
                                    "highlights": ["right_atrium"],
                                    "arrows": ["invented_arrow"],
                                },
                                "writes": [],
                            }
                        ],
                    }
                ],
            },
            authored=_pkg_with_arrow(),
        )


def test_highlight_plus_authored_arrow_plan_accepted():
    plan = validate_plan_payload(
        {
            "capabilities_used": ["highlights", "arrows", "labels_visible"],
            "scenes": [
                {
                    "asset_key": "heart",
                    "beats": [
                        {
                            "id": "b1",
                            "speak": "Blood enters the right atrium from the body.",
                            "visual_state": {
                                "highlights": ["right_atrium"],
                                "labels_visible": ["right_atrium"],
                                "arrows": ["body_to_right_atrium"],
                            },
                            "writes": [],
                        }
                    ],
                }
            ],
        },
        authored=_pkg_with_arrow(),
    )
    vs = plan.scenes[0].beats[0].visual_state
    assert vs.highlights == ["right_atrium"]
    assert vs.labels_visible == ["right_atrium"]
    assert vs.arrows == ["body_to_right_atrium"]
