"""Expand authored VTSE outline points via DeepSeek into teacher-style prose.

Authored curriculum points are content outlines only — never teach them verbatim.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.cir.limits import ROW_DETAIL_MAX, ROW_NARRATION_MAX
from app.services.curriculum.concept_vtse_template import ConceptVtseTemplate
from app.services.pedagogy.teacher_voice import (
    TEACHER_SPEAKING_CONTRACT,
    continuity_instructions,
)
from app.vtse.authoring.process_step_schema import (
    ProcessLLMDraftV1,
    ProcessStepSemanticV1,
)

logger = logging.getLogger(__name__)

_SYSTEM = """You output ONLY valid JSON. No markdown fences. No commentary."""

# Board stays revision material. Speech teaches that material and must not read it.
_BOARD_SPEECH_RULES = """
BOARD VS SPEECH
- The board is the revision resource. explanation_text, left_detail, right_detail, left_card, right_card, and any detail shown on the card stay exam-useful. Write several useful sentences when the authored point supports that depth. Include the mechanism, why it matters, and the useful explanation. Do not shorten the board to separate it from speech. Do not greet, orient, or bridge on the board.
- Speech (narration_text, pair_narration, opening_narration) is richer than the board. Orient the student to what is visible, define a hard word in plain language the first time the outline needs it, explain why and how, name a distinction a student could confuse, and use a simple example only when the outline supports it. Then connect the previous item, this item, and the next item.
- Do not read the board aloud. Do not make speech a synonym swap of the same sentence.
- Shared names and exam keywords belong in both layers. A longer explanation may repeat a term or a short phrase while it teaches around that phrase.
- Develop the authored point. Do not add a new outline point or a second curriculum.
- Rhetorical questions are allowed. Do not ask the student to answer.
- Bridges and attention lines are spoken only.
""".strip()

_STOPWORDS = frozenset(
    """
    a an the of to from and or in on for with that this it is are was be by its
    their they we you after much into then than
    """.split()
)


def _continuity_block(continuity: dict[str, Any] | None) -> str:
    text = continuity_instructions(continuity)
    return f"\n{text}\n" if text else ""


async def _ask_expand(instructions: str) -> str | None:
    """Direct DeepSeek call. The teaching-essay wrapper is not used."""
    from app.services.story_hook.planner import llm_call

    question = (
        f"{_SYSTEM}\n{TEACHER_SPEAKING_CONTRACT}\n{instructions}\nRespond with JSON only."
    )
    return await llm_call(
        question,
        system_content=f"{_SYSTEM}\n\n{TEACHER_SPEAKING_CONTRACT}",
        temperature=0.4,
        timeout=30.0,
    )


def _extract_json_object(text: str) -> dict[str, Any] | None:
    t = (text or "").strip()
    if not t:
        return None
    try:
        obj = json.loads(t)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass
    fenced = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", t)
    if fenced:
        try:
            obj = json.loads(fenced.group(1))
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            return None
    start = t.find("{")
    end = t.rfind("}")
    if start >= 0 and end > start:
        try:
            obj = json.loads(t[start : end + 1])
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def _clip(s: str, n: int) -> str:
    return (s or "").strip()[:n]


async def expand_authored_vtse_template(
    *,
    rag_service: Any,
    template: ConceptVtseTemplate,
    topic_name: str,
    concept: str,
    student_profile: dict[str, Any] | None = None,
    continuity: dict[str, Any] | None = None,
) -> tuple[
    dict[str, Any] | None,
    ProcessLLMDraftV1 | None,
    list[dict[str, Any]] | None,
    dict[str, Any],
]:
    """
    Expand authored outline → LLM teacher prose.

    Returns (comparison_llm_json, process_llm_draft, trait_steps, debug).
    On failure returns (None, None, None, debug) so caller can fall back.
    """
    strategy = template.strategy_id
    debug: dict[str, Any] = {
        "authored_expand": True,
        "strategy_id": strategy,
    }
    try:
        if strategy == "comparison_contrast":
            expanded, dbg = await _expand_comparison(
                rag_service=rag_service,
                template=template,
                topic_name=topic_name,
                concept=concept,
                student_profile=student_profile,
                continuity=continuity,
            )
            debug.update(dbg)
            return expanded, None, None, debug

        if strategy in ("cycle_process", "linear_process"):
            draft, dbg = await _expand_process(
                rag_service=rag_service,
                template=template,
                topic_name=topic_name,
                concept=concept,
                student_profile=student_profile,
                cycle=strategy == "cycle_process",
                continuity=continuity,
            )
            debug.update(dbg)
            return None, draft, None, debug

        steps, dbg = await _expand_hierarchy(
            rag_service=rag_service,
            template=template,
            topic_name=topic_name,
            concept=concept,
            student_profile=student_profile,
            continuity=continuity,
        )
        debug.update(dbg)
        return None, None, steps, debug
    except Exception as exc:  # noqa: BLE001
        logger.warning("[VTSE_AUTHOR] authored_expand_failed detail=%s", exc)
        debug["expand_error"] = str(exc)[:200]
        return None, None, None, debug


async def _expand_hierarchy(
    *,
    rag_service: Any,
    template: ConceptVtseTemplate,
    topic_name: str,
    concept: str,
    student_profile: dict[str, Any] | None,
    continuity: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]] | None, dict[str, Any]]:
    outline_steps = list((template.payload or {}).get("steps") or [])
    debug: dict[str, Any] = {"mode": "hierarchy"}
    if len(outline_steps) < 3:
        debug["expand_error"] = "too_few_steps"
        return None, debug

    bullets = []
    for i, step in enumerate(outline_steps, start=1):
        label = _clip(str(step.get("label") or ""), 120)
        summary = _clip(str(step.get("summary") or label), 400)
        bullets.append(f"{i}. Label: {label}\n   Outline fact: {summary}")

    n = len(outline_steps)
    _ = student_profile
    previous_error: str | None = None
    for attempt in range(2):
        instructions = f"""
You are an expert teacher. Expand an AUTHOR-PROVIDED outline into whiteboard teaching prose.

Topic: {topic_name}
Concept: {concept}
{_continuity_block(continuity)}
AUTHOR OUTLINE (exact points to teach — same count and order):
{chr(10).join(bullets)}

Return JSON:
{{
  "opening_narration": "spoken opening for the parent idea, or empty string",
  "traits": [
    {{
      "concise_node_label": "2-4 word identity label",
      "explanation_text": "several useful sentences of exam study notes for this point, including the mechanism when the outline supports it",
      "narration_text": "spoken teaching of that board note"
    }}
  ]
}}

{_BOARD_SPEECH_RULES}

CRITICAL RULES:
- Return EXACTLY {n} traits, one per outline point, in the SAME order.
- concise_node_label should reflect the outline label (short identity only).
- NEVER paste the outline fact sentence verbatim into explanation_text or narration_text.
- narration_text is spoken only. explanation_text is the board note. Do not copy narration into explanation_text.
- narration_text says how the child belongs to the parent, clarifies a hard word, then points toward the next outline point.
- For a flat set of traits, narration_text says why the trait matters and how it fits with the previous one.
- The last narration can synthesize how the children fit together, then closes toward the next focus when one is given, without teaching that next part.
- The first trait's narration opens from the previous focus when one is given.
- opening_narration is spoken only. It is not an extra trait.
- Do NOT invent extra characteristics beyond these {n} points.
- Do NOT drop or reorder points.
{_retry_note(previous_error)}
"""
        raw = await _ask_expand(instructions)
        debug["llm_transport"] = "direct"
        debug["raw_preview"] = _clip(str(raw or ""), 400)
        parsed = _extract_json_object(str(raw or ""))
        if not isinstance(parsed, dict):
            debug["expand_error"] = "json_parse_failed"
            return None, debug

        opening = _clip(str(parsed.get("opening_narration") or ""), ROW_NARRATION_MAX)
        if opening:
            debug["opening_narration"] = opening

        traits_in = parsed.get("traits")
        if not isinstance(traits_in, list) or len(traits_in) < n:
            debug["expand_error"] = "trait_count_mismatch"
            return None, debug

        out: list[dict[str, Any]] = []
        speech_error: str | None = None
        for i, step in enumerate(outline_steps):
            item = traits_in[i] if i < len(traits_in) and isinstance(traits_in[i], dict) else {}
            label = _clip(
                str(item.get("concise_node_label") or step.get("label") or f"Point {i + 1}"),
                80,
            )
            explanation = _clip(str(item.get("explanation_text") or ""), 800)
            narration = _clip(str(item.get("narration_text") or ""), ROW_NARRATION_MAX)
            outline_fact = _clip(str(step.get("summary") or step.get("label") or ""), 400)
            if not explanation or _too_similar(explanation, outline_fact):
                debug["expand_error"] = f"verbatim_or_empty_explanation:{i}"
                return None, debug
            board_error = narration_board_error(narration, explanation, outline=outline_fact)
            if board_error:
                speech_error = f"{board_error}:{i}"
                break
            out.append(
                {
                    "title": label,
                    "annotation": explanation,
                    "narration": narration,
                }
            )
        if speech_error:
            debug["expand_error"] = speech_error
            if attempt == 0:
                previous_error = speech_error
                continue
            return None, debug

        debug["expanded_count"] = len(out)
        debug["expand_ok"] = True
        return out, debug
    return None, debug


async def _expand_comparison(
    *,
    rag_service: Any,
    template: ConceptVtseTemplate,
    topic_name: str,
    concept: str,
    student_profile: dict[str, Any] | None,
    continuity: dict[str, Any] | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    payload = template.payload or {}
    left_label = _clip(str(payload.get("left_label") or "Left"), 80)
    right_label = _clip(str(payload.get("right_label") or "Right"), 80)
    rows = list(payload.get("rows") or [])
    debug: dict[str, Any] = {"mode": "comparison"}
    if len(rows) < 2:
        debug["expand_error"] = "too_few_rows"
        return None, debug

    bullets = []
    for i, row in enumerate(rows, start=1):
        dim = _clip(str(row.get("dimension") or f"Point {i}"), 80)
        left = _clip(str(row.get("left_detail") or row.get("left") or ""), 400)
        right = _clip(str(row.get("right_detail") or row.get("right") or ""), 400)
        bullets.append(
            f"{i}. Dimension: {dim}\n   {left_label}: {left}\n   {right_label}: {right}"
        )

    n = len(rows)
    _ = student_profile
    previous_error: str | None = None
    for attempt in range(2):
        instructions = f"""
You are an expert teacher. Expand an AUTHOR-PROVIDED comparison outline into teaching prose.

Topic: {topic_name}
Concept: {concept}
Left: {left_label}
Right: {right_label}
{_continuity_block(continuity)}
AUTHOR OUTLINE (exact row pairs — same count and order):
{chr(10).join(bullets)}

Return JSON:
{{
  "opening_narration": "spoken opening for the comparison, or empty string",
  "left_label": "{left_label}",
  "right_label": "{right_label}",
  "rows": [
    {{
      "dimension": "short dimension name",
      "left_title": "2-4 word title",
      "right_title": "2-4 word title",
      "left_detail": "several useful sentences of exam study notes for the left side, including the mechanism when the outline supports it",
      "right_detail": "several useful sentences of exam study notes for the right side, including the mechanism when the outline supports it",
      "left_card": "the same rich study note shown on the left card",
      "right_card": "the same rich study note shown on the right card",
      "pair_narration": "spoken teaching of this row, deeper than either card"
    }}
  ]
}}

{_BOARD_SPEECH_RULES}

CRITICAL RULES:
- Return EXACTLY {n} rows in the SAME order as the outline.
- Keep left_label and right_label exactly as given.
- NEVER paste outline sentences verbatim into details or pair_narration.
- pair_narration is spoken only. left_card and right_card stay rich board study notes. Do not copy pair_narration into cards or details.
- Each pair_narration introduces the dimension, teaches both sides, contrasts the right side with the left, explains why the distinction matters, then bridges to the next row.
- When another row follows, pair_narration ends by moving toward that next row.
- The first row opens from the previous focus when one is given.
- The last row closes toward the next focus when one is given, without teaching that next part.
- opening_narration orients the student to the two visible columns, then points at the first difference. It is spoken only. It is not an extra row.
{_retry_note(previous_error)}
"""
        raw = await _ask_expand(instructions)
        debug["llm_transport"] = "direct"
        debug["raw_preview"] = _clip(str(raw or ""), 400)
        parsed = _extract_json_object(str(raw or ""))
        if not isinstance(parsed, dict):
            debug["expand_error"] = "json_parse_failed"
            return None, debug

        rows_out = parsed.get("rows")
        if not isinstance(rows_out, list) or len(rows_out) < n:
            debug["expand_error"] = "row_count_mismatch"
            return None, debug

        speech_error: str | None = None
        kept_rows = rows_out[:n]
        for i, row in enumerate(kept_rows):
            if not isinstance(row, dict):
                speech_error = f"empty_narration:{i}"
                break
            pair = _clip(str(row.get("pair_narration") or ""), ROW_NARRATION_MAX)
            left_board = _clip(
                str(row.get("left_card") or row.get("left_detail") or ""),
                ROW_DETAIL_MAX,
            )
            right_board = _clip(
                str(row.get("right_card") or row.get("right_detail") or ""),
                ROW_DETAIL_MAX,
            )
            board_error = narration_board_error(pair, left_board, right_board)
            if board_error:
                speech_error = f"{board_error}:{i}"
                break
        if speech_error:
            debug["expand_error"] = speech_error
            if attempt == 0:
                previous_error = speech_error
                continue
            return None, debug

        opening = _clip(str(parsed.get("opening_narration") or ""), ROW_NARRATION_MAX)
        if opening:
            debug["opening_narration"] = opening
        result = {
            "left_label": left_label,
            "right_label": right_label,
            "opening_narration": opening,
            "rows": kept_rows,
        }
        debug["expanded_count"] = n
        debug["expand_ok"] = True
        return result, debug
    return None, debug


async def _expand_process(
    *,
    rag_service: Any,
    template: ConceptVtseTemplate,
    topic_name: str,
    concept: str,
    student_profile: dict[str, Any] | None,
    cycle: bool,
    continuity: dict[str, Any] | None = None,
) -> tuple[ProcessLLMDraftV1 | None, dict[str, Any]]:
    outline_steps = list((template.payload or {}).get("steps") or [])
    debug: dict[str, Any] = {"mode": "cycle" if cycle else "linear"}
    if len(outline_steps) < 3:
        debug["expand_error"] = "too_few_steps"
        return None, debug

    bullets = []
    for i, step in enumerate(outline_steps, start=1):
        label = _clip(str(step.get("label") or f"Step {i}"), 120)
        summary = _clip(str(step.get("summary") or label), 400)
        bullets.append(f"{i}. Label: {label}\n   Outline fact: {summary}")

    n = len(outline_steps)
    kind = "cycle (looping stages)" if cycle else "linear process"
    cycle_rule = (
        "- The last narration must say why the loop returns to the first stage."
        if cycle
        else "- Each narration says why this step leads to the next."
    )
    _ = student_profile
    previous_error: str | None = None
    for attempt in range(2):
        instructions = f"""
You are an expert teacher. Expand an AUTHOR-PROVIDED {kind} outline into teaching prose.

Topic: {topic_name}
Concept: {concept}
{_continuity_block(continuity)}
AUTHOR OUTLINE (exact stages — same count and order):
{chr(10).join(bullets)}

Return JSON:
{{
  "opening_narration": "spoken opening for the first stage, or empty string",
  "topic": "{_clip(concept or topic_name, 80)}",
  "steps": [
    {{
      "step_number": 1,
      "process_title": "short stage title",
      "concise_node_label": "2-4 word node label",
      "explanation_text": "several useful sentences of exam study notes for this stage, including the mechanism when the outline supports it",
      "narration_text": "spoken teaching of that board note",
      "pedagogical_role": "explain"
    }}
  ]
}}

{_BOARD_SPEECH_RULES}

CRITICAL RULES:
- Return EXACTLY {n} steps in the SAME order.
- NEVER paste outline facts verbatim into explanation_text or narration_text.
- narration_text is spoken only. explanation_text is the board note. Do not copy narration into explanation_text.
- Each narration explains the mechanism and why this step follows the previous outline step and leads to the next.
- The first step opens from the previous focus when one is given.
- The last step closes toward the next focus when one is given, without teaching that next part.
{cycle_rule}
- opening_narration is spoken only. It is not an extra step.
{_retry_note(previous_error)}
"""
        raw = await _ask_expand(instructions)
        debug["llm_transport"] = "direct"
        debug["raw_preview"] = _clip(str(raw or ""), 400)
        parsed = _extract_json_object(str(raw or ""))
        if not isinstance(parsed, dict):
            debug["expand_error"] = "json_parse_failed"
            return None, debug

        steps_in = parsed.get("steps")
        if not isinstance(steps_in, list) or len(steps_in) < n:
            debug["expand_error"] = "step_count_mismatch"
            return None, debug

        opening = _clip(str(parsed.get("opening_narration") or ""), ROW_NARRATION_MAX)
        process_steps: list[ProcessStepSemanticV1] = []
        speech_error: str | None = None
        for i, outline in enumerate(outline_steps):
            item = steps_in[i] if i < len(steps_in) and isinstance(steps_in[i], dict) else {}
            label = _clip(
                str(
                    item.get("concise_node_label")
                    or item.get("process_title")
                    or outline.get("label")
                    or f"Step {i + 1}"
                ),
                80,
            )
            explanation = _clip(str(item.get("explanation_text") or ""), 800)
            narration = _clip(str(item.get("narration_text") or ""), ROW_NARRATION_MAX)
            outline_fact = _clip(str(outline.get("summary") or outline.get("label") or ""), 400)
            if not explanation or _too_similar(explanation, outline_fact):
                debug["expand_error"] = f"verbatim_or_empty_explanation:{i}"
                return None, debug
            board_error = narration_board_error(narration, explanation, outline=outline_fact)
            if board_error:
                speech_error = f"{board_error}:{i}"
                break
            if i == 0 and opening:
                narration = prepend_spoken_opening(narration, opening)
            process_steps.append(
                ProcessStepSemanticV1(
                    step_number=i + 1,
                    process_title=_clip(concept or topic_name, 120) or "Process",
                    concise_node_label=label,
                    explanation_text=explanation,
                    narration_text=narration,
                    pedagogical_role="explain",
                )
            )
        if speech_error:
            debug["expand_error"] = speech_error
            if attempt == 0:
                previous_error = speech_error
                continue
            return None, debug

        if opening:
            debug["opening_narration"] = opening
        draft = ProcessLLMDraftV1(
            topic=_clip(concept or topic_name, 120) or "Process",
            steps=tuple(process_steps),
            semantic_process_confidence=1.0,
            narration_richness_level="authored_expanded",
        )
        debug["expanded_count"] = len(process_steps)
        debug["expand_ok"] = True
        return draft, debug
    return None, debug


def _normalize_speech(text: str) -> str:
    cleaned = re.sub(r"[^a-z0-9'\s]", " ", (text or "").lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def _content_tokens(text: str) -> set[str]:
    return {
        word
        for word in re.findall(r"[a-z0-9']+", _normalize_speech(text))
        if word not in _STOPWORDS and len(word) > 2
    }


def speech_reads_board(speech: str, board: str) -> bool:
    """Reject a read-aloud or a same-length synonym swap. A longer teaching may share terms."""
    spoken = _normalize_speech(speech)
    written = _normalize_speech(board)
    if not spoken or not written:
        return False
    if spoken == written:
        return True
    length_ratio = len(spoken) / max(len(written), 1)
    board_tokens = _content_tokens(board)
    speech_tokens = _content_tokens(speech)
    overlap = (
        len(board_tokens & speech_tokens) / len(board_tokens) if board_tokens else 0.0
    )
    added_tokens = len(speech_tokens - board_tokens)
    substantially_longer = length_ratio > 1.6 and added_tokens >= 4
    sentences = [
        part.strip()
        for part in re.split(r"(?<=[.!?])\s+", (board or "").strip())
        if part.strip()
    ] or [board]
    for sentence in sentences:
        clause = _normalize_speech(sentence)
        if len(clause) >= 12 and clause in spoken and not substantially_longer:
            return True
    return bool(board_tokens) and overlap >= 0.6 and 0.7 <= length_ratio <= 1.45


def _too_similar(a: str, b: str) -> bool:
    """True when expanded text is basically the outline copied."""
    aa = re.sub(r"\s+", " ", (a or "").strip().lower())
    bb = re.sub(r"\s+", " ", (b or "").strip().lower())
    if not aa or not bb:
        return False
    if aa == bb:
        return True
    if len(bb) >= 12 and bb in aa and len(aa) < len(bb) * 1.6:
        return True
    return False


def narration_board_error(narration: str, *boards: str, outline: str = "") -> str | None:
    """Reject empty speech and speech that reads the board. Never returns board text."""
    if not (narration or "").strip():
        return "empty_narration"
    if outline and _too_similar(narration, outline):
        return "speech_reads_board"
    for board in boards:
        if (board or "").strip() and speech_reads_board(narration, board):
            return "speech_reads_board"
    return None


def prepend_spoken_opening(
    narration: str,
    opening: str,
    *,
    limit: int = ROW_NARRATION_MAX,
) -> str:
    spoken = (narration or "").strip()
    lead = (opening or "").strip()
    if not lead or lead.lower() in spoken.lower():
        return spoken[:limit]
    return f"{lead} {spoken}".strip()[:limit]


def _retry_note(previous_error: str | None) -> str:
    if not previous_error:
        return ""
    return (
        f"\nprevious_error: {previous_error}\n"
        "Rewrite the speech so it teaches beyond the board. "
        "Do not copy the board text or swap a few synonyms.\n"
    )
