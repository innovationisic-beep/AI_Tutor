"""Helpers for surfacing micro-teaching prompts to the client (read-only)."""

from __future__ import annotations

import re

_QUESTION_STARTERS = (
    "what ",
    "which ",
    "how ",
    "why ",
    "when ",
    "who ",
    "where ",
    "can ",
    "could ",
    "would ",
    "should ",
    "is ",
    "are ",
    "do ",
    "does ",
    "did ",
    "name ",
    "tell ",
    "give ",
    "explain ",
    "describe ",
)

_MIN_MEANINGFUL_LEN = 18

# Same blank shapes as concept_check_question_types.BLANK_MARKER_RE
_BLANK_MARKER_RE = re.compile(
    r"_{3,}|____+|\[blank\]|\{\{\s*blank\s*\}\}",
    re.IGNORECASE,
)


def _has_blank_marker(text: str) -> bool:
    return bool(_BLANK_MARKER_RE.search(text or ""))


def _looks_like_option_fragment(text: str) -> bool:
    """Detect bare choice lists like 'a rock, a tree, or a spoon?'"""
    t = (text or "").strip()
    if not t.endswith("?"):
        return False
    # Fill-in stems are never option fragments.
    if _has_blank_marker(t):
        return False
    lower = t.lower().rstrip("?").strip()
    if any(lower.startswith(s) for s in _QUESTION_STARTERS):
        return False
    if re.search(r"\bor\b", lower) and re.match(r"^(?:a|an|the)\s+", lower):
        return True
    if re.search(r"\bor\b", lower) and "," in lower and len(lower.split()) <= 16:
        return True
    if len(lower) < _MIN_MEANINGFUL_LEN:
        return True
    return False


def _question_quality_score(text: str) -> int:
    t = (text or "").strip()
    if _has_blank_marker(t):
        return len(t) + 80
    if not t.endswith("?"):
        return -100
    score = len(t)
    lower = t.lower()
    if any(lower.startswith(s) for s in _QUESTION_STARTERS):
        score += 40
    if _looks_like_option_fragment(t):
        score -= 200
    if len(t) >= 40:
        score += 15
    if ":" in t and not _looks_like_option_fragment(t):
        score += 10
    return score


def is_meaningful_concept_question(text: str) -> bool:
    """True when text is a complete learner-facing question, not a fragment."""
    t = (text or "").strip()
    # Fill-in-the-blank stems are valid prompts even without "?" / interrogatives.
    if _has_blank_marker(t) and len(t) >= 8:
        return True
    if not t.endswith("?"):
        return False
    if _looks_like_option_fragment(t):
        return False
    lower = t.lower()
    # Complete interrogatives can be short ("Do humans laugh?") — do not force
    # the 18-char floor that was meant to reject option-list fragments.
    if any(lower.startswith(s) for s in _QUESTION_STARTERS):
        return len(t) >= 10
    if lower.startswith(("true or false", "yes or no")):
        return True
    if len(t) < _MIN_MEANINGFUL_LEN:
        return False
    return len(t) >= 35 and not _looks_like_option_fragment(t)


def fallback_concept_question(concept: str | None, index: int = 0) -> str:
    c = (concept or "this key idea").strip()
    templates = [
        f"What is one important thing to know about {c}?",
        f"Can you explain {c} in your own words?",
        f"Give one example that shows you understand {c}.",
    ]
    return templates[max(0, min(index, len(templates) - 1))]


def _ensure_question_mark(text: str) -> str:
    t = text.strip()
    return t if t.endswith("?") else f"{t.rstrip('.!')}?"


def _try_merge_stem_and_options(stem: str, options: str) -> str | None:
    stem_t = stem.strip().rstrip(".!?").strip()
    opt_t = _ensure_question_mark(options.strip())
    if not stem_t or not _looks_like_option_fragment(opt_t):
        return None
    if not any(stem_t.lower().startswith(s) for s in _QUESTION_STARTERS):
        return None
    merged = f"{stem_t}: {opt_t.rstrip('?').strip()}?"
    return merged if is_meaningful_concept_question(merged) else None


def normalize_concept_question_text(
    full_text: str | None,
    *,
    concept: str | None = None,
    question_index: int = 0,
) -> str:
    """
    Return a complete, learner-facing question extracted from stored quiz text.

    Rejects option-only fragments and merges stems with choice lists when needed.
    Fill-in-the-blank stems are returned as authored (blank kept).
    """
    text = (full_text or "").strip()
    if not text:
        return fallback_concept_question(concept, question_index)

    # Authored / generated fill-in stems must display verbatim — never replace
    # with the generic "important thing" fallback.
    if _has_blank_marker(text) and is_meaningful_concept_question(text):
        return text

    line_parts = [p.strip() for p in re.split(r"\n+", text) if p.strip()]
    if len(line_parts) >= 2:
        merged = _try_merge_stem_and_options(line_parts[0], line_parts[1])
        if merged:
            return merged
        for i in range(len(line_parts) - 1):
            merged = _try_merge_stem_and_options(line_parts[i], line_parts[i + 1])
            if merged:
                return merged

    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    questions = [s for s in sentences if s.endswith("?") or _has_blank_marker(s)]

    if questions:
        for i, s in enumerate(sentences):
            if not s.endswith("?"):
                continue
            if i + 1 < len(sentences):
                merged = _try_merge_stem_and_options(s, sentences[i + 1])
                if merged:
                    return merged

        ranked = sorted(questions, key=_question_quality_score, reverse=True)
        for cand in ranked:
            if is_meaningful_concept_question(cand):
                return cand

    if text.endswith("?") and is_meaningful_concept_question(text):
        return text

    paragraph_parts = [p.strip() for p in text.split("\n\n") if p.strip()]
    for part in paragraph_parts:
        if part == text:
            continue
        inner = normalize_concept_question_text(
            part,
            concept=concept,
            question_index=question_index,
        )
        if inner != fallback_concept_question(concept, question_index) and is_meaningful_concept_question(
            inner
        ):
            return inner

    if text and not text.endswith("?"):
        candidate = f"{text.rstrip('.!')}?"
        if is_meaningful_concept_question(candidate):
            return candidate

    return fallback_concept_question(concept, question_index)


def extract_micro_interaction_prompt(current_question: str | None) -> str:
    """
    Pull the learner-facing question from session.current_question.

    Prefers a complete question sentence; never returns bare option lists.
    """
    return normalize_concept_question_text(current_question)
