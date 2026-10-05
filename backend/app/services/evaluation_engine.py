"""
Evaluation engine — LLM-based student answer evaluation with rule-based fallback.

Public API
----------
evaluate_answer(concept, student_answer, reference_context) -> dict

The function evaluates how well a student's free-text explanation covers one or
more target concepts.  It calls the same LLM backend used by the RAG service and
falls back to lightweight keyword matching when the LLM is unavailable.

Return schema (always returned, even on fallback)
-------------------------------------------------
{
    "score":         int (0–100)  — overall quality score.
    "correct":       bool         — True when score >= 60.
    "feedback":      str          — warm, specific 1–2 sentence feedback.
    "missing_points": list[str]   — concepts or ideas not addressed by the student.
}
"""

from __future__ import annotations

import json
import logging
import re
from typing import Union

from app.core.constants import TEACHBACK_PASS_THRESHOLD
from app.repositories.topic_note_repository import TopicNoteRepository
from app.repositories.topic_question_repository import TopicQuestionRepository
from app.repositories.topic_repository import TopicRepository
from app.repositories.video_subtitle_repository import VideoSubtitleRepository
from app.services.rag_service import RAGService

logger = logging.getLogger(__name__)

# Score at or above this threshold means the answer is considered correct.
_CORRECT_THRESHOLD = TEACHBACK_PASS_THRESHOLD

# Maximum number of characters kept from reference_context before sending to LLM.
_MAX_CONTEXT_CHARS: int = 900


# ─────────────────────────────────────────────────────────────────────────────
# Rule-based fallback (no I/O — used when LLM is unavailable)
# ─────────────────────────────────────────────────────────────────────────────


def _rule_based_evaluate(
    concept_list: list[str],
    student_answer: str,
) -> dict:
    """
    Lightweight keyword-based evaluation.

    Each concept is considered covered when at least one of its significant
    keywords (length > 3) appears in the student's answer.  Score combines
    concept coverage (70 %) and answer length as a depth proxy (30 %).
    """
    if not concept_list:
        return {
            "score": 100,
            "correct": True,
            "feedback": "Good answer!",
            "missing_points": [],
        }

    answer_lower = (student_answer or "").lower()
    covered: list[str] = []
    missing: list[str] = []
    for concept in concept_list:
        keywords = [w for w in concept.lower().split() if len(w) > 3]
        if not keywords:
            keywords = [concept.lower()]
        if any(kw in answer_lower for kw in keywords):
            covered.append(concept)
        else:
            missing.append(concept)

    coverage = len(covered) / len(concept_list)
    word_count = len((student_answer or "").strip().split())
    depth = min(1.0, word_count / 20.0)
    score = max(0, min(100, int(round(coverage * 70 + depth * 30))))
    correct = score >= _CORRECT_THRESHOLD

    if correct:
        feedback = "Good explanation — you've captured the key ideas."
    elif missing:
        missing_str = ", ".join(f'"{c}"' for c in missing[:3])
        feedback = f"Good attempt! Try to also address {missing_str}."
    else:
        feedback = "Try to explain the concept in a bit more detail."

    return {
        "score": score,
        "correct": correct,
        "feedback": feedback,
        "missing_points": missing,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Context cleaning (pure function — no I/O)
# ─────────────────────────────────────────────────────────────────────────────


def clean_context(context: str | None) -> str | None:
    """
    Normalise a reference context string before it is sent to the LLM.

    * Collapses runs of 3+ newlines to a single blank line.
    * Collapses runs of spaces/tabs (not newlines) to a single space.
    * Truncates to _MAX_CONTEXT_CHARS, cutting at the nearest line boundary.
    * Returns None when the input is None or whitespace-only.
    """
    if not context:
        return None
    text = re.sub(r"\n{3,}", "\n\n", context.strip())
    text = re.sub(r"[ \t]{2,}", " ", text)
    if not text:
        return None
    if len(text) > _MAX_CONTEXT_CHARS:
        truncated = text[:_MAX_CONTEXT_CHARS]
        # Prefer cutting at a newline so we don't split mid-sentence.
        last_nl = truncated.rfind("\n")
        text = truncated[:last_nl].rstrip() if last_nl > 0 else truncated
    return text


# ─────────────────────────────────────────────────────────────────────────────
# LLM evaluation (primary path)
# ─────────────────────────────────────────────────────────────────────────────


def _build_rag_service() -> RAGService:
    """Instantiate a RAGService with fresh repository instances."""
    return RAGService(
        TopicNoteRepository(),
        VideoSubtitleRepository(),
        TopicQuestionRepository(),
        TopicRepository(),
    )


async def _llm_evaluate(
    concept_list: list[str],
    student_answer: str,
    reference_context: str | None,
) -> dict:
    """
    Call the LLM for evaluation.  Raises on any failure so that the caller
    can fall back to rule-based evaluation.
    """
    rag_service = _build_rag_service()
    concepts_str = ", ".join(f'"{c}"' for c in concept_list)
    context_block = clean_context(reference_context) or ""

    evaluation_prompt = f"""\
You are an expert, empathetic tutor evaluating a student's explanation.

CONCEPTS BEING EVALUATED: {concepts_str}

STUDENT ANSWER:
{student_answer}

---

EVALUATION RULES (follow strictly):
1. Evaluate MEANING and conceptual understanding — not exact wording or terminology.
2. Accept paraphrased, informal, or simplified explanations.
3. If the student captures the core idea of a concept, count it as covered.
4. Detect genuine misconceptions — do NOT penalise vague wording alone.
5. When in doubt, lean toward CORRECT rather than incorrect.
6. Provide warm, specific 1–2 sentence feedback.

SCORING GUIDE:
  90–100 : Clear, thorough understanding of all concepts.
  70–89  : Good understanding with minor gaps.
  50–69  : Partial understanding — key ideas present but incomplete.
  30–49  : Limited understanding — some relevant ideas but significant gaps.
   0–29  : Minimal or incorrect understanding.

Respond ONLY with valid JSON (no markdown, no extra text):
{{"score": <int 0-100>, "correct": <true if score>=60>, "feedback": "<1-2 warm sentences>", "missing_points": ["<concept or idea not addressed>"]}}"""

    response = await rag_service.generate_prompt(
        question=evaluation_prompt,
        context=context_block,
        student_profile=None,
        topic_name=None,
        learning_state="explaining",
        user_intent="EVALUATE",
        last_answer=None,
        is_followup=False,
        current_concept=concept_list[0] if concept_list else None,
    )

    text = (response or "").strip()
    # Strip markdown code fences if present.
    if text.startswith("```"):
        rest = text.split("\n", 1)[-1] if "\n" in text else text[3:]
        text = rest.rsplit("```", 1)[0].strip()

    # Try direct JSON parse first; fall back to extracting embedded JSON object.
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        m = re.search(r"\{[\s\S]*\}", text)
        if not m:
            raise ValueError(f"No JSON object in LLM response: {text!r}")
        data = json.loads(m.group(0))

    score = max(0, min(100, int(data.get("score", 0))))
    correct = bool(data.get("correct", score >= _CORRECT_THRESHOLD))
    feedback = str(data.get("feedback") or "Good attempt — keep going!").strip()
    missing_points = [str(p) for p in (data.get("missing_points") or [])]

    return {
        "score": score,
        "correct": correct,
        "feedback": feedback,
        "missing_points": missing_points,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────


async def evaluate_answer(
    concept: Union[str, list[str]],
    student_answer: str,
    reference_context: str | None = None,
) -> dict:
    """
    Evaluate a student's explanation using LLM-based evaluation.

    Falls back to rule-based keyword matching when the LLM call fails so that
    the caller is never left without a result.

    Args:
        concept:           A single concept name or a list of concept names.
        student_answer:    The student's free-text explanation.
        reference_context: Optional curriculum context to guide evaluation.

    Returns:
        {
            "score":          int (0–100),
            "correct":        bool,
            "feedback":       str,
            "missing_points": list[str],
        }
    """
    concept_list: list[str] = (
        [concept] if isinstance(concept, str) else list(concept or [])
    )

    if not student_answer or not student_answer.strip():
        return {
            "score": 0,
            "correct": False,
            "feedback": "Please share your explanation — there's no wrong answer!",
            "missing_points": concept_list,
        }

    try:
        return await _llm_evaluate(concept_list, student_answer, reference_context)
    except Exception:
        logger.exception(
            "LLM evaluation failed for concepts=%r — using rule-based fallback",
            concept_list,
        )
        return _rule_based_evaluate(concept_list, student_answer)
