"""API schema round-trip for Visual Teaching connection metadata."""

from __future__ import annotations

from app.api.schemas.curriculum_structure import (
    ConceptVisualTeachingIn,
    visual_teaching_to_out,
)
from app.services.visual_teaching.authored import (
    ConceptVisualTeaching,
    VisualTeachingAnchor,
    VisualTeachingConnection,
    VisualTeachingImage,
    normalize_visual_teaching,
)


def test_connection_teaching_purpose_survives_api_in_normalize_out():
    """FE → ConceptVisualTeachingIn → normalize → Out must keep purpose/style."""
    body = ConceptVisualTeachingIn.model_validate(
        {
            "images": [
                {
                    "asset_key": "heart",
                    "storage_key": "vt/heart.jpg",
                    "teaching_purpose": "Show blood flow",
                    "annotations_status": "confirmed",
                    "regions": [],
                    "anchors": [
                        {
                            "anchor_id": "body_to_right_atrium_from",
                            "point": {"x": 0.1, "y": 0.5},
                        },
                        {
                            "anchor_id": "body_to_right_atrium_to",
                            "point": {"x": 0.5, "y": 0.4},
                        },
                    ],
                    "connections": [
                        {
                            "connection_id": "body_to_right_atrium",
                            "from_anchor": "body_to_right_atrium_from",
                            "to_anchor": "body_to_right_atrium_to",
                            "label": "Blood returning to the heart",
                            "teaching_purpose": (
                                "Show deoxygenated blood moving from the body "
                                "into the right atrium"
                            ),
                            "color": "#0ea5e9",
                            "label_bg_color": "#0f172a",
                            "label_text_color": "#f8fafc",
                            "label_box": {
                                "x": 0.2,
                                "y": 0.3,
                                "w": 0.25,
                                "h": 0.08,
                            },
                        }
                    ],
                }
            ]
        }
    )
    # Simulate service path: In model → dump → normalize → persist dump → Out
    raw = body.model_dump()
    pkg = normalize_visual_teaching(raw)
    assert pkg is not None
    conn = pkg.images[0].connections[0]
    assert conn.connection_id == "body_to_right_atrium"
    assert conn.teaching_purpose.startswith("Show deoxygenated")
    assert conn.color == "#0ea5e9"
    assert conn.label_bg_color == "#0f172a"
    assert conn.label_text_color == "#f8fafc"
    assert conn.label_box == {"x": 0.2, "y": 0.3, "w": 0.25, "h": 0.08}
    assert conn.kind == "flow"

    out = visual_teaching_to_out(pkg)
    cout = out.images[0].connections[0]
    assert cout.teaching_purpose.startswith("Show deoxygenated")
    assert cout.color == "#0ea5e9"
    assert cout.label_box["w"] == 0.25
    assert cout.kind == "flow"


def test_frozen_snapshot_preserves_teaching_purpose():
    pkg = ConceptVisualTeaching(
        images=[
            VisualTeachingImage(
                asset_key="heart",
                storage_key="heart.jpg",
                teaching_purpose="x",
                anchors=[
                    VisualTeachingAnchor(
                        anchor_id="a1", point={"x": 0.1, "y": 0.1}
                    ),
                    VisualTeachingAnchor(
                        anchor_id="a2", point={"x": 0.9, "y": 0.9}
                    ),
                ],
                connections=[
                    VisualTeachingConnection(
                        connection_id="body_to_right_atrium",
                        from_anchor="a1",
                        to_anchor="a2",
                        label="Flow",
                        teaching_purpose="Show venous return",
                        kind="flow",
                        color="#ef4444",
                    )
                ],
            )
        ]
    )
    snap = pkg.model_dump()
    restored = normalize_visual_teaching(snap)
    assert restored is not None
    c = restored.images[0].connections[0]
    assert c.teaching_purpose == "Show venous return"
    assert c.color == "#ef4444"
