"""Process-step identity vs explanation splitting (storyboard pedagogy)."""

from __future__ import annotations

import re

from app.cir.limits import CIR_V1_MAX_NODES
from app.vtse.authoring.comparison_rows import is_placeholder_text
from app.vtse.authoring.content_filters import sanitize_process_production_text, strip_scaffold_prefix
from app.vtse.authoring.semantic_extract import _clip

PROCESS_MAX_STEPS = CIR_V1_MAX_NODES

_GENERIC_STAGE_RE = re.compile(r"^stage\s*\d+\s*$", re.I)
_STEP_NUM_ONLY_RE = re.compile(r"^step\s*\d+\s*$", re.I)
_STEP_PREFIX_RE = re.compile(r"^step\s*(\d+)\s*[—\-:,]\s*(.+)$", re.I)
_IN_THE_RE = re.compile(
    r"\b(?:in|at|through|into|from)\s+(?:the\s+)?([a-z][a-z\s\-]{2,36}?)(?:\s+where|\s+which|\s+when|,|\.|$)",
    re.IGNORECASE,
)
_TITLE_CASE_RE = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})\b")


def process_step_display_label(index: int) -> str:
    return f"Step {index + 1}"


def is_generic_stage_label(label: str) -> bool:
    return bool(_GENERIC_STAGE_RE.match((label or "").strip()))


def is_prose_identity(identity: str) -> bool:
    """True when text reads like a sentence, not a short stage title."""
    text = (identity or "").strip()
    if not text:
        return True
    words = text.split()
    if len(words) > 4:
        return True
    low = f" {text.lower()} "
    prose_markers = (
        " begins ",
        " starts ",
        " moves ",
        " involves ",
        " is the ",
        " are the ",
        " where ",
        " which ",
        " that ",
        " after ",
        " before ",
        " during ",
    )
    return any(marker in low for marker in prose_markers)


def _identity_from_long_text(text: str, index: int) -> str:
    """Derive a concise stage name from prose when no explicit title exists."""
    m = _IN_THE_RE.search(text)
    if m:
        phrase = m.group(1).strip()
        words = phrase.split()
        if len(words) <= 4:
            return _clip(" ".join(w.capitalize() for w in words), 48)

    for m in _TITLE_CASE_RE.finditer(text):
        candidate = m.group(1).strip()
        low = candidate.lower()
        if low in {"digestion", "process", "food", "body", "nutrients", "energy"}:
            continue
        if len(candidate.split()) <= 3:
            return _clip(candidate, 48)

    words = text.split()
    if len(words) >= 2:
        return _clip(" ".join(words[:3]).rstrip(".,;:"), 48)
    return _clip(f"Stage {index + 1}", 48)


def split_process_step_content(
    raw: str,
    *,
    index: int,
) -> tuple[str, str, str]:
    """
    Split raw step text into storyboard parts.

    Returns:
        (step_display_label, identity, explanation)
    """
    step_display = process_step_display_label(index)
    detail = sanitize_process_production_text(raw, fallback="", max_len=600)
    if not detail:
        identity = _clip(f"Stage {index + 1}", 48)
        return step_display, identity, identity

    prefix = _STEP_PREFIX_RE.match(detail)
    if prefix:
        rest = strip_scaffold_prefix(prefix.group(2).strip())
        if ":" in rest:
            title, body = rest.split(":", 1)
            identity = _clip(title.strip(), 48)
            explanation = _clip(body.strip() or detail, 600)
            if is_prose_identity(identity):
                identity = _identity_from_long_text(detail, index)
            return step_display, identity, explanation
        identity = _identity_from_fragment(rest, index)
        explanation = rest if len(rest) > len(identity) + 12 else detail
        if is_prose_identity(identity):
            identity = _identity_from_long_text(detail, index)
        return step_display, identity, _clip(explanation, 600)

    for sep in (" — ", " - ", " – ", ": "):
        if sep in detail:
            left, right = detail.split(sep, 1)
            left = left.strip()
            right = right.strip()
            if _STEP_NUM_ONLY_RE.match(left) or re.match(r"^step\s*\d+", left, re.I):
                identity = _identity_from_fragment(right or detail, index)
                expl = _clip(right or detail, 600)
                return step_display, identity, expl
            if len(left.split()) <= 5 and not is_placeholder_text(left):
                identity = _clip(left, 48)
                expl = _clip(right or detail, 600)
                return step_display, identity, expl

    identity = _identity_from_fragment(detail, index)
    if _STEP_NUM_ONLY_RE.match(identity) or re.match(r"^step\s*\d+\s*$", identity, re.I):
        identity = _identity_from_long_text(detail, index)
    return step_display, identity, _clip(detail, 600)


def _identity_from_fragment(fragment: str, index: int) -> str:
    text = sanitize_process_production_text(fragment, fallback="", max_len=120)
    if not text:
        return _clip(f"Stage {index + 1}", 48)
    if _STEP_NUM_ONLY_RE.match(text):
        return _identity_from_long_text(fragment, index)
    if ":" in text:
        title = text.split(":", 1)[0].strip()
        if title and len(title.split()) <= 4 and not is_prose_identity(title):
            return _clip(title, 48)
    first_sentence = text.split(".")[0].strip()
    if len(first_sentence.split()) <= 4 and not is_prose_identity(first_sentence):
        return _clip(first_sentence, 48)
    return _identity_from_long_text(text, index)
