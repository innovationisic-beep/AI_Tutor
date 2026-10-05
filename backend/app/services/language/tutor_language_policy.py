"""
Stage-aware tutor language policy.

Language is a presentation/generation policy over ONE tutor runtime — never a
second architecture. Only human-facing text changes; machine fields, JSON keys,
IDs and enums always stay in English.

Hinglish is enabled per stage (see HINGLISH_STAGES). Stages outside that
allowlist return None so existing English behavior is untouched.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

TutorLanguageMode = Literal["english", "hinglish"]

ENGLISH: TutorLanguageMode = "english"
HINGLISH: TutorLanguageMode = "hinglish"

# Stage keys used when asking for a language instruction.
STAGE_ZONE0_CURIOSITY = "zone0_curiosity"
STAGE_ZONE0_PREREQ = "zone0_prereq"
STAGE_STORY_HOOK = "story_hook"
STAGE_CLUSTER_CURIOSITY = "cluster_curiosity"

# v1 allowlist: conversational stages only. VTSE, Concept Check, Cluster Quiz,
# Notes, teachback and Clarity Gate intentionally remain English.
HINGLISH_STAGES: frozenset[str] = frozenset(
    {
        STAGE_ZONE0_CURIOSITY,
        STAGE_ZONE0_PREREQ,
        STAGE_STORY_HOOK,
        STAGE_CLUSTER_CURIOSITY,
    }
)

# Accepted stored values that mean Hinglish.
_HINGLISH_VALUES: frozenset[str] = frozenset({"hinglish", "hi-en", "hien", "en-hi"})

_HINGLISH_STYLE_BLOCK = (
    "LANGUAGE: Write all student-facing text in easy conversational Hinglish.\n"
    "STRICT LANGUAGE RULES:\n"
    "- Roman script only. NEVER use Devanagari.\n"
    "- Use simple, everyday spoken Hindi mixed naturally with English.\n"
    "- Keep familiar English academic/technical terms in English "
    "(for example: stomata, guard cells, gas exchange, carbon dioxide, oxygen).\n"
    "- No difficult or shuddh Hindi. No literal word-by-word translation.\n"
    "- No slang-heavy casual tone. Sound like a warm, clear teacher.\n"
    "- Stay scientifically precise.\n"
    "- EASY LANGUAGE DOES NOT MEAN SIMPLER CONTENT: keep the same facts, "
    "examples, richness and teaching depth as the English source material.\n"
    'STYLE EXAMPLE: "Stomata leaves par present chhote pores hote hain. '
    'Ye gas exchange aur water loss ko control karne mein help karte hain."'
)


def resolve_mode(preferred_language: Any) -> TutorLanguageMode:
    """Map a stored profile ``preferred_language`` onto a tutor language mode."""
    value = str(preferred_language or "").strip().lower()
    if value in _HINGLISH_VALUES:
        return HINGLISH
    return ENGLISH


def resolve_mode_from_profile(profile: Any) -> TutorLanguageMode:
    """Resolve mode from a StudentProfile document, dict, or None."""
    if profile is None:
        return ENGLISH
    if isinstance(profile, dict):
        return resolve_mode(profile.get("preferred_language"))
    return resolve_mode(getattr(profile, "preferred_language", None))


def stage_supports_hinglish(stage: str) -> bool:
    """True when this stage is allowed to speak Hinglish in v1."""
    return str(stage or "").strip().lower() in HINGLISH_STAGES


def language_instruction_for_stage(
    stage: str,
    mode: TutorLanguageMode,
) -> Optional[str]:
    """
    Prompt block enforcing the student-facing language for this stage.

    Returns None when nothing should be injected (English mode, or a stage that
    stays English in v1) so existing prompts are byte-identical.
    """
    if mode != HINGLISH:
        return None
    if not stage_supports_hinglish(stage):
        return None
    return _HINGLISH_STYLE_BLOCK


def apply_language_to_system_prompt(
    system_prompt: str,
    *,
    stage: str,
    mode: TutorLanguageMode,
) -> str:
    """Append the stage language block to a system prompt when applicable."""
    block = language_instruction_for_stage(stage, mode)
    if not block:
        return system_prompt
    return f"{system_prompt}\n\n{block}"


# Deterministic student-facing lines inside Hinglish stages. Authored (not
# translated at runtime) so tone stays controlled and no LLM call is needed.
_HINGLISH_STATIC_TEXT: dict[str, str] = {
    "zone0_prereq_intro": (
        "Shuru karne se pehle ek chhota sa question — pehle jo padha hai, "
        "sirf usko warm up karne ke liye."
    ),
    "story_hook_answer_ack": (
        "Achha socha — is baat ko yaad rakho. Chalo aage badhte hain."
    ),
    "story_hook_visual_caption": "Isko dhyaan se dekho.",
}


def static_text(key: str, mode: TutorLanguageMode, *, english: str) -> str:
    """Authored translation for a fixed tutor line; falls back to ``english``."""
    if mode != HINGLISH:
        return english
    return _HINGLISH_STATIC_TEXT.get(key, english)


async def resolve_mode_for_session(session: Any) -> TutorLanguageMode:
    """
    Load the learner profile for a session and resolve the tutor language mode.

    Reads the profile per call so a dashboard change applies to the next
    response without a session restart. Never raises — defaults to English.
    """
    try:
        from app.models.identification.student_profiles import StudentProfile

        profile = await StudentProfile.find_one(
            {
                "organization_id": getattr(session, "organization_id", None),
                "user_id": getattr(session, "student_id", None),
            }
        )
    except Exception:  # noqa: BLE001
        return ENGLISH
    return resolve_mode_from_profile(profile)
