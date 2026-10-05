"""Process storyboard identity / explanation splitting."""

from __future__ import annotations

from app.vtse.authoring.process_step_content import split_process_step_content


def test_split_step_prefix_mouth() -> None:
    display, identity, explanation = split_process_step_content(
        "Step 1 — Mouth: food is chewed and mixed with saliva.",
        index=0,
    )
    assert display == "Step 1"
    assert identity.lower() == "mouth"
    assert "chewed" in explanation.lower()


def test_split_in_the_mouth_from_prose() -> None:
    display, identity, explanation = split_process_step_content(
        "Digestion begins in the mouth where food is chewed.",
        index=0,
    )
    assert display == "Step 1"
    assert "mouth" in identity.lower()
    assert len(explanation) > len(identity)


def test_identity_not_generic_step_number() -> None:
    _, identity, _ = split_process_step_content("Step 2 — Stomach", index=1)
    assert identity.lower() == "stomach"
