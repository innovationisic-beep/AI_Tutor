"""Curriculum tree must surface Visual Teaching packages to the builder UI."""

from __future__ import annotations

from types import SimpleNamespace

from app.services.curriculum.curriculum_tree_service import _concept_dict


def test_concept_dict_includes_visual_teaching_images():
    concept = SimpleNamespace(
        id="cid",
        curriculum_zone_id="zid",
        curriculum_cluster_id="clid",
        slug="stomata",
        display_name="Stomata",
        canonical_runtime_key="stomata",
        sort_order=0,
        difficulty_level="basic",
        estimated_learning_minutes=None,
        study_points=[],
        learning_outcomes=[],
        story_hook=None,
        visual_teaching={
            "images": [
                {
                    "id": "img1",
                    "asset_key": "leaf_surface",
                    "storage_key": "leaf-abc.png",
                    "mime_type": "image/png",
                    "teaching_purpose": "Show the pore",
                    "annotations_status": "confirmed",
                    "regions": [],
                    "anchors": [],
                    "connections": [],
                }
            ]
        },
        teaching_sequence=["vtse", "visual_teaching"],
        vtse_template=None,
        status="draft",
        published_revision=0,
    )

    out = _concept_dict(concept)

    assert out["visual_teaching"] is not None
    assert len(out["visual_teaching"]["images"]) == 1
    assert out["visual_teaching"]["images"][0]["asset_key"] == "leaf_surface"
    assert out["visual_teaching"]["images"][0]["storage_key"] == "leaf-abc.png"
    assert out["visual_teaching"]["images"][0]["teaching_purpose"] == "Show the pore"


def test_concept_dict_visual_teaching_none_when_empty():
    concept = SimpleNamespace(
        id="cid",
        curriculum_zone_id="zid",
        curriculum_cluster_id="clid",
        slug="stomata",
        display_name="Stomata",
        canonical_runtime_key="stomata",
        sort_order=0,
        difficulty_level="basic",
        estimated_learning_minutes=None,
        study_points=[],
        learning_outcomes=[],
        story_hook=None,
        visual_teaching={"images": []},
        teaching_sequence=["vtse"],
        vtse_template=None,
        status="draft",
        published_revision=0,
    )

    assert _concept_dict(concept)["visual_teaching"] is None
