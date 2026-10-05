"""Authored package + stale-on-replace semantics."""

from app.services.visual_teaching.authored import (
    VisualTeachingImage,
    mark_image_annotations_stale,
    normalize_visual_teaching,
)


def test_normalize_drops_missing_storage():
    pkg = normalize_visual_teaching(
        {
            "images": [
                {
                    "asset_key": "a",
                    "storage_key": "",
                    "regions": [],
                },
                {
                    "asset_key": "b",
                    "storage_key": "b.jpg",
                    "regions": [
                        {
                            "region_id": "r1",
                            "shape": "rect",
                            "geometry": {"x": 0, "y": 0, "w": 0.5, "h": 0.5},
                        }
                    ],
                },
            ]
        }
    )
    assert pkg is not None
    assert len(pkg.images) == 1
    assert pkg.images[0].asset_key == "b"


def test_replace_always_stales():
    img = VisualTeachingImage(
        id="1",
        asset_key="leaf",
        storage_key="old.jpg",
        annotations_status="confirmed",
        natural_width=100,
        natural_height=100,
    )
    stale = mark_image_annotations_stale(img)
    assert stale.annotations_status == "stale"
    # Same dimensions would not clear stale — author must reconfirm
    assert stale.natural_width == 100
