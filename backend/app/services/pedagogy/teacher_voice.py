"""Shared speaking contract and student-facing lesson continuity.

Structure only. The model writes the words. Canonical stage ids never leave
this module.
"""

from __future__ import annotations

import re
from typing import Any, Optional

_FORBIDDEN_TOKENS = (
    "story_hook",
    "visual_teaching",
    "vtse",
    "zone 0",
    "zone 1",
    "zone0",
    "zone1",
)

TEACHER_WARMTH_RULES = """
SPEAKING MANNER
- Speak as one teacher who is already with the student.
- Vary how you move on. Do not begin consecutive beats with the same attention phrase.
- Warmth is professional and brief. Do not use praise filler, and do not grade the student.
- If no student reply is provided, do not pretend they answered.
- Never say internal lesson labels or planner names. The student should hear only the idea.
- Do not announce that a check of understanding is coming.
- Orientation, attention, acknowledgement, and bridges are spoken only. They are never board writes, notes, cards, or annotations.
""".strip()

TEACHER_SPEAKING_CONTRACT = (
    TEACHER_WARMTH_RULES
    + """

LESSON MOVEMENT
- Open from what was just established, teach the current point, then move.
- When a visual is on screen, name the highlighted part by its label, say why that spot matters, teach it, then move to the next spot without restarting the lesson.
- If position_hint is present, you may use that coarse placement. If it is absent, refer only to the highlighted part. Never invent a placement the hint does not give.
- A next focus is only a direction. Do not teach that next part's facts in this turn.
- The first spoken part opens from the previous focus or the student's own words when those are provided.
- The last spoken part moves toward the next focus when one is provided, as speech only.
"""
).strip()


def _clip(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _safe_phrase(text: str) -> str:
    cleaned = text
    for token in _FORBIDDEN_TOKENS:
        cleaned = re.sub(re.escape(token), "", cleaned, flags=re.IGNORECASE)
    return " ".join(cleaned.split())


def phrase_has_internal_name(text: str) -> bool:
    low = str(text or "").lower()
    return any(token in low for token in _FORBIDDEN_TOKENS)


def coarse_position_hint(
    *,
    shape: str = "",
    geometry: Any = None,
    focus_point: Any = None,
) -> Optional[str]:
    """One coarse word from normalized geometry. Raw coordinates stay out of prompts."""
    x, y = _region_center(shape=shape, geometry=geometry, focus_point=focus_point)
    if x is None or y is None:
        return None
    if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
        return None

    def _bucket(value: float, low_name: str, high_name: str) -> str:
        if value < 0.34:
            return low_name
        if value > 0.66:
            return high_name
        return "center"

    horizontal = _bucket(x, "left", "right")
    vertical = _bucket(y, "upper", "lower")
    if abs(x - 0.5) >= abs(y - 0.5):
        if horizontal != "center":
            return horizontal
        return vertical if vertical != "center" else "center"
    if vertical != "center":
        return vertical
    return horizontal if horizontal != "center" else "center"


def _num(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _region_center(
    *,
    shape: str,
    geometry: Any,
    focus_point: Any,
) -> tuple[Optional[float], Optional[float]]:
    if isinstance(focus_point, dict):
        fx, fy = _num(focus_point.get("x")), _num(focus_point.get("y"))
        if fx is not None and fy is not None:
            return fx, fy
    geo = geometry if isinstance(geometry, dict) else {}
    kind = str(shape or "")
    if kind == "ellipse" or ("cx" in geo and "cy" in geo):
        return _num(geo.get("cx")), _num(geo.get("cy"))
    points = geo.get("points")
    if kind == "polygon" or isinstance(points, list):
        xs: list[float] = []
        ys: list[float] = []
        for point in points or []:
            if not isinstance(point, dict):
                continue
            px, py = _num(point.get("x")), _num(point.get("y"))
            if px is None or py is None:
                continue
            xs.append(px)
            ys.append(py)
        if xs and ys:
            return sum(xs) / len(xs), sum(ys) / len(ys)
    x, y = _num(geo.get("x")), _num(geo.get("y"))
    if x is None or y is None:
        return None, None
    width, height = _num(geo.get("w")), _num(geo.get("h"))
    if width is not None and height is not None:
        return x + width / 2.0, y + height / 2.0
    return x, y


def student_thread_from_session(session: Any) -> str:
    if session is None:
        return ""
    qa = list(getattr(session, "story_hook_qa", None) or [])
    if qa and isinstance(qa[-1], dict):
        answer = str(qa[-1].get("answer") or "").strip()
        if answer:
            return _clip(answer, 200)
    return _clip(getattr(session, "zone0_student_thread", "") or "", 200)


def _field(raw: Any, name: str) -> Any:
    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw.get(name)
    return getattr(raw, name, None)


def student_stage_focus(
    stage: Optional[str],
    *,
    concept: Any = None,
    session: Any = None,
    concept_name: str = "",
) -> str:
    """Student-facing direction for one stage. Never a canonical stage id."""
    name = _clip(concept_name, 80) or "this idea"
    key = str(stage or "").strip().lower()
    if key == "story_hook":
        hook = None
        if session is not None:
            snap = getattr(session, "concept_teaching_story_hook_snapshot", None)
            if isinstance(snap, dict) and snap:
                hook = snap
        if hook is None and concept is not None:
            hook = _field(concept, "story_hook")
        title = _clip(_field(hook, "title"), 80)
        phrase = f"a short story called {title}" if title else f"a short story about {name}"
        return _safe_phrase(_clip(phrase, 160))
    if key == "visual_teaching":
        visual = None
        if session is not None:
            snap = getattr(session, "concept_teaching_visual_teaching_snapshot", None)
            if isinstance(snap, dict) and snap:
                visual = snap
        if visual is None and concept is not None:
            visual = _field(concept, "visual_teaching")
        images = list(_field(visual, "images") or [])
        purpose = ""
        if images:
            purpose = _clip(_field(images[0], "teaching_purpose"), 120)
        phrase = purpose or f"a diagram of {name}"
        return _safe_phrase(_clip(phrase, 160))
    if key == "vtse":
        template = _field(concept, "vtse_template") if concept is not None else None
        strategy = str(_field(template, "strategy_id") or "").strip().lower()
        phrases = {
            "comparison_contrast": f"a side-by-side comparison of {name}",
            "linear_process": f"the steps of {name}",
            "cycle_process": f"the repeating cycle of {name}",
            "hierarchy_concept_intro": f"how {name} fits together",
            "clustered_trait_list": f"the main traits of {name}",
        }
        return _safe_phrase(_clip(phrases.get(strategy, f"the main ideas of {name}"), 160))
    return ""


def _lesson_sequence(concept: Any, session: Any) -> list[str]:
    if session is not None:
        snap = getattr(session, "concept_teaching_sequence_snapshot", None)
        if isinstance(snap, list) and snap:
            return [str(item).strip().lower() for item in snap if str(item).strip()]
    if concept is None:
        return []
    from app.services.curriculum.concept_teaching_sequence import (
        select_frozen_teaching_sequence,
    )

    sequence, _source = select_frozen_teaching_sequence(concept)
    return [str(item).strip().lower() for item in sequence if str(item).strip()]


def build_continuity_card(
    *,
    concept: Any = None,
    session: Any = None,
    current_stage: Optional[str] = None,
    concept_name: str = "",
    include_student_thread: bool = True,
) -> dict[str, str]:
    """Small direction card. Omits empty threads so the model does not invent a reply."""
    sequence = _lesson_sequence(concept, session)
    stage = str(current_stage or "").strip().lower()
    index = sequence.index(stage) if stage and stage in sequence else -1
    if index < 0:
        previous = None
        nxt = sequence[0] if sequence else None
        position = "opening"
    else:
        previous = sequence[index - 1] if index > 0 else None
        nxt = sequence[index + 1] if index + 1 < len(sequence) else None
        if previous is None:
            position = "opening"
        elif nxt is None:
            position = "closing"
        else:
            position = "middle"
    card = {
        "previous_focus": student_stage_focus(
            previous, concept=concept, session=session, concept_name=concept_name
        ),
        "next_focus": student_stage_focus(
            nxt, concept=concept, session=session, concept_name=concept_name
        ),
        "student_thread": (
            student_thread_from_session(session) if include_student_thread else ""
        ),
        "position_in_lesson": position,
    }
    return {key: _safe_phrase(value) if key != "position_in_lesson" else value for key, value in card.items()}


def continuity_instructions(card: Optional[dict[str, Any]]) -> str:
    if not card:
        return ""
    previous = str(card.get("previous_focus") or "").strip()
    nxt = str(card.get("next_focus") or "").strip()
    thread = str(card.get("student_thread") or "").strip()
    position = str(card.get("position_in_lesson") or "middle").strip() or "middle"
    lines = [
        "LESSON CONTINUITY (direction only — do not teach the next part's facts):",
        f"Place in the lesson: {position}",
    ]
    if previous:
        lines.append(f"What the student just came from: {previous}")
    else:
        lines.append("Nothing has been taught yet in this lesson.")
    if nxt:
        lines.append(f"Where the last spoken line should lead, without teaching it yet: {nxt}")
    else:
        lines.append(
            "There is no next teaching focus. End on this idea. Do not preview a later check."
        )
    if thread:
        lines.append(f"The student said: {thread}")
        lines.append("The first spoken part may use that, without grading it.")
    else:
        lines.append("The student has not just answered. Do not acknowledge an answer.")
    lines.append(
        "The first spoken part opens from what came before when that context is present."
    )
    lines.append(
        "The last spoken part moves toward the next focus when one is present, as speech only."
    )
    return "\n".join(lines)


def zone0_close_paragraph(next_focus: str) -> str:
    focus = _safe_phrase(_clip(next_focus, 160))
    if focus:
        return (
            "Paragraph 2: In everyday language, point toward this next focus without "
            f"teaching any facts from it: \"{focus}\". "
            "Mention they can tap the button below when they feel ready. "
            "Do not name internal lesson parts."
        )
    return (
        "Paragraph 2: Ask if they're ready to start the topic together; mention they "
        "can tap the button below when they feel ready."
    )
