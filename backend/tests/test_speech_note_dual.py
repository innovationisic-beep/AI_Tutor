"""Shared speech/note dual-channel helpers — including sentence-anchored writes."""

from __future__ import annotations

import json

from app.services.speech_note_dual import (
    WRITING_MODE_LEGACY,
    WRITING_MODE_NOTES,
    map_source_sentence_to_index,
    normalize_board_writes,
    notes_payload,
    parse_prose_dual,
    parse_prose_dual_full,
    split_spoken_sentences,
)


def test_parse_prose_json_rich_message_and_short_note() -> None:
    raw = json.dumps(
        {
            "text": (
                "Sunlight is a strong place to start — plants really do lean on light.\n\n"
                "When you're ready, tap the button below."
            ),
            "note": "Light fuels plant growth",
        }
    )
    spoken, note, mode = parse_prose_dual(raw)
    assert mode == WRITING_MODE_NOTES
    assert "Sunlight" in spoken
    assert note == "Light fuels plant growth"
    assert note != spoken


def test_parse_prose_empty_note_is_speak_only_notes_mode() -> None:
    raw = json.dumps(
        {
            "text": "Thanks for sharing that thought.\n\nTap Ready when you like.",
            "note": "",
        }
    )
    spoken, note, mode = parse_prose_dual(raw)
    assert mode == WRITING_MODE_NOTES
    assert spoken.startswith("Thanks")
    assert note == ""


def test_parse_prose_plain_text_falls_back_to_legacy() -> None:
    raw = (
        "Thanks for sharing that — it helps me see where you're coming from.\n\n"
        "If you're ready to begin the lesson, tap the button below whenever you like."
    )
    spoken, note, mode = parse_prose_dual(raw)
    assert mode == WRITING_MODE_LEGACY
    assert spoken == raw.strip()
    assert note == ""


def test_notes_payload_for_board() -> None:
    payload = notes_payload(
        message="Full spoken paragraphs here.",
        display_text="Self-movement differs",
    )
    assert payload["writing_mode"] == WRITING_MODE_NOTES
    assert payload["display_text"] == "Self-movement differs"
    assert payload["message"] == "Full spoken paragraphs here."
    assert payload["visual"]["type"] == "zone0_display"


def test_hinglish_devanagari_in_note_dropped() -> None:
    raw = json.dumps(
        {
            "text": "Yeh ek warm reply hai.",
            "note": "तैयार जब तुम हो",
        }
    )
    spoken, note, mode = parse_prose_dual(raw, language="hinglish")
    assert mode == WRITING_MODE_NOTES
    assert spoken == "Yeh ek warm reply hai."
    assert note == ""


def test_split_spoken_sentences_basic() -> None:
    text = "Hello there. What next? Cool!"
    assert split_spoken_sentences(text) == ["Hello there.", "What next?", "Cool!"]


def test_map_source_sentence_exact_and_near() -> None:
    sentences = split_spoken_sentences(
        "When stomata open, CO2 enters. Water escapes too."
    )
    assert (
        map_source_sentence_to_index("When stomata open, CO2 enters.", sentences) == 0
    )
    assert (
        map_source_sentence_to_index("when stomata open, CO2 enters", sentences) == 0
    )
    assert map_source_sentence_to_index("totally unrelated line", sentences) is None


def test_map_source_sentence_ambiguous_containment_drops() -> None:
    sentences = ["Water escapes quickly.", "Water escapes slowly."]
    # Contained in both → ambiguous → None
    assert map_source_sentence_to_index("Water escapes", sentences) is None


def test_normalize_writes_from_source_sentence() -> None:
    spoken = (
        "Imagine a leaf with hundreds of tiny gates. "
        "The plant opens them for carbon dioxide."
    )
    writes = normalize_board_writes(
        spoken_text=spoken,
        raw_writes=[
            {
                "source_sentence": "Imagine a leaf with hundreds of tiny gates.",
                "text": "Stomata = tiny leaf gates",
            }
        ],
    )
    assert writes == [
        {"sentence_index": 0, "text": "Stomata = tiny leaf gates"},
    ]


def test_normalize_ignores_bare_sentence_index() -> None:
    spoken = "First sentence. Second sentence."
    writes = normalize_board_writes(
        spoken_text=spoken,
        raw_writes=[{"sentence_index": 1, "text": "Should drop without source"}],
    )
    assert writes == []


def test_short_verbatim_allowed_long_verbatim_rejected() -> None:
    short = "Stomata are tiny pores."
    writes_ok = normalize_board_writes(
        spoken_text=short,
        raw_writes=[{"source_sentence": short, "text": short}],
    )
    assert writes_ok == [{"sentence_index": 0, "text": short}]

    long_sent = (
        "That is a really long conversational spoken sentence that goes on and on "
        "about many soft ideas without a tight board-worthy core and should not "
        "be chalked verbatim onto the teacher board at all."
    )
    assert len(long_sent) > 100
    writes_bad = normalize_board_writes(
        spoken_text=long_sent,
        raw_writes=[{"source_sentence": long_sent, "text": long_sent}],
    )
    assert writes_bad == []


def test_parse_prose_dual_full_writes_and_payload() -> None:
    raw = json.dumps(
        {
            "text": "Light matters for plants. Ready when you like.",
            "writes": [
                {
                    "source_sentence": "Light matters for plants.",
                    "text": "Light fuels growth",
                }
            ],
        }
    )
    spoken, note, mode, writes = parse_prose_dual_full(raw)
    assert mode == WRITING_MODE_NOTES
    assert spoken.startswith("Light")
    assert note == "Light fuels growth"
    assert writes == [{"sentence_index": 0, "text": "Light fuels growth"}]
    payload = notes_payload(message=spoken, display_text=note, writes=writes)
    assert payload["writes"] == writes
    assert payload["visual"]["writes"] == writes
