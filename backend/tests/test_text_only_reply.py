"""Tests for plain-text reply coercion (no legacy JSON/visual)."""

from app.services.handlers.text_only_reply import coerce_plain_text_reply


def test_coerce_extracts_explanation_from_json_leak() -> None:
    raw = (
        '{"explanation": "Living things grow, respire, and reproduce.", '
        '"visual": {"type": "list", "items": ["growth"], "emojis": ["🌱"]}}'
    )
    assert coerce_plain_text_reply(raw) == "Living things grow, respire, and reproduce."


def test_coerce_passes_through_plain_text() -> None:
    assert coerce_plain_text_reply("Hello student.") == "Hello student."
