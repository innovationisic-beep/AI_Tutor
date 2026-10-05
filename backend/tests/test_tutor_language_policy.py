"""Stage-aware tutor language policy — English stays byte-identical."""

from __future__ import annotations

from app.services.language.tutor_language_policy import (
    ENGLISH,
    HINGLISH,
    STAGE_STORY_HOOK,
    STAGE_ZONE0_CURIOSITY,
    STAGE_ZONE0_PREREQ,
    apply_language_to_system_prompt,
    language_instruction_for_stage,
    resolve_mode,
    resolve_mode_from_profile,
    stage_supports_hinglish,
    static_text,
)


class _Profile:
    def __init__(self, preferred_language: str | None) -> None:
        self.preferred_language = preferred_language


def test_resolve_mode_defaults_to_english() -> None:
    for value in ("en", "EN", "", None, "fr", "hi", "unknown"):
        assert resolve_mode(value) == ENGLISH


def test_resolve_mode_accepts_hinglish_aliases() -> None:
    for value in ("hinglish", "Hinglish", " HINGLISH ", "hi-en", "en-hi"):
        assert resolve_mode(value) == HINGLISH


def test_resolve_mode_from_profile_handles_doc_dict_and_none() -> None:
    assert resolve_mode_from_profile(None) == ENGLISH
    assert resolve_mode_from_profile({"preferred_language": "hinglish"}) == HINGLISH
    assert resolve_mode_from_profile(_Profile("hinglish")) == HINGLISH
    assert resolve_mode_from_profile(_Profile("en")) == ENGLISH


def test_hinglish_allowlist_covers_only_conversational_stages() -> None:
    for stage in (STAGE_ZONE0_CURIOSITY, STAGE_ZONE0_PREREQ, STAGE_STORY_HOOK):
        assert stage_supports_hinglish(stage)
    for stage in ("vtse", "concept_check", "cluster_quiz", "notes", "teachback"):
        assert not stage_supports_hinglish(stage)


def test_english_mode_injects_nothing() -> None:
    base = "You are an expert tutor."
    for stage in (STAGE_STORY_HOOK, STAGE_ZONE0_CURIOSITY, "vtse"):
        assert language_instruction_for_stage(stage, ENGLISH) is None
        assert apply_language_to_system_prompt(base, stage=stage, mode=ENGLISH) == base


def test_hinglish_mode_leaves_english_only_stages_untouched() -> None:
    base = "You are an expert tutor."
    for stage in ("vtse", "concept_check", "cluster_quiz"):
        assert language_instruction_for_stage(stage, HINGLISH) is None
        assert apply_language_to_system_prompt(base, stage=stage, mode=HINGLISH) == base


def test_hinglish_block_states_roman_script_and_depth_rules() -> None:
    block = language_instruction_for_stage(STAGE_STORY_HOOK, HINGLISH)
    assert block is not None
    assert "Roman script only" in block
    assert "NEVER use Devanagari" in block
    assert "EASY LANGUAGE DOES NOT MEAN SIMPLER CONTENT" in block
    # Roman script only — the policy itself must not ship Devanagari.
    assert all(not ("\u0900" <= ch <= "\u097f") for ch in block)


def test_apply_language_appends_block_for_allowed_stage() -> None:
    base = "You are a warm companion."
    out = apply_language_to_system_prompt(base, stage=STAGE_STORY_HOOK, mode=HINGLISH)
    assert out.startswith(base)
    assert len(out) > len(base)


def test_static_text_falls_back_to_english_for_unknown_key() -> None:
    assert static_text("nope", HINGLISH, english="Fallback") == "Fallback"
    assert static_text("zone0_prereq_intro", ENGLISH, english="Eng") == "Eng"
    hinglish_intro = static_text("zone0_prereq_intro", HINGLISH, english="Eng")
    assert hinglish_intro != "Eng"
    assert all(not ("\u0900" <= ch <= "\u097f") for ch in hinglish_intro)
