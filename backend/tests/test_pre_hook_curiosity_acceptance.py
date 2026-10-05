"""Simulate English / Hinglish dual-channel payloads for manual acceptance."""

from __future__ import annotations

import json

from app.services.speech_note_dual import WRITING_MODE_NOTES, notes_payload, parse_prose_dual


def test_english_after_curiosity_style_payload() -> None:
    raw = json.dumps(
        {
            "text": (
                "I like your reasoning — not knowing yet leaves room to explore.\n\n"
                "When you feel ready, tap the button below and we will begin."
            ),
            "note": "Not knowing → room to explore",
        }
    )
    spoken, note, mode = parse_prose_dual(raw, language="english")
    assert mode == WRITING_MODE_NOTES
    payload = notes_payload(message=spoken, display_text=note)
    assert payload["message"] != payload["display_text"]
    assert "Ready when you are" not in (payload["display_text"] or "")
    assert "explore" in payload["display_text"].lower()


def test_hinglish_mirror_style_payload() -> None:
    raw = json.dumps(
        {
            "text": (
                "Koi baat nahi. Socho ek patthar aur ek chidiya dono hawa mein hain, "
                "lekin chidiya apne aap move kar sakti hai."
            ),
            "note": "Patthar vs chidiya → self-movement",
        }
    )
    spoken, note, mode = parse_prose_dual(raw, language="hinglish")
    assert mode == WRITING_MODE_NOTES
    payload = notes_payload(message=spoken, display_text=note)
    assert "patthar" in payload["display_text"].lower()
    assert len(payload["display_text"]) < len(payload["message"])
