"""Zone 0 dual-channel (speech vs written note) — parse + payload helpers."""

from __future__ import annotations

import json

from app.services.handlers.zone0_handler import (
    WRITING_MODE_LEGACY,
    WRITING_MODE_NOTES,
    _parse_zone0_prose_dual,
    _zone0_notes_fields,
)


def test_parse_prose_json_rich_message_and_short_note() -> None:
    raw = json.dumps(
        {
            "text": (
                "Sunlight is a strong place to start — plants really do lean on light.\n\n"
                "When you're ready, tap the button below."
            ),
            "note": "Ready when you are",
        }
    )
    spoken, note, mode = _parse_zone0_prose_dual(raw)
    assert mode == WRITING_MODE_NOTES
    assert "Sunlight" in spoken
    assert note == "Ready when you are"
    assert note != spoken


def test_parse_prose_empty_note_is_speak_only_notes_mode() -> None:
    raw = json.dumps(
        {
            "text": "Thanks for sharing that thought.\n\nTap Ready when you like.",
            "note": "",
        }
    )
    spoken, note, mode = _parse_zone0_prose_dual(raw)
    assert mode == WRITING_MODE_NOTES
    assert spoken.startswith("Thanks")
    assert note == ""


def test_parse_prose_plain_text_falls_back_to_legacy() -> None:
    raw = (
        "Thanks for sharing that — it helps me see where you're coming from.\n\n"
        "If you're ready to begin the lesson, tap the button below whenever you like."
    )
    spoken, note, mode = _parse_zone0_prose_dual(raw)
    assert mode == WRITING_MODE_LEGACY
    assert spoken == raw.strip()
    assert note == ""


def test_parse_prose_fenced_json() -> None:
    raw = (
        "```json\n"
        '{"text": "Warm spoken reply.", "note": "One-line takeaway"}\n'
        "```"
    )
    spoken, note, mode = _parse_zone0_prose_dual(raw)
    assert mode == WRITING_MODE_NOTES
    assert spoken == "Warm spoken reply."
    assert note == "One-line takeaway"


def test_parse_prose_missing_text_falls_back_legacy() -> None:
    raw = json.dumps({"note": "orphan note"})
    spoken, note, mode = _parse_zone0_prose_dual(raw)
    assert mode == WRITING_MODE_LEGACY
    assert note == ""
    assert "orphan" in spoken or spoken.startswith("{")


def test_notes_fields_payload_for_board() -> None:
    payload = _zone0_notes_fields(
        message="Full spoken paragraphs here.",
        display_text="Ready when you are",
    )
    assert payload["writing_mode"] == WRITING_MODE_NOTES
    assert payload["display_text"] == "Ready when you are"
    assert payload["message"] == "Full spoken paragraphs here."
    assert payload["visual"]["type"] == "zone0_display"
    assert payload["visual"]["writing_mode"] == WRITING_MODE_NOTES
    assert payload["visual"]["display_text"] == "Ready when you are"


def test_notes_fields_empty_display_is_speak_only() -> None:
    payload = _zone0_notes_fields(message="Spoken only.", display_text="")
    assert payload["writing_mode"] == WRITING_MODE_NOTES
    assert payload["display_text"] == ""


def test_notes_fields_include_writes_on_visual() -> None:
    writes = [{"sentence_index": 0, "text": "Light fuels growth"}]
    payload = _zone0_notes_fields(
        message="Light matters. Ready when you like.",
        display_text="Light fuels growth",
        writes=writes,
    )
    assert payload["writes"] == writes
    assert payload["visual"]["writes"] == writes


def test_session_service_merges_writes_into_board_visual() -> None:
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "app" / "services" / "session_service.py"
    text = src.read_text(encoding="utf-8")
    assert 'writes = result.get("writes")' in text
    assert 'merged["writes"] = writes' in text


def test_hinglish_devanagari_in_note_dropped() -> None:
    raw = json.dumps(
        {
            "text": "Yeh ek warm reply hai.",
            "note": "तैयार जब तुम हो",
        }
    )
    spoken, note, mode = _parse_zone0_prose_dual(raw, language="hinglish")
    assert mode == WRITING_MODE_NOTES
    assert spoken == "Yeh ek warm reply hai."
    assert note == ""
