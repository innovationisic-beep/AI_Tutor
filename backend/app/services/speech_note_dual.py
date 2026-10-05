"""
Shared dual-channel speech vs written note helpers.

Tiny module for pre-Story-Hook curiosity prose (Zone 0 + pedagogy cluster feedback).
Not a pedagogy framework — parse / payload / prompt fragment only.

Supports:
- Legacy flat ``note``
- Sentence-anchored ``writes`` (LLM ``source_sentence`` → validated ``sentence_index``)
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any

WRITING_MODE_LEGACY = "legacy"
WRITING_MODE_NOTES = "notes"
MAX_NOTE_CHARS = 280
MAX_WRITE_CHARS = 120
MAX_WRITES = 8
VERBATIM_MAX_CHARS = 100
SOURCE_MATCH_RATIO = 0.85
CONTAIN_MIN_FRACTION = 0.6

_DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")
_JSON_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.?!])\s+")
_TRAILING_PUNCT_RE = re.compile(r"[.?!]+$")

logger = logging.getLogger(__name__)

PROSE_DUAL_RULES = (
    "\n\nOUTPUT FORMAT — return ONE JSON object only, no markdown fences:\n"
    '{"text": "full spoken teacher language", '
    '"writes": [{"source_sentence": "exact/near-exact spoken sentence", '
    '"text": "concise board phrase"}]}\n'
    "Legacy also accepted: {\"text\": \"...\", \"note\": \"optional flat note\"}\n\n"
    "SPOKEN (text):\n"
    "- Rich, warm, natural, curiosity-building teacher speech.\n"
    "- Analogies, examples, and soft transitions are welcome when they fit.\n"
    "- Still pre-lesson: do not teach the full concept or list curriculum facts.\n\n"
    "BOARD WRITES (writes):\n"
    "- Zero or more entries. Empty writes: [] is fine (speak-only).\n"
    "- Only add a write for a spoken sentence with a durable teachable idea.\n"
    "- source_sentence: copy that sentence from text (exact or near-exact).\n"
    "- text: meaning-preserving short form of THAT sentence only "
    "(phrase or short sentence — not keywords-only).\n"
    "- Exact copy of source_sentence is OK when that sentence is already short "
    "and board-ready. Do NOT paste long conversational spoken lines onto the board.\n"
    "- Conversational / acknowledgment / transition / filler sentences → no write.\n"
    "- Never write praise, 'Ready when you are', button/UI instructions, or filler.\n"
    "- Do not emit one global summary covering the whole turn.\n"
)


def strip_json_fence(raw: str) -> str:
    return _JSON_FENCE_RE.sub("", str(raw or "")).strip()


def _normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", str(text or ""))).strip()


def split_spoken_sentences(text: str) -> list[str]:
    """Deterministic sentence list shared with FE (normalize + (?<=[.?!])\\s+)."""
    normalized = _normalize_space(text)
    if not normalized:
        return []
    return [s.strip() for s in _SENTENCE_SPLIT_RE.split(normalized) if s.strip()]


def _fold_for_match(text: str) -> str:
    folded = _normalize_space(text).casefold()
    return _TRAILING_PUNCT_RE.sub("", folded).strip()


def map_source_sentence_to_index(
    source_sentence: str,
    sentences: list[str],
) -> int | None:
    """
    Map LLM source_sentence onto splitSpokenSentences(text).

    Prefer drop over wrong beat: ambiguous / no hit → None.
    """
    source = _normalize_space(source_sentence)
    if not source or not sentences:
        return None

    # 1) Exact
    for i, s in enumerate(sentences):
        if source == s:
            return i

    source_fold = _fold_for_match(source)
    # 2) Casefold + strip trailing .?!
    exact_fold_hits: list[int] = []
    for i, s in enumerate(sentences):
        if source_fold == _fold_for_match(s):
            exact_fold_hits.append(i)
    if len(exact_fold_hits) == 1:
        return exact_fold_hits[0]
    if len(exact_fold_hits) > 1:
        return None

    # 3) Unique containment (source in sentence or sentence in source with length gate)
    contain_hits: list[int] = []
    for i, s in enumerate(sentences):
        s_fold = _fold_for_match(s)
        if not s_fold:
            continue
        if source_fold in s_fold:
            contain_hits.append(i)
            continue
        if s_fold in source_fold and len(s_fold) >= CONTAIN_MIN_FRACTION * max(len(source_fold), 1):
            contain_hits.append(i)
    if len(contain_hits) == 1:
        return contain_hits[0]
    if len(contain_hits) > 1:
        return None

    # 4) Soft ratio — unique best ≥ threshold
    best_i: int | None = None
    best_ratio = 0.0
    tied = False
    for i, s in enumerate(sentences):
        ratio = SequenceMatcher(None, source_fold, _fold_for_match(s)).ratio()
        if ratio > best_ratio + 1e-9:
            best_ratio = ratio
            best_i = i
            tied = False
        elif abs(ratio - best_ratio) <= 1e-9 and ratio >= SOURCE_MATCH_RATIO:
            tied = True
    if tied or best_i is None or best_ratio < SOURCE_MATCH_RATIO:
        return None
    return best_i


def _is_transcript_like_verbatim(write_text: str, spoken_sentence: str) -> bool:
    """True when exact/near copy would dump long conversational speech onto the board."""
    w = _normalize_space(write_text)
    s = _normalize_space(spoken_sentence)
    if not w or not s:
        return False
    if _fold_for_match(w) != _fold_for_match(s):
        return False
    return len(s) > VERBATIM_MAX_CHARS


def normalize_board_writes(
    *,
    spoken_text: str,
    raw_writes: Any = None,
    legacy_note: str = "",
) -> list[dict[str, Any]]:
    """
    Normalize LLM writes (source_sentence) or legacy note into runtime writes.

    Runtime shape: [{sentence_index: int, text: str}, ...]
    Bare LLM sentence_index is ignored as authority (v1).
    """
    sentences = split_spoken_sentences(spoken_text)
    if not sentences:
        return []

    out: list[dict[str, Any]] = []
    seen_indices: set[int] = set()

    if isinstance(raw_writes, list):
        for item in raw_writes:
            if len(out) >= min(MAX_WRITES, len(sentences)):
                break
            if not isinstance(item, dict):
                continue
            write_text_raw = _normalize_space(str(item.get("text") or ""))
            if not write_text_raw:
                continue
            write_text = write_text_raw[:MAX_WRITE_CHARS]
            source = str(item.get("source_sentence") or item.get("spoken_anchor") or "").strip()
            if not source:
                # No source_sentence → drop (do not trust bare sentence_index).
                continue
            idx = map_source_sentence_to_index(source, sentences)
            if idx is None:
                logger.info(
                    "speech_note_dual: dropped write — unmapped source_sentence=%r",
                    source[:80],
                )
                continue
            if idx in seen_indices:
                continue
            # Verbatim policy uses the untruncated write vs spoken sentence.
            if _is_transcript_like_verbatim(write_text_raw, sentences[idx]):
                logger.info(
                    "speech_note_dual: dropped long verbatim write at sentence_index=%s",
                    idx,
                )
                continue
            seen_indices.add(idx)
            out.append({"sentence_index": idx, "text": write_text})

    if out:
        return out

    # Legacy flat note → attach to first sentence when non-empty
    note = _normalize_space(legacy_note)[:MAX_NOTE_CHARS]
    if note:
        if _is_transcript_like_verbatim(note, sentences[0]) or (
            _fold_for_match(note) == _fold_for_match(_normalize_space(spoken_text))
            and len(note) > VERBATIM_MAX_CHARS
        ):
            return []
        return [{"sentence_index": 0, "text": note[:MAX_WRITE_CHARS]}]
    return []


def _filter_devanagari_writes(
    spoken: str,
    writes: list[dict[str, Any]],
    *,
    language: str,
) -> tuple[str, list[dict[str, Any]]]:
    """Hinglish: drop Devanagari from board ink (and strip note-equivalent)."""
    if str(language).strip().lower() != "hinglish":
        return spoken, writes
    if _DEVANAGARI_RE.search(spoken):
        # Spoken with Devanagari is a language-policy concern elsewhere; keep as-is.
        pass
    cleaned: list[dict[str, Any]] = []
    for w in writes:
        text = str(w.get("text") or "")
        if text and _DEVANAGARI_RE.search(text):
            continue
        cleaned.append(w)
    return spoken, cleaned


def _join_writes_as_note(writes: list[dict[str, Any]]) -> str:
    parts = [str(w.get("text") or "").strip() for w in writes if str(w.get("text") or "").strip()]
    return "\n".join(parts)[:MAX_NOTE_CHARS]


def _extract_json_payload(text: str) -> dict | None:
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        try:
            parsed = json.loads(text[start : end + 1])
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return None
    return None


def parse_prose_dual_full(
    raw: str | None,
    *,
    language: str = "english",
) -> tuple[str, str, str, list[dict[str, Any]]]:
    """
    Parse non-question prose LLM output.

    Returns (spoken_text, flat_note, writing_mode, normalized_writes).
    On failure: treat whole string as spoken with writing_mode=legacy.
    """
    text = strip_json_fence(raw or "")
    if not text:
        return "", "", WRITING_MODE_LEGACY, []

    payload = _extract_json_payload(text)
    if payload is None:
        logger.warning("speech_note_dual: JSON parse fallback to legacy prose")
        return text.strip(), "", WRITING_MODE_LEGACY, []

    spoken = str(payload.get("text") or payload.get("message") or "").strip()
    if not spoken:
        logger.warning("speech_note_dual: empty text in JSON → legacy")
        return text.strip(), "", WRITING_MODE_LEGACY, []

    legacy_note = str(payload.get("note") or payload.get("display_text") or "").strip()
    writes = normalize_board_writes(
        spoken_text=spoken,
        raw_writes=payload.get("writes"),
        legacy_note=legacy_note,
    )
    spoken, writes = _filter_devanagari_writes(spoken, writes, language=language)
    note = _join_writes_as_note(writes)
    if not note and legacy_note and not writes:
        # Devanagari strip may have cleared writes derived from note
        note = ""
    return spoken, note, WRITING_MODE_NOTES, writes


def parse_prose_dual(
    raw: str | None,
    *,
    language: str = "english",
) -> tuple[str, str, str]:
    """
    Parse non-question prose LLM output.

    Returns (spoken_text, note, writing_mode).
    On failure: treat whole string as spoken with writing_mode=legacy.
    """
    spoken, note, mode, _writes = parse_prose_dual_full(raw, language=language)
    return spoken, note, mode


def notes_payload(
    *,
    message: str,
    display_text: str = "",
    writes: list[dict[str, Any]] | None = None,
    visual_type: str = "zone0_display",
) -> dict:
    """Build writing_mode/display_text/writes (+ visual) for notes-mode turns."""
    spoken = (message or "").strip()
    normalized_writes = list(writes or [])
    if normalized_writes and not (display_text or "").strip():
        note = _join_writes_as_note(normalized_writes)
    else:
        note = (display_text or "").strip()[:MAX_NOTE_CHARS]
    visual: dict[str, Any] = {
        "type": visual_type,
        "writing_mode": WRITING_MODE_NOTES,
        "display_text": note,
    }
    if normalized_writes:
        visual["writes"] = normalized_writes
    out: dict[str, Any] = {
        "writing_mode": WRITING_MODE_NOTES,
        "display_text": note,
        "visual": visual,
        "message": spoken,
    }
    if normalized_writes:
        out["writes"] = normalized_writes
    return out
