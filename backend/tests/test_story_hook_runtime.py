"""
Story Hook runtime — the backend owns stepping, waiting and stage completion.

Uses a stub session so the state machine is tested without a database.
"""

from __future__ import annotations

import json
from typing import Any, Optional

import pytest

from app.services.pedagogy import concept_teaching_orchestrator as cto_module
from app.services.pedagogy.concept_teaching_orchestrator import (
    ConceptTeachingOrchestrator,
)
from app.services.story_hook import planner as planner_module
from app.services.story_hook import runtime as runtime_module

HOOK_SNAPSHOT = {
    "title": "City of tiny doors",
    "body": "A leaf is a city with millions of doors.",
    "teacher_intent": "",
    "visuals": [
        {
            "id": "v1",
            "asset_key": "stomata_surface",
            "storage_key": "leaf-abc.png",
            "description": "Pores on a leaf underside",
            "teaching_purpose": "Show how many there are",
            "mime_type": "image/png",
            "sort_order": 0,
        }
    ],
}

PLAN_JSON = json.dumps(
    {
        "steps": [
            {
                "type": "narration",
                "text": "A leaf is breathing right now.",
                "note": "Leaves breathe",
            },
            {
                "type": "visual",
                "text": "Look at all those pores.",
                "note": "Stomata = tiny pores",
                "asset_key": "stomata_surface",
            },
            {"type": "question", "text": "Why would a plant ever close them?"},
            {"type": "finish", "text": "Let's find out."},
        ]
    }
)

PLAN_JSON_SPEAK_ONLY = json.dumps(
    {
        "steps": [
            {
                "type": "narration",
                "text": "Now here is the interesting part.",
                "note": "",
            },
            {"type": "finish", "text": "Onward.", "note": ""},
        ]
    }
)


class StubSession:
    """Minimal stand-in for the Session document fields the runtime touches."""

    def __init__(self, **overrides: Any) -> None:
        self.current_zone = 1
        self.zone0_phase = "done"
        self.flow_state = "idle"
        self.current_concept = "Stomata"
        self.current_concept_index = 0
        self.key_concept_ids = ["concept-1"]
        self.concept_teaching_for_index = 0
        self.concept_teaching_sequence_snapshot = ["story_hook", "vtse"]
        self.concept_teaching_stage_index = 0
        self.concept_teaching_story_hook_snapshot = dict(HOOK_SNAPSHOT)
        self.concept_teaching_await_vtse_done = False
        self.concept_questions_active = False
        self.story_hook_for_index = -1
        self.story_hook_plan = None
        self.story_hook_step_index = 0
        self.story_hook_status = "idle"
        self.story_hook_pending_question = None
        self.story_hook_qa = []
        self.story_hook_language = "english"
        self.saves = 0
        for key, value in overrides.items():
            setattr(self, key, value)

    async def save(self) -> None:
        self.saves += 1


class StubConcept:
    id = "concept-1"
    display_name = "Stomata"
    vtse_template = {
        "strategy_id": "clustered_trait_list",
        "payload": {
            "steps": [
                {"label": "Stomata", "summary": "Tiny pores on the leaf surface."},
                {"label": "Guard cells", "summary": "They open and close each pore."},
                {"label": "Gas exchange", "summary": "CO2 in, O2 out."},
            ]
        },
    }


@pytest.fixture
def orchestrator(monkeypatch) -> ConceptTeachingOrchestrator:
    async def fake_llm(user_content, *, system_content="", **_kwargs):
        return PLAN_JSON

    async def fake_resolve_mode(_session):
        return "english"

    monkeypatch.setattr(planner_module, "llm_call", fake_llm)
    monkeypatch.setattr(cto_module, "resolve_mode_for_session", fake_resolve_mode)

    cto = ConceptTeachingOrchestrator()

    async def fake_concept(_session) -> Optional[StubConcept]:
        return StubConcept()

    monkeypatch.setattr(cto, "_resolve_current_concept", fake_concept)
    return cto


async def _emit_first(cto: ConceptTeachingOrchestrator, session: StubSession) -> dict:
    result = await cto.maybe_emit(session, action="start")
    session.flow_state = result["flow_state"]
    return result


# ── Stepping ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_first_turn_emits_step_zero_not_the_whole_story(orchestrator) -> None:
    session = StubSession()
    result = await _emit_first(orchestrator, session)

    assert result["type"] == "concept_story_hook"
    assert result["message"] == "A leaf is breathing right now."
    assert result["story_hook_card"]["body"] == "Leaves breathe"
    assert result["story_hook_card"]["spoken_text"] == "A leaf is breathing right now."
    assert result["story_hook_card"]["writing_mode"] == "notes"
    assert result["story_hook_step"]["kind"] == "narration"
    assert result["story_hook_step"]["index"] == 0
    assert result["story_hook_step"]["total"] == 4
    assert result["story_hook_step"]["awaiting"] is False
    assert result["story_hook_step"]["last"] is False
    assert result["story_hook_step"]["writing_mode"] == "notes"
    assert result["story_hook_step"]["note"] == "Leaves breathe"
    assert session.story_hook_status == "playing"
    assert session.story_hook_for_index == 0


@pytest.mark.asyncio
async def test_notes_mode_empty_note_is_speak_only(orchestrator, monkeypatch) -> None:
    async def fake_llm(user_content, *, system_content="", **_kwargs):
        return PLAN_JSON_SPEAK_ONLY

    monkeypatch.setattr(planner_module, "llm_call", fake_llm)
    snap = dict(HOOK_SNAPSHOT)
    snap["visuals"] = []
    session = StubSession(concept_teaching_story_hook_snapshot=snap)
    result = await _emit_first(orchestrator, session)
    assert result["message"] == "Now here is the interesting part."
    assert result["story_hook_card"]["body"] == ""
    assert result["story_hook_card"]["writing_mode"] == "notes"
    assert result["story_hook_step"]["note"] == ""


@pytest.mark.asyncio
async def test_legacy_stored_plan_shows_spoken_text_on_card(orchestrator) -> None:
    session = StubSession(
        story_hook_for_index=0,
        story_hook_plan={
            "steps": [
                {"type": "narration", "text": "Legacy spoken line."},
                {"type": "finish", "text": "Done."},
            ],
            "language": "english",
            "source": "planner",
            "writing_mode": "legacy",
        },
        story_hook_step_index=0,
        story_hook_status="playing",
        story_hook_language="english",
    )
    result = await orchestrator.maybe_emit(session, action="start")
    assert result["message"] == "Legacy spoken line."
    assert result["story_hook_card"]["body"] == "Legacy spoken line."
    assert result["story_hook_card"]["writing_mode"] == "legacy"

@pytest.mark.asyncio
async def test_visual_step_carries_an_api_relative_image_path(orchestrator) -> None:
    session = StubSession()
    await _emit_first(orchestrator, session)
    result = await orchestrator.maybe_emit(session, action="story_hook_done")

    card = result["story_hook_card"]
    assert result["story_hook_step"]["kind"] == "visual"
    assert card["image_path"] == (
        "/curriculum/concepts/concept-1/story-hook/visuals/stomata_surface"
    )
    # The opaque storage key never reaches the client.
    assert "leaf-abc.png" not in json.dumps(result)


@pytest.mark.asyncio
async def test_question_step_pauses_for_the_student(orchestrator) -> None:
    session = StubSession()
    await _emit_first(orchestrator, session)
    await orchestrator.maybe_emit(session, action="story_hook_done")
    result = await orchestrator.maybe_emit(session, action="story_hook_done")

    assert result["story_hook_step"]["awaiting"] is True
    assert session.story_hook_status == "waiting_for_student"
    assert session.story_hook_pending_question == "Why would a plant ever close them?"
    assert runtime_module.is_awaiting_student(session) is True


@pytest.mark.asyncio
async def test_advance_action_cannot_skip_a_pending_question(orchestrator) -> None:
    session = StubSession()
    await _emit_first(orchestrator, session)
    await orchestrator.maybe_emit(session, action="story_hook_done")
    await orchestrator.maybe_emit(session, action="story_hook_done")

    before = session.story_hook_step_index
    result = await orchestrator.maybe_emit(session, action="story_hook_done")

    assert result == {"type": "noop"}
    assert session.story_hook_step_index == before
    assert session.story_hook_status == "waiting_for_student"


@pytest.mark.asyncio
async def test_student_answer_gets_a_fresh_reply_then_the_story_resumes(
    orchestrator, monkeypatch
) -> None:
    session = StubSession()
    await _emit_first(orchestrator, session)
    await orchestrator.maybe_emit(session, action="story_hook_done")
    await orchestrator.maybe_emit(session, action="story_hook_done")

    async def fake_reply(**kwargs):
        assert kwargs["question"] == "Why would a plant ever close them?"
        assert kwargs["student_answer"] == "To save water maybe"
        return "Exactly the right instinct — water is the trade-off."

    monkeypatch.setattr(planner_module, "respond_to_story_hook_answer", fake_reply)
    monkeypatch.setattr(runtime_module, "respond_to_story_hook_answer", fake_reply)

    result = await orchestrator.maybe_emit(
        session, action=None, user_input="To save water maybe"
    )

    assert result["story_hook_step"]["kind"] == "reply"
    assert result["story_hook_step"]["awaiting"] is False
    assert "water is the trade-off" in result["message"]
    assert session.story_hook_status == "playing"
    assert session.story_hook_qa[-1]["answer"] == "To save water maybe"

    # The pointer stayed on the question, so the next advance moves exactly one.
    resumed = await orchestrator.maybe_emit(session, action="story_hook_done")
    assert resumed["story_hook_step"]["kind"] == "finish"
    assert resumed["story_hook_step"]["last"] is True


@pytest.mark.asyncio
async def test_answer_falls_back_to_a_neutral_line_when_llm_is_down(
    orchestrator, monkeypatch
) -> None:
    session = StubSession()
    await _emit_first(orchestrator, session)
    await orchestrator.maybe_emit(session, action="story_hook_done")
    await orchestrator.maybe_emit(session, action="story_hook_done")

    async def fake_reply(**_kwargs):
        return ""

    monkeypatch.setattr(runtime_module, "respond_to_story_hook_answer", fake_reply)
    result = await orchestrator.maybe_emit(
        session, action=None, user_input="No idea honestly"
    )

    assert result["message"].strip()
    assert session.story_hook_status == "playing"


@pytest.mark.asyncio
async def test_last_step_completes_the_stage_and_hands_over(orchestrator) -> None:
    session = StubSession(concept_teaching_sequence_snapshot=["story_hook"])
    await _emit_first(orchestrator, session)
    for _ in range(2):
        await orchestrator.maybe_emit(session, action="story_hook_done")
    # Answer the question so the story can finish.
    session.story_hook_status = "playing"
    session.story_hook_pending_question = None
    finish = await orchestrator.maybe_emit(session, action="story_hook_done")
    assert finish["story_hook_step"]["kind"] == "finish"

    done = await orchestrator.maybe_emit(
        session, action="story_hook_done", handler_ctx=None
    )
    assert done["type"] == "noop"
    assert session.story_hook_status == "done"
    assert session.flow_state == "idle"
    assert session.concept_teaching_stage_index == 1


@pytest.mark.asyncio
async def test_plan_is_generated_once_per_concept(orchestrator, monkeypatch) -> None:
    calls = {"n": 0}

    async def counting_llm(user_content, *, system_content="", **_kwargs):
        calls["n"] += 1
        return PLAN_JSON

    monkeypatch.setattr(planner_module, "llm_call", counting_llm)

    session = StubSession()
    await _emit_first(orchestrator, session)
    await orchestrator.maybe_emit(session, action="story_hook_done")
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_language_switch_does_not_restart_a_story_in_progress(
    orchestrator, monkeypatch
) -> None:
    session = StubSession()
    await _emit_first(orchestrator, session)

    async def hinglish_mode(_session):
        return "hinglish"

    monkeypatch.setattr(cto_module, "resolve_mode_for_session", hinglish_mode)
    result = await orchestrator.maybe_emit(session, action="story_hook_done")

    assert result["story_hook_step"]["index"] == 1
    assert session.story_hook_language == "english"


# ── Acceptance: Stomata, three visuals, Hinglish ────────────────────────────


STOMATA_HOOK = {
    "title": "City of tiny doors",
    "body": "A leaf is a city with millions of doors that open at dawn.",
    "teacher_intent": "Emphasise that the plant controls the doors.",
    "visuals": [
        {
            "id": f"v{i}",
            "asset_key": key,
            "storage_key": f"{key}-abc.png",
            "description": desc,
            "teaching_purpose": purpose,
            "mime_type": "image/png",
            "sort_order": i,
        }
        for i, (key, desc, purpose) in enumerate(
            [
                ("stomata_surface", "Pores on a leaf underside", "Show how many"),
                ("guard_cells", "Two guard cells around a pore", "Show what opens"),
                ("closed_stoma", "A closed pore in dry heat", "Show the trade-off"),
            ]
        )
    ],
}

HINGLISH_PLAN_JSON = json.dumps(
    {
        "steps": [
            {"type": "narration", "text": "Abhi ek patta chupchaap saans le raha hai."},
            {
                "type": "visual",
                "text": "Dekho kitne saare pores hain leaf ke neeche.",
                "asset_key": "stomata_surface",
            },
            {
                "type": "visual",
                "text": "Ye do guard cells hi pore ko open aur close karte hain.",
                "asset_key": "guard_cells",
            },
            {"type": "question", "text": "Plant inhe band kyun karega?"},
            {
                "type": "visual",
                "text": "Garmi mein pore band ho jata hai, warna paani udd jaata.",
                "asset_key": "closed_stoma",
            },
            {"type": "finish", "text": "Ab dekhte hain plant decide kaise karta hai."},
        ]
    }
)


@pytest.mark.asyncio
async def test_hinglish_stomata_story_uses_every_visual_then_hands_over_to_vtse(
    orchestrator, monkeypatch
) -> None:
    async def hinglish_llm(user_content, *, system_content="", **_kwargs):
        assert "Roman script only" in system_content
        return HINGLISH_PLAN_JSON

    async def hinglish_mode(_session):
        return "hinglish"

    async def fake_reply(**_kwargs):
        return "Bilkul sahi socha — paani bachana hi asli wajah hai."

    monkeypatch.setattr(planner_module, "llm_call", hinglish_llm)
    monkeypatch.setattr(cto_module, "resolve_mode_for_session", hinglish_mode)
    monkeypatch.setattr(runtime_module, "respond_to_story_hook_answer", fake_reply)

    session = StubSession(concept_teaching_story_hook_snapshot=dict(STOMATA_HOOK))
    shown: list[str] = []

    result = await _emit_first(orchestrator, session)
    assert session.story_hook_language == "hinglish"

    for _ in range(10):
        card = result.get("story_hook_card") or {}
        if card.get("image_path"):
            shown.append(card["image_path"].rsplit("/", 1)[-1])
        step = result["story_hook_step"]
        if step["awaiting"]:
            result = await orchestrator.maybe_emit(
                session, action=None, user_input="Shayad paani bachane ke liye"
            )
            continue
        if step["last"]:
            break
        result = await orchestrator.maybe_emit(session, action="story_hook_done")

    # Every authored visual appeared exactly once, in authored order.
    assert shown == ["stomata_surface", "guard_cells", "closed_stoma"]
    assert session.story_hook_qa[-1]["answer"] == "Shayad paani bachane ke liye"

    await orchestrator.maybe_emit(session, action="story_hook_done")
    assert session.story_hook_status == "done"
    # VTSE is next in the sequence and is reached without being reordered.
    assert session.concept_teaching_stage_index == 1
    assert session.concept_teaching_sequence_snapshot[1] == "vtse"


@pytest.mark.asyncio
async def test_new_concept_clears_the_previous_plan(orchestrator) -> None:
    session = StubSession()
    await _emit_first(orchestrator, session)
    assert session.story_hook_plan is not None

    session.current_concept_index = 1
    session.flow_state = "idle"
    await orchestrator.ensure_sequence_snapshot(session)

    assert session.story_hook_plan is None
    assert session.story_hook_status == "idle"
    assert session.story_hook_step_index == 0
