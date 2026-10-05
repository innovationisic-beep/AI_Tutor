"""
Story Hook planner grounding, retry and fallback.

Concept richness comes from the authored VTSE template only — never TopicNotes,
the authoring expander, or CIR.
"""

from __future__ import annotations

import json

import pytest

from app.services.story_hook import planner as planner_module
from app.services.story_hook.planner import (
    build_outline,
    build_planner_prompt,
    plan_story_hook,
)

STOMATA_TEMPLATE = {
    "strategy_id": "clustered_trait_list",
    "payload": {
        "steps": [
            {
                "label": "Stomata",
                "summary": "Tiny pores on the leaf surface, mostly on the underside.",
            },
            {
                "label": "Guard cells",
                "summary": "Two curved cells that swell and shrink to open or close the pore.",
            },
            {
                "label": "Gas exchange",
                "summary": "Carbon dioxide enters and oxygen leaves through the open pore.",
            },
            {
                "label": "Transpiration",
                "summary": "Water vapour escapes, which is why stomata close in dry heat.",
            },
        ]
    },
}

HOOK = {
    "title": "City of tiny doors",
    "body": "A leaf is a city with millions of doors that open at dawn.",
    "teacher_intent": "Emphasise that the plant controls the doors.",
    "visuals": [
        {
            "asset_key": "stomata_surface",
            "storage_key": "leaf-abc.png",
            "description": "Microscope view of pores on a leaf underside",
            "teaching_purpose": "Show how many pores there really are",
        },
        {
            "asset_key": "guard_cells",
            "storage_key": "guard-def.png",
            "description": "Two guard cells around one open pore",
            "teaching_purpose": "Show what actually opens and closes",
        },
    ],
}


class _Concept:
    def __init__(self, template=STOMATA_TEMPLATE) -> None:
        self.vtse_template = template
        self.display_name = "Stomata"


def _valid_plan_json() -> str:
    return json.dumps(
        {
            "steps": [
                {"type": "narration", "text": "A leaf is quietly breathing right now."},
                {
                    "type": "visual",
                    "text": "Look at how many pores there are.",
                    "asset_key": "stomata_surface",
                },
                {"type": "question", "text": "Why open them only sometimes?"},
                {
                    "type": "visual",
                    "text": "These two guard cells do the opening.",
                    "asset_key": "guard_cells",
                },
                {"type": "finish", "text": "Let's see how the plant decides."},
            ]
        }
    )


# ── Grounding ────────────────────────────────────────────────────────────────


def test_outline_comes_from_vtse_template_without_the_seed() -> None:
    outline = build_outline(_Concept(), concept_label="Stomata")
    assert "Guard cells" in outline
    assert "Transpiration" in outline
    # The seed is a separate planner input and must not appear as a "fact".
    assert "city with millions of doors" not in outline
    assert "Story hook" not in outline


def test_outline_empty_when_no_template_authored() -> None:
    assert build_outline(_Concept(template=None), concept_label="Stomata") == ""


def test_prompt_carries_outline_seed_intent_and_visual_metadata() -> None:
    prompt = build_planner_prompt(
        concept_label="Stomata",
        seed=HOOK["body"],
        title=HOOK["title"],
        teacher_intent=HOOK["teacher_intent"],
        outline=build_outline(_Concept(), concept_label="Stomata"),
        visuals=HOOK["visuals"],
    )
    assert "AUTHORITATIVE_CONCEPT_OUTLINE" in prompt
    assert "Guard cells" in prompt
    assert "city with millions of doors" in prompt
    assert "plant controls the doors" in prompt
    assert "stomata_surface" in prompt
    assert "Show what actually opens and closes" in prompt
    assert "exactly once" in prompt


def test_prompt_never_leaks_storage_keys_or_ids() -> None:
    prompt = build_planner_prompt(
        concept_label="Stomata",
        seed=HOOK["body"],
        title=HOOK["title"],
        teacher_intent="",
        outline="",
        visuals=HOOK["visuals"],
    )
    assert "leaf-abc.png" not in prompt
    assert "storage_key" not in prompt


def test_prompt_without_visuals_forbids_visual_steps() -> None:
    prompt = build_planner_prompt(
        concept_label="Stomata",
        seed=HOOK["body"],
        title="",
        teacher_intent="",
        outline="",
        visuals=[],
    )
    assert "do not use visual steps" in prompt


def test_planner_never_reaches_for_deprecated_teaching_sources() -> None:
    """
    Richness must come from the authored VTSE outline. TopicNotes, the authoring
    expander and CIR are deliberately out of the planner's reach.
    """
    import inspect

    source = inspect.getsource(planner_module)
    for forbidden in (
        "TopicNotes",
        "topic_notes",
        "concept_notes_markdown",
        "expand_authored_vtse_template",
        "concept_inference",
    ):
        assert forbidden not in source


def test_prompt_warns_when_no_outline_authored() -> None:
    prompt = build_planner_prompt(
        concept_label="Stomata",
        seed=HOOK["body"],
        title="",
        teacher_intent="",
        outline="",
        visuals=[],
    )
    assert "Do not invent specific curriculum facts." in prompt


# ── Planning, retry and fallback ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_plan_uses_validated_llm_output(monkeypatch) -> None:
    calls: list[str] = []

    async def fake_llm(user_content, *, system_content="", **_kwargs):
        calls.append(user_content)
        return _valid_plan_json()

    monkeypatch.setattr(planner_module, "llm_call", fake_llm)
    plan = await plan_story_hook(
        concept=_Concept(), hook=HOOK, concept_label="Stomata"
    )

    assert len(calls) == 1
    assert plan.source == "planner"
    assert plan.question_count == 1
    assert [s.asset_key for s in plan.steps if s.type == "visual"] == [
        "stomata_surface",
        "guard_cells",
    ]


@pytest.mark.asyncio
async def test_invalid_plan_retries_once_with_the_reason(monkeypatch) -> None:
    prompts: list[str] = []

    async def fake_llm(user_content, *, system_content="", **_kwargs):
        prompts.append(user_content)
        if len(prompts) == 1:
            # Unknown asset + missing the attached ones.
            return json.dumps(
                {"steps": [{"type": "visual", "text": "Look", "asset_key": "nope"}]}
            )
        return _valid_plan_json()

    monkeypatch.setattr(planner_module, "llm_call", fake_llm)
    plan = await plan_story_hook(
        concept=_Concept(), hook=HOOK, concept_label="Stomata"
    )

    assert len(prompts) == 2
    assert "Your previous answer was rejected" in prompts[1]
    assert "unknown asset_key" in prompts[1]
    assert plan.source == "planner"


@pytest.mark.asyncio
async def test_two_failures_fall_back_to_seed_narration(monkeypatch) -> None:
    async def fake_llm(user_content, *, system_content="", **_kwargs):
        return "I cannot do that."

    monkeypatch.setattr(planner_module, "llm_call", fake_llm)
    plan = await plan_story_hook(
        concept=_Concept(), hook=HOOK, concept_label="Stomata"
    )

    assert plan.source == "fallback"
    assert "city with millions of doors" in plan.steps[0].text
    # Authored visuals are still shown rather than silently dropped.
    assert [s.asset_key for s in plan.steps if s.type == "visual"] == [
        "stomata_surface",
        "guard_cells",
    ]


@pytest.mark.asyncio
async def test_rich_outline_survives_into_the_plan(monkeypatch) -> None:
    """A three-word seed must not shrink the teaching — the outline carries it."""
    captured: list[str] = []

    async def fake_llm(user_content, *, system_content="", **_kwargs):
        captured.append(user_content)
        return json.dumps(
            {
                "steps": [
                    {"type": "narration", "text": "Tiny pores cover the leaf underside."},
                    {
                        "type": "visual",
                        "text": "Two guard cells swell to open each pore.",
                        "asset_key": "stomata_surface",
                    },
                    {
                        "type": "visual",
                        "text": "Carbon dioxide enters while water vapour escapes.",
                        "asset_key": "guard_cells",
                    },
                    {"type": "finish", "text": "Now let's see when they close."},
                ]
            }
        )

    monkeypatch.setattr(planner_module, "llm_call", fake_llm)
    plan = await plan_story_hook(
        concept=_Concept(),
        hook={**HOOK, "body": "Leaf doors."},
        concept_label="Stomata",
    )

    for fact in ("Guard cells", "Gas exchange", "Transpiration"):
        assert fact in captured[0]
    assert plan.source == "planner"
    assert len(plan.steps) == 4


@pytest.mark.asyncio
async def test_empty_template_falls_back_to_the_seed_without_inventing_science(
    monkeypatch,
) -> None:
    async def fake_llm(user_content, *, system_content="", **_kwargs):
        return None

    monkeypatch.setattr(planner_module, "llm_call", fake_llm)
    plan = await plan_story_hook(
        concept=_Concept(template=None),
        hook={"title": "T", "body": "A leaf is a city of doors.", "visuals": []},
        concept_label="Stomata",
    )

    assert plan.source == "fallback"
    assert [s.text for s in plan.steps if s.type == "narration"] == [
        "A leaf is a city of doors."
    ]


@pytest.mark.asyncio
async def test_llm_unavailable_falls_back_without_raising(monkeypatch) -> None:
    async def fake_llm(user_content, *, system_content="", **_kwargs):
        return None

    monkeypatch.setattr(planner_module, "llm_call", fake_llm)
    plan = await plan_story_hook(
        concept=_Concept(), hook=HOOK, concept_label="Stomata"
    )
    assert plan.source == "fallback"
    assert plan.steps


@pytest.mark.asyncio
async def test_hinglish_and_english_share_the_same_english_outline(monkeypatch) -> None:
    seen: dict[str, list[str]] = {"system": [], "user": []}

    async def fake_llm(user_content, *, system_content="", **_kwargs):
        seen["user"].append(user_content)
        seen["system"].append(system_content)
        return _valid_plan_json()

    monkeypatch.setattr(planner_module, "llm_call", fake_llm)
    await plan_story_hook(
        concept=_Concept(), hook=HOOK, concept_label="Stomata", language_mode="english"
    )
    await plan_story_hook(
        concept=_Concept(), hook=HOOK, concept_label="Stomata", language_mode="hinglish"
    )

    # Same factual source in both languages.
    assert seen["user"][0] == seen["user"][1]
    # Only the language policy differs, and only for Hinglish.
    assert "Roman script only" not in seen["system"][0]
    assert "Roman script only" in seen["system"][1]
    assert "NEVER use Devanagari" in seen["system"][1]


@pytest.mark.asyncio
async def test_devanagari_output_is_rejected_for_hinglish(monkeypatch) -> None:
    prompts: list[str] = []

    async def fake_llm(user_content, *, system_content="", **_kwargs):
        prompts.append(user_content)
        return json.dumps(
            {"steps": [{"type": "narration", "text": "पत्ती saans leti hai."}]}
        )

    monkeypatch.setattr(planner_module, "llm_call", fake_llm)
    plan = await plan_story_hook(
        concept=_Concept(),
        hook={"title": "T", "body": "A leaf breathes.", "visuals": []},
        concept_label="Stomata",
        language_mode="hinglish",
    )
    assert len(prompts) == 2
    assert "Roman script" in prompts[1]
    assert plan.source == "fallback"
