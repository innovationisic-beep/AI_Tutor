"""Hand-authored Photosynthesis CIR v1 example (test fixture)."""

from __future__ import annotations

from typing import Any

from app.cir.template_emit import cir_v1_dict_from_template_steps


def photosynthesis_cir_v1() -> dict[str, Any]:
    """
    Minimal Photosynthesis explanation as CIR v1 (three beats, hub-friendly edges).
    """
    steps = [
        {
            "title": "Sunlight Capture",
            "annotation": "Leaves absorb sunlight energy.",
            "narration": "A plant starts by capturing sunlight in its leaves.",
        },
        {
            "title": "Input Mixing",
            "annotation": "Water and carbon dioxide are combined.",
            "narration": "The plant combines water and carbon dioxide using that energy.",
        },
        {
            "title": "Sugar Output",
            "annotation": "Glucose is made and oxygen is released.",
            "narration": "That process creates sugar for the plant and releases oxygen.",
        },
    ]
    return cir_v1_dict_from_template_steps(
        representation_type="hierarchy",
        topic="Photosynthesis",
        canonical_tag="photosynthesis",
        steps=steps,
    )
