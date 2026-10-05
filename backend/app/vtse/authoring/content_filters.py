"""Shared content filters for Zone 1 authoring (process / hierarchy / comparison)."""

from __future__ import annotations

import re

_PRACTICE_MARKERS = (
    "[practice question",
    "for reference only",
    "[video explanation",
    "[subtitle]",
)

_QUESTION_STARTERS = (
    "what ", "can ", "why ", "how ", "is ", "are ", "when ", "which ",
    "does ", "do ", "did ", "will ", "could ", "should ", "would ",
    "name ", "list ", "describe ", "explain ", "define ",
)

_QUESTION_RE = re.compile(r"\?$")
_SCAFFOLD_HEADER_RE = re.compile(r"^\[[^\]]+\]\s*$", re.IGNORECASE)
_INLINE_SCAFFOLD_RE = re.compile(
    r"^\[(?:Detailed|TODO|TBD|placeholder)[^\]]*\]\s*",
    re.IGNORECASE,
)
_PLACEHOLDER_RE = re.compile(
    r"\[(?:Detailed|TODO|TBD|placeholder)[^\]]*\]",
    re.IGNORECASE,
)
_PLACEHOLDER_PHRASES = (
    "[detailed",
    "detailed —",
    "detailed -",
    "concept a",
    "concept b",
    "other ...",
    "lorem ipsum",
    "tbd",
    "placeholder",
)


def is_placeholder_text(text: str | None) -> bool:
    raw = (text or "").strip().lower()
    if not raw or len(raw) < 3:
        return True
    if _PLACEHOLDER_RE.search(raw):
        return True
    return any(p in raw for p in _PLACEHOLDER_PHRASES)


def strip_placeholder_markers(text: str) -> str:
    return _PLACEHOLDER_RE.sub("", (text or "").strip()).strip()


def is_practice_or_support_content(text: str | None) -> bool:
    """True when text is practice/reference/support material, not main teaching."""
    raw = (text or "").strip().lower()
    if not raw or len(raw) < 6:
        return False
    return any(marker in raw for marker in _PRACTICE_MARKERS)


def is_question_text(text: str | None) -> bool:
    """True when text reads as a question (starts with interrogative word or ends with '?')."""
    raw = (text or "").strip()
    if not raw:
        return False
    if _QUESTION_RE.search(raw):
        return True
    low = raw.lower()
    return any(low.startswith(q) for q in _QUESTION_STARTERS)


def is_unsuitable_hierarchy_label(text: str | None) -> bool:
    """True when text should be rejected as a hierarchy node label."""
    if is_practice_or_support_content(text):
        return True
    if is_question_text(text):
        return True
    return False


def is_authoring_scaffold_header(text: str | None) -> bool:
    """True for RAG bracket headers like ``[Detailed — concept: living things]``."""
    raw = (text or "").strip()
    if not raw:
        return False
    if is_practice_or_support_content(raw):
        return True
    if _SCAFFOLD_HEADER_RE.match(raw):
        return True
    if raw.startswith("[") and "concept" in raw.lower() and raw.endswith("]"):
        return True
    return False


def strip_scaffold_prefix(text: str) -> str:
    """Remove leading bracket scaffolding from a content line."""
    cleaned = _INLINE_SCAFFOLD_RE.sub("", (text or "").strip()).strip()
    return cleaned


def sanitize_process_production_text(text: str | None, *, fallback: str, max_len: int = 480) -> str:
    """Production-safe process text — no placeholders or bracket scaffolding."""
    cleaned = strip_scaffold_prefix((text or "").strip())
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned or is_placeholder_text(cleaned) or is_practice_or_support_content(cleaned):
        return fallback
    if len(cleaned) > max_len:
        return cleaned[: max_len - 1].rstrip() + "…"
    return cleaned
