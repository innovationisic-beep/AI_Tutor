"""Tests for authored VTSE DeepSeek expansion helpers."""

from __future__ import annotations

from app.vtse.authoring.authored_expand import _too_similar


def test_too_similar_detects_verbatim():
    assert _too_similar("Living things grow", "Living things grow")
    assert _too_similar(
        "Living things grow.",
        "Living things grow",
    )


def test_too_similar_allows_expanded_prose():
    outline = "Living things grow"
    expanded = (
        "Living things grow because their cells keep dividing. "
        "For example, a tiny seed can become a tall tree over many years."
    )
    assert not _too_similar(expanded, outline)
