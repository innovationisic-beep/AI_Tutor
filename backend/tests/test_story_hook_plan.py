"""Story Hook plan validation — the backend, not the LLM, owns the contract."""

from __future__ import annotations

import pytest

from app.services.story_hook.plan_schema import (
    MAX_STEPS,
    PLAN_SOURCE_FALLBACK,
    StoryHookPlanError,
    build_fallback_plan,
    parse_plan_json,
    validate_plan_payload,
)


def _payload(*steps: dict) -> dict:
    return {"steps": list(steps)}


def test_accepts_minimal_narration_plan() -> None:
    plan = validate_plan_payload(
        _payload(
            {"type": "narration", "text": "Every leaf breathes."},
            {"type": "finish", "text": "Let's find out how."},
        ),
        allowed_asset_keys=[],
        language="english",
    )
    assert [s.type for s in plan.steps] == ["narration", "finish"]
    assert plan.question_count == 0
    assert plan.source == "planner"
    assert plan.writing_mode == "notes"


def test_planner_plan_accepts_optional_note_and_empty_note() -> None:
    plan = validate_plan_payload(
        _payload(
            {
                "type": "narration",
                "text": (
                    "Imagine a leaf with hundreds of tiny gates. "
                    "The plant opens them for carbon dioxide."
                ),
                "note": "Stomata = tiny leaf gates",
            },
            {
                "type": "narration",
                "text": "Now here is the interesting part.",
                "note": "",
            },
            {"type": "finish", "text": "Let's keep going.", "note": "Trade-off: CO₂ vs water"},
        ),
        allowed_asset_keys=[],
        language="english",
    )
    assert plan.writing_mode == "notes"
    assert plan.steps[0].note == "Stomata = tiny leaf gates"
    assert plan.steps[1].note == ""
    assert plan.steps[2].note == "Trade-off: CO₂ vs water"


def test_planner_plan_normalizes_source_sentence_writes() -> None:
    plan = validate_plan_payload(
        _payload(
            {
                "type": "narration",
                "text": (
                    "Imagine a leaf with hundreds of tiny gates. "
                    "The plant opens them for carbon dioxide."
                ),
                "writes": [
                    {
                        "source_sentence": "Imagine a leaf with hundreds of tiny gates.",
                        "text": "Stomata = tiny leaf gates",
                    }
                ],
            },
            {"type": "finish", "text": "Let's keep going."},
        ),
        allowed_asset_keys=[],
        language="english",
    )
    assert len(plan.steps[0].writes) == 1
    assert plan.steps[0].writes[0].sentence_index == 0
    assert plan.steps[0].writes[0].text == "Stomata = tiny leaf gates"
    assert plan.steps[0].note == "Stomata = tiny leaf gates"


def test_question_writes_are_ignored() -> None:
    plan = validate_plan_payload(
        _payload(
            {"type": "narration", "text": "Leaves breathe."},
            {
                "type": "question",
                "text": "Why close the pores?",
                "writes": [
                    {
                        "source_sentence": "Why close the pores?",
                        "text": "should be ignored",
                    }
                ],
            },
        ),
        allowed_asset_keys=[],
        language="english",
    )
    assert plan.steps[1].type == "question"
    assert plan.steps[1].writes == []
    assert plan.steps[1].note == ""


def test_question_note_is_ignored() -> None:
    plan = validate_plan_payload(
        _payload(
            {"type": "narration", "text": "Leaves breathe."},
            {
                "type": "question",
                "text": "Why close the pores?",
                "note": "should be ignored",
            },
        ),
        allowed_asset_keys=[],
        language="english",
    )
    assert plan.steps[1].type == "question"
    assert plan.steps[1].note == ""


def test_hinglish_rejects_devanagari_in_note() -> None:
    with pytest.raises(StoryHookPlanError, match="Roman script"):
        validate_plan_payload(
            _payload(
                {
                    "type": "narration",
                    "text": "Stomata are tiny pores.",
                    "note": "पत्तियाँ",
                }
            ),
            allowed_asset_keys=[],
            language="hinglish",
        )


def test_old_stored_plan_without_note_loads_as_legacy() -> None:
    from app.services.story_hook.plan_schema import plan_from_stored

    plan = plan_from_stored(
        {
            "steps": [{"type": "narration", "text": "Old session step."}],
            "language": "english",
            "source": "planner",
        }
    )
    assert plan is not None
    assert plan.writing_mode == "legacy"
    assert plan.steps[0].note == ""


def test_parses_fenced_json_and_surrounding_prose() -> None:
    raw = 'Here you go:\n```json\n{"steps": [{"type": "narration", "text": "Hi"}]}\n```'
    assert parse_plan_json(raw) == {"steps": [{"type": "narration", "text": "Hi"}]}


def test_pause_steps_are_dropped() -> None:
    plan = validate_plan_payload(
        _payload(
            {"type": "narration", "text": "Look closely."},
            {"type": "pause"},
            {"type": "narration", "text": "Now look again."},
        ),
        allowed_asset_keys=[],
        language="english",
    )
    assert [s.type for s in plan.steps] == ["narration", "narration"]


def test_every_attached_visual_must_be_used() -> None:
    with pytest.raises(StoryHookPlanError, match="exactly once"):
        validate_plan_payload(
            _payload(
                {"type": "narration", "text": "A leaf."},
                {"type": "visual", "text": "See the pores.", "asset_key": "surface"},
            ),
            allowed_asset_keys=["surface", "cross_section"],
            language="english",
        )


def test_unknown_asset_key_is_rejected() -> None:
    with pytest.raises(StoryHookPlanError, match="unknown asset_key"):
        validate_plan_payload(
            _payload({"type": "visual", "text": "Look.", "asset_key": "invented"}),
            allowed_asset_keys=["surface"],
            language="english",
        )


def test_repeated_asset_key_is_rejected() -> None:
    with pytest.raises(StoryHookPlanError, match="more than once"):
        validate_plan_payload(
            _payload(
                {"type": "visual", "text": "Once.", "asset_key": "surface"},
                {"type": "visual", "text": "Twice.", "asset_key": "surface"},
            ),
            allowed_asset_keys=["surface"],
            language="english",
        )


def test_visual_step_requires_spoken_text() -> None:
    with pytest.raises(StoryHookPlanError, match="spoken line"):
        validate_plan_payload(
            _payload(
                {"type": "narration", "text": "Here."},
                {"type": "visual", "asset_key": "surface"},
            ),
            allowed_asset_keys=["surface"],
            language="english",
        )


def test_question_cap_is_enforced() -> None:
    with pytest.raises(StoryHookPlanError, match="at most 2"):
        validate_plan_payload(
            _payload(
                {"type": "narration", "text": "Leaves breathe."},
                {"type": "question", "text": "What do you think?"},
                {"type": "question", "text": "And why?"},
                {"type": "question", "text": "Anything else?"},
            ),
            allowed_asset_keys=[],
            language="english",
        )


def test_two_questions_allowed() -> None:
    plan = validate_plan_payload(
        _payload(
            {"type": "narration", "text": "Leaves breathe."},
            {"type": "question", "text": "What do you think?"},
            {"type": "question", "text": "And why?"},
        ),
        allowed_asset_keys=[],
        language="english",
    )
    assert plan.question_count == 2


def test_nothing_may_follow_finish() -> None:
    with pytest.raises(StoryHookPlanError, match="follow the finish"):
        validate_plan_payload(
            _payload(
                {"type": "finish", "text": "Done."},
                {"type": "narration", "text": "One more thing."},
            ),
            allowed_asset_keys=[],
            language="english",
        )


def test_unsupported_step_type_is_rejected() -> None:
    with pytest.raises(StoryHookPlanError, match="unsupported type"):
        validate_plan_payload(
            _payload({"type": "quiz", "text": "Pick one."}),
            allowed_asset_keys=[],
            language="english",
        )


def test_step_ceiling_is_enforced() -> None:
    with pytest.raises(StoryHookPlanError, match="at most"):
        validate_plan_payload(
            _payload(
                *[
                    {"type": "narration", "text": f"Beat {i}."}
                    for i in range(MAX_STEPS + 1)
                ]
            ),
            allowed_asset_keys=[],
            language="english",
        )


def test_hinglish_rejects_devanagari() -> None:
    with pytest.raises(StoryHookPlanError, match="Roman script"):
        validate_plan_payload(
            _payload({"type": "narration", "text": "पत्तियाँ saans leti hain."}),
            allowed_asset_keys=[],
            language="hinglish",
        )


def test_hinglish_accepts_roman_script_with_english_terms() -> None:
    plan = validate_plan_payload(
        _payload(
            {
                "type": "narration",
                "text": "Stomata leaves par chhote pores hote hain jo gas exchange karte hain.",
            }
        ),
        allowed_asset_keys=[],
        language="hinglish",
    )
    assert plan.language == "hinglish"


def test_english_plan_is_not_script_checked() -> None:
    plan = validate_plan_payload(
        _payload({"type": "narration", "text": "Leaves breathe through stomata."}),
        allowed_asset_keys=[],
        language="english",
    )
    assert plan.language == "english"


def test_non_object_payload_is_rejected() -> None:
    with pytest.raises(StoryHookPlanError, match="JSON object"):
        validate_plan_payload([], allowed_asset_keys=[], language="english")


def test_empty_steps_rejected() -> None:
    with pytest.raises(StoryHookPlanError, match="non-empty array"):
        validate_plan_payload({"steps": []}, allowed_asset_keys=[], language="english")


def test_fallback_plan_narrates_seed_and_uses_every_visual() -> None:
    plan = build_fallback_plan(
        seed="A leaf is a city with millions of tiny doors.",
        title="City of doors",
        visuals=[
            {"asset_key": "surface", "description": "Pores on a leaf surface"},
            {"asset_key": "cross_section", "description": ""},
        ],
    )
    assert plan.source == PLAN_SOURCE_FALLBACK
    assert plan.writing_mode == "legacy"
    assert plan.steps[0].type == "narration"
    assert "tiny doors" in plan.steps[0].text
    assert [s.asset_key for s in plan.steps if s.type == "visual"] == [
        "surface",
        "cross_section",
    ]
    # A visual with no authored description still gets something spoken.
    assert all(s.text for s in plan.steps)


def test_fallback_plan_never_empty() -> None:
    plan = build_fallback_plan(seed="", title="")
    assert plan.steps and plan.steps[0].text
