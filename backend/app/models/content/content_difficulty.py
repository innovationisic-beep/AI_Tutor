"""Shared difficulty strings for topic notes and question bank rows."""

from __future__ import annotations

from typing import Any, Literal

ContentDifficulty = Literal["basic", "medium", "hard"]

ALLOWED_CONTENT_DIFFICULTY = frozenset({"basic", "medium", "hard"})


def normalize_content_difficulty_from_storage(v: Any) -> str:
    """
    Lenient coercion when loading from DB (legacy int, unknown strings → safe default).
    """
    if v is None or v == "":
        return "medium"
    if isinstance(v, bool):
        return "medium"
    if isinstance(v, int):
        if v <= 1:
            return "basic"
        if v == 2:
            return "medium"
        return "hard"
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ALLOWED_CONTENT_DIFFICULTY:
            return s
        if s.isdigit():
            return normalize_content_difficulty_from_storage(int(s))
        return "medium"
    return "medium"


def parse_content_difficulty_strict(v: Any) -> str:
    """
    API / user input: only basic | medium | hard, or legacy int 1–5.
    """
    if v is None or v == "":
        return "medium"
    if isinstance(v, int):
        return normalize_content_difficulty_from_storage(v)
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ALLOWED_CONTENT_DIFFICULTY:
            return s
        if s.isdigit():
            return normalize_content_difficulty_from_storage(int(s))
    raise ValueError('difficulty_level must be "basic", "medium", or "hard"')


def difficulty_for_json(value: Any) -> str:
    """Response serialization: normalize numeric legacy to string labels."""
    return normalize_content_difficulty_from_storage(value)
