"""Concept-check question type helpers (MCQ, fill-in-the-blank, descriptive)."""

from __future__ import annotations

import re
from typing import Literal, TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.content.topic_question_bank import TopicQuestionBank

ConceptCheckQuestionType = Literal["mcq", "fill_in_blank", "descriptive"]

BLANK_MARKER_RE = re.compile(
    r"_{3,}|____+|\[blank\]|\{\{\s*blank\s*\}\}",
    re.IGNORECASE,
)

DESCRIPTIVE_STEM_RE = re.compile(
    r"\b("
    r"explain in your own words|describe in detail|give a detailed explanation|"
    r"write an essay|discuss at length|elaborate on"
    r")\b",
    re.IGNORECASE,
)

# Pronouns / fillers — never valid as the blanked "important word" for fill-in.
_FILL_IN_WEAK_TOKENS = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "but",
        "for",
        "with",
        "from",
        "into",
        "onto",
        "over",
        "under",
        "about",
        "above",
        "after",
        "before",
        "between",
        "also",
        "just",
        "only",
        "very",
        "more",
        "most",
        "some",
        "any",
        "all",
        "each",
        "every",
        "such",
        "than",
        "then",
        "that",
        "this",
        "these",
        "those",
        "there",
        "their",
        "theirs",
        "them",
        "they",
        "themself",
        "themselves",
        "himself",
        "herself",
        "itself",
        "myself",
        "yourself",
        "yourselves",
        "ourselves",
        "him",
        "her",
        "his",
        "its",
        "our",
        "ours",
        "your",
        "yours",
        "who",
        "whom",
        "whose",
        "which",
        "what",
        "when",
        "where",
        "while",
        "how",
        "why",
        "can",
        "could",
        "will",
        "would",
        "should",
        "shall",
        "may",
        "might",
        "must",
        "being",
        "been",
        "have",
        "has",
        "had",
        "having",
        "doing",
        "does",
        "did",
        "done",
        "make",
        "makes",
        "made",
        "making",
        "take",
        "takes",
        "took",
        "taking",
        "care",
        "own",
        "ones",
        "one",
        "thing",
        "things",
        "something",
        "anything",
        "nothing",
        "everything",
        "someone",
        "anyone",
        "people",
        "person",
        "someone",
        "able",
        "like",
        "into",
        "onto",
        "upon",
        "across",
        "because",
        "since",
        "during",
        "through",
        "around",
        "among",
        "other",
        "others",
        "another",
        "same",
        "different",
        "good",
        "well",
        "much",
        "many",
        "few",
        "lot",
        "lots",
    }
)


def is_strong_fill_in_answer(answer: str) -> bool:
    """
    True when the blank answer is a teachable content term, not a filler/pronoun.

    Example reject: "themselves", "things", "own".
    Example accept: "respire", "reproduce", "photosynthesis", "small intestine".
    """
    raw = normalize_answer_text(answer)
    if not raw:
        return False
    words = [re.sub(r"[^a-z'-]", "", w) for w in raw.split()]
    words = [w for w in words if w]
    if not words or len(words) > 4:
        return False
    if any(w in _FILL_IN_WEAK_TOKENS for w in words):
        # Multi-word answers may include a weak connector only if a strong term remains,
        # but single-token blanks must never be weak.
        if len(words) == 1:
            return False
    content = [w for w in words if w not in _FILL_IN_WEAK_TOKENS and len(w) >= 3]
    if not content:
        return False
    if len(words) == 1 and len(words[0]) < 3:
        return False
    # Majority of tokens must be content words.
    if len(content) < max(1, (len(words) + 1) // 2):
        return False
    return True


def pick_fill_in_answer_from_fact(fact: str) -> str | None:
    """Choose the strongest content token from a board fact to blank."""
    tokens = re.findall(r"[A-Za-z][A-Za-z'-]{2,}", fact or "")
    candidates: list[str] = []
    seen: set[str] = set()
    for tok in tokens:
        key = tok.lower()
        if key in seen:
            continue
        seen.add(key)
        if is_strong_fill_in_answer(tok):
            candidates.append(tok)
    if not candidates:
        return None
    # Prefer longer, more distinctive taught terms.
    candidates.sort(key=lambda w: (len(w), w.lower()), reverse=True)
    return candidates[0]


def infer_bank_question_type(question: TopicQuestionBank) -> ConceptCheckQuestionType:
    """Infer type from stored field or row shape (backward compatible)."""
    stored = getattr(question, "question_type", None)
    if stored in ("mcq", "fill_in_blank", "descriptive"):
        return stored  # type: ignore[return-value]

    options = list(getattr(question, "options", None) or [])
    text = str(getattr(question, "question_text", "") or "").strip()
    answer = str(getattr(question, "correct_answer", "") or "").strip()

    if len(options) >= 2:
        return "mcq"
    if BLANK_MARKER_RE.search(text) and answer:
        return "fill_in_blank"
    return "descriptive"


def has_blank_marker(text: str) -> bool:
    return bool(BLANK_MARKER_RE.search(text or ""))


def is_descriptive_stem(text: str) -> bool:
    return bool(DESCRIPTIVE_STEM_RE.search(text or ""))


def normalize_answer_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _mcq_reference_key(correct_answer: str) -> str:
    """Use only the keyed answer line, not appended lesson context."""
    text = (correct_answer or "").strip()
    if not text:
        return ""
    first = text.split("\n", 1)[0].strip()
    return first if first else text


def _option_token_in_reference(opt: str, ref: str) -> bool:
    token = normalize_answer_text(opt)
    if not token or not ref:
        return False
    return bool(re.search(rf"\b{re.escape(token)}\b", ref))


def resolve_mcq_correct_option(correct_answer: str, options: list[str]) -> str | None:
    """Map stored correct_answer to the matching option text when possible."""
    ref = normalize_answer_text(_mcq_reference_key(correct_answer))
    if not ref or not options:
        return None
    for opt in options:
        if normalize_answer_text(opt) == ref:
            return opt
    hits = [opt for opt in options if _option_token_in_reference(opt, ref)]
    if len(hits) == 1:
        return hits[0]
    return None


def mcq_answer_matches(student: str, correct_answer: str, options: list[str]) -> bool:
    """Case-insensitive match against the keyed correct option."""
    st = normalize_answer_text(student)
    if not st:
        return False
    selected = next(
        (opt for opt in options if normalize_answer_text(opt) == st),
        None,
    )
    if selected is None:
        return False
    correct_opt = resolve_mcq_correct_option(correct_answer, options)
    if correct_opt is not None:
        return normalize_answer_text(selected) == normalize_answer_text(correct_opt)
    return normalize_answer_text(selected) == normalize_answer_text(
        _mcq_reference_key(correct_answer)
    )
