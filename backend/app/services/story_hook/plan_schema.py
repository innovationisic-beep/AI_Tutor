"""
Story Hook plan schema and backend validation.

The planner LLM is bounded by this schema: the backend decides what a valid
Story Hook may contain, never the model. Anything outside these rules is
rejected so the runtime can retry once and then fall back to seed narration.
"""

from __future__ import annotations

import json
import re
from typing import Any, Iterable, List, Literal, Optional, Sequence

from pydantic import BaseModel, Field

from app.services.speech_note_dual import (
    MAX_WRITE_CHARS,
    normalize_board_writes,
)

StoryHookStepType = Literal["narration", "visual", "question", "finish"]
StoryHookWritingMode = Literal["legacy", "notes"]

MAX_QUESTIONS = 2
MAX_STEPS = 14
MAX_STEP_TEXT_CHARS = 1200
MAX_QUESTION_CHARS = 400
MAX_NOTE_CHARS = 280

PLAN_SOURCE_PLANNER = "planner"
PLAN_SOURCE_FALLBACK = "fallback"

WRITING_MODE_LEGACY: StoryHookWritingMode = "legacy"
WRITING_MODE_NOTES: StoryHookWritingMode = "notes"

# Roman script is a hard Hinglish requirement, so any Devanagari fails the plan.
_DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")
_JSON_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


class StoryHookPlanError(ValueError):
    """A planner payload that violates the bounded Story Hook contract."""


class StoryHookBoardWrite(BaseModel):
    """Normalized runtime board write (validated sentence index)."""

    sentence_index: int = Field(ge=0)
    text: str = Field(default="", max_length=MAX_WRITE_CHARS)


class StoryHookStep(BaseModel):
    """One runtime beat. ``asset_key`` is set only on ``visual`` steps."""

    type: StoryHookStepType
    text: str = Field(
        default="",
        max_length=MAX_STEP_TEXT_CHARS,
        description="Spoken teacher narration (TTS / message).",
    )
    asset_key: str = Field(default="", max_length=64)
    note: str = Field(
        default="",
        max_length=MAX_NOTE_CHARS,
        description="Optional concise written takeaway on the Story Hook card.",
    )
    writes: List[StoryHookBoardWrite] = Field(
        default_factory=list,
        description="Optional sentence-anchored board writes (runtime indices).",
    )


class StoryHookPlan(BaseModel):
    steps: List[StoryHookStep]
    language: str = Field(default="english")
    source: str = Field(default=PLAN_SOURCE_PLANNER)
    writing_mode: StoryHookWritingMode = Field(
        default=WRITING_MODE_LEGACY,
        description=(
            "legacy: card shows spoken text (old plans / fallback). "
            "notes: card shows optional note; empty note means speak-only."
        ),
    )

    @property
    def question_count(self) -> int:
        return sum(1 for s in self.steps if s.type == "question")

    @property
    def uses_notes(self) -> bool:
        return self.writing_mode == WRITING_MODE_NOTES


def _normalize_step_writes(
    *,
    spoken: str,
    raw_step: dict,
    legacy_note: str,
    step_type: str,
) -> tuple[str, List[StoryHookBoardWrite]]:
    """Map LLM source_sentence writes (or legacy note) to validated indices."""
    if step_type == "question":
        return "", []
    normalized = normalize_board_writes(
        spoken_text=spoken,
        raw_writes=raw_step.get("writes"),
        legacy_note=legacy_note,
    )
    writes = [
        StoryHookBoardWrite(
            sentence_index=int(w["sentence_index"]),
            text=str(w.get("text") or "")[:MAX_WRITE_CHARS],
        )
        for w in normalized
        if str(w.get("text") or "").strip()
    ]
    note = legacy_note
    if writes and not note:
        note = "\n".join(w.text for w in writes)[:MAX_NOTE_CHARS]
    return note, writes


def _clean_text(raw: Any, *, limit: int = MAX_STEP_TEXT_CHARS) -> str:
    text = str(raw or "").replace("\r", "").strip()
    # Planners like to wrap narration in quotes or markdown emphasis.
    text = text.strip('"').strip()
    return text[:limit]


def strip_json_fence(raw: str) -> str:
    return _JSON_FENCE_RE.sub("", str(raw or "")).strip()


def parse_plan_json(raw: str) -> Any:
    """Parse a planner response, tolerating code fences and surrounding prose."""
    text = strip_json_fence(raw)
    if not text:
        raise StoryHookPlanError("empty planner response")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        raise StoryHookPlanError("planner response is not JSON")
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise StoryHookPlanError(f"planner response is not JSON: {exc}") from exc


def contains_devanagari(values: Iterable[str]) -> bool:
    return any(_DEVANAGARI_RE.search(v or "") for v in values)


def validate_plan_payload(
    raw: Any,
    *,
    allowed_asset_keys: Sequence[str],
    language: str,
    max_questions: int = MAX_QUESTIONS,
) -> StoryHookPlan:
    """
    Validate a raw planner payload into a ``StoryHookPlan``.

    Enforces the locked v1 rules: known step types only, every attached visual
    used exactly once, no unknown or repeated ``asset_key``, at most
    ``max_questions`` questions, and Roman script for Hinglish.

    Raises ``StoryHookPlanError`` with a reason suitable for a retry prompt.
    """
    if not isinstance(raw, dict):
        raise StoryHookPlanError("plan must be a JSON object")

    raw_steps = raw.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise StoryHookPlanError("plan.steps must be a non-empty array")

    allowed = [str(k) for k in allowed_asset_keys]
    allowed_set = set(allowed)

    steps: List[StoryHookStep] = []
    used_assets: List[str] = []
    questions = 0
    finish_seen = False

    for index, raw_step in enumerate(raw_steps):
        if not isinstance(raw_step, dict):
            raise StoryHookPlanError(f"step {index} must be an object")
        step_type = str(raw_step.get("type") or "").strip().lower()

        # Every step boundary already waits for the student's client, so an
        # explicit pause carries no runtime meaning.
        if step_type == "pause":
            continue

        if step_type not in ("narration", "visual", "question", "finish"):
            raise StoryHookPlanError(
                f"step {index} has unsupported type '{step_type}'; "
                "allowed: narration, visual, question, finish"
            )
        if finish_seen:
            raise StoryHookPlanError("no step may follow the finish step")

        if step_type == "visual":
            asset_key = str(raw_step.get("asset_key") or "").strip().lower()
            if asset_key not in allowed_set:
                raise StoryHookPlanError(
                    f"step {index} references unknown asset_key '{asset_key}'; "
                    f"available: {', '.join(allowed) or 'none'}"
                )
            if asset_key in used_assets:
                raise StoryHookPlanError(
                    f"asset_key '{asset_key}' is used more than once"
                )
            caption = _clean_text(raw_step.get("text"))
            if not caption:
                # The tutor must say something while an image appears, otherwise
                # the turn has no narration to reveal or speak.
                raise StoryHookPlanError(
                    f"step {index} (visual) needs a spoken line in 'text'"
                )
            note_raw = _clean_text(raw_step.get("note"), limit=MAX_NOTE_CHARS)
            note, writes = _normalize_step_writes(
                spoken=caption,
                raw_step=raw_step,
                legacy_note=note_raw,
                step_type="visual",
            )
            used_assets.append(asset_key)
            steps.append(
                StoryHookStep(
                    type="visual",
                    text=caption,
                    asset_key=asset_key,
                    note=note,
                    writes=writes,
                )
            )
            continue

        limit = MAX_QUESTION_CHARS if step_type == "question" else MAX_STEP_TEXT_CHARS
        text = _clean_text(raw_step.get("text"), limit=limit)
        if not text:
            raise StoryHookPlanError(f"step {index} ({step_type}) has empty text")

        # Questions always show spoken text; ignore note/writes to avoid competing strings.
        note_raw = (
            ""
            if step_type == "question"
            else _clean_text(raw_step.get("note"), limit=MAX_NOTE_CHARS)
        )
        note, writes = _normalize_step_writes(
            spoken=text,
            raw_step=raw_step if step_type != "question" else {},
            legacy_note=note_raw,
            step_type=step_type,
        )

        if step_type == "question":
            questions += 1
            if questions > max_questions:
                raise StoryHookPlanError(
                    f"plan asks {questions} questions; at most {max_questions} allowed"
                )
        if step_type == "finish":
            finish_seen = True

        steps.append(
            StoryHookStep(
                type=step_type,  # type: ignore[arg-type]
                text=text,
                note=note,
                writes=writes,
            )
        )

    if not steps:
        raise StoryHookPlanError("plan has no usable steps")
    if len(steps) > MAX_STEPS:
        raise StoryHookPlanError(f"plan has {len(steps)} steps; at most {MAX_STEPS} allowed")
    if not any(s.type in ("narration", "finish") for s in steps):
        raise StoryHookPlanError("plan must contain at least one narration step")

    missing = [key for key in allowed if key not in used_assets]
    if missing:
        raise StoryHookPlanError(
            "every attached visual must be used exactly once; missing: "
            f"{', '.join(missing)}"
        )

    if str(language).strip().lower() == "hinglish" and contains_devanagari(
        value
        for s in steps
        for value in (
            s.text,
            s.note,
            *(w.text for w in s.writes),
        )
    ):
        raise StoryHookPlanError(
            "Hinglish must use Roman script only; Devanagari characters found"
        )

    return StoryHookPlan(
        steps=steps,
        language=str(language).strip().lower() or "english",
        source=PLAN_SOURCE_PLANNER,
        writing_mode=WRITING_MODE_NOTES,
    )


def build_fallback_plan(
    *,
    seed: str,
    title: str = "",
    visuals: Sequence[Any] = (),
    language: str = "english",
    visual_caption_fallback: str = "Take a look at this.",
) -> StoryHookPlan:
    """
    Seed-only plan used when the planner fails validation twice.

    Narrates the authored seed verbatim and shows each attached visual once, so
    the stage still teaches something authored rather than getting stuck.
    """
    steps: List[StoryHookStep] = []
    body = _clean_text(seed)
    heading = _clean_text(title, limit=200)
    if body:
        steps.append(StoryHookStep(type="narration", text=body))
    elif heading:
        steps.append(StoryHookStep(type="narration", text=heading))

    for visual in visuals:
        get = (
            (lambda name: visual.get(name))
            if isinstance(visual, dict)
            else (lambda name: getattr(visual, name, None))
        )
        asset_key = str(get("asset_key") or "").strip().lower()
        if not asset_key:
            continue
        caption = (
            _clean_text(get("description"))
            or _clean_text(get("teaching_purpose"))
            or visual_caption_fallback
        )
        steps.append(StoryHookStep(type="visual", text=caption, asset_key=asset_key))

    if not steps:
        steps.append(StoryHookStep(type="narration", text=heading or "Story Hook"))

    return StoryHookPlan(
        steps=steps,
        language=str(language).strip().lower() or "english",
        source=PLAN_SOURCE_FALLBACK,
        writing_mode=WRITING_MODE_LEGACY,
    )


def resolve_card_written(
    step: StoryHookStep,
    *,
    writing_mode: StoryHookWritingMode = WRITING_MODE_LEGACY,
    kind: Optional[str] = None,
) -> str:
    """
    Visible card writing for one step.

    - question / reply: always the spoken text (must stay on-screen).
    - notes mode: prefer joined writes, else optional ``note``
      (empty = speak-only, write nothing new).
    - legacy mode: spoken text (old plans / fallback).
    """
    step_kind = kind or step.type
    if step_kind in ("question", "reply"):
        return (step.text or "").strip()
    if writing_mode == WRITING_MODE_NOTES:
        if step.writes:
            joined = "\n".join(
                (w.text or "").strip() for w in step.writes if (w.text or "").strip()
            )
            if joined:
                return joined[:MAX_NOTE_CHARS]
        return (step.note or "").strip()
    return (step.text or "").strip()


def plan_from_stored(raw: Any) -> Optional[StoryHookPlan]:
    """Rehydrate a persisted plan; returns ``None`` when unusable."""
    if not isinstance(raw, dict):
        return None
    try:
        plan = StoryHookPlan.model_validate(raw)
    except Exception:  # noqa: BLE001
        return None
    return plan if plan.steps else None