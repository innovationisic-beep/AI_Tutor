"""
Story Hook planner — one bounded DeepSeek call per concept.

Grounding rule: the authored VTSE template is the factual source of truth, the
Story Hook ``body`` is only an analogy/narrative direction, and ``teacher_intent``
only says what to emphasise. The planner may not introduce curriculum facts of
its own.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, List, Optional, Sequence

import httpx

from app.core.config import DEEPSEEK_THINKING_DISABLED, Settings
from app.services.curriculum.concept_vtse_context import (
    format_vtse_template_as_rag_context,
)
from app.services.pedagogy.teacher_voice import (
    TEACHER_SPEAKING_CONTRACT,
    continuity_instructions,
)
from app.services.language.tutor_language_policy import (
    ENGLISH,
    STAGE_STORY_HOOK,
    TutorLanguageMode,
    apply_language_to_system_prompt,
    static_text,
)
from app.services.story_hook.plan_schema import (
    MAX_QUESTIONS,
    MAX_STEPS,
    StoryHookPlan,
    StoryHookPlanError,
    build_fallback_plan,
    parse_plan_json,
    validate_plan_payload,
)

logger = logging.getLogger(__name__)

# The authored outline is already bounded to authored steps/rows; this cap only
# guards against a pathological template blowing up prompt cost.
MAX_OUTLINE_CHARS = 8000

_PLANNER_SYSTEM = f"""You are an expert school teacher planning the opening of a lesson.

You return ONE JSON object and nothing else:
{{"steps": [{{"type": "narration|visual|question|finish", "text": "...", "note": "...", "writes": [{{"source_sentence": "...", "text": "..."}}], "asset_key": "..."}}]}}

STEP TYPES
- narration: you speak to the student. Warm, vivid, concrete.
- visual: show one supplied image. Put a short spoken line in "text" that leads into the image, and the exact asset_key in "asset_key". Optional board writes / note under the image.
- question: ONE short conversational question to the student. The student will reply and you will respond later. Put the question in "text"; leave "note" empty and omit writes (or use []).
- finish: your closing line. If a next focus is given, this step bridges toward it in speech only, without teaching that next part's facts. If no next focus is given, close the story. Optional, and must be last. Do not preview a later check.

SPOKEN TEACHER NARRATION ("text"):
- Rich, natural, conversational teacher speech.
- Storytelling, analogies, examples, transitions, and curiosity-building language are welcome.
- Explains and connects ideas; does NOT need to appear word-for-word on the card.
- Every step needs non-empty "text" (what the teacher says aloud).

BOARD WRITES ("writes") — preferred over a single flat note:
- Zero or more entries. Empty writes: [] is fine (speak-only).
- Only add a write for a spoken sentence with a durable teachable idea.
- source_sentence: copy that sentence from "text" (exact or near-exact).
- text: meaning-preserving short form of THAT sentence (phrase or short sentence — not keywords-only).
- Exact copy of source_sentence is OK when that sentence is already short and board-ready.
- Do NOT paste long conversational spoken lines onto the board.
- Conversational / acknowledgment / transition sentences → no write.
- For question steps, leave writes empty.

LEGACY FLAT "note" (still accepted):
- Concise durable teacher note — used only when writes is omitted/empty.
- May be "" when the teacher only speaks.
- For question steps, leave "note" empty.

EXAMPLE (do not copy literally unless it fits this concept):
- text: "Imagine a leaf with hundreds of tiny gates. The plant can open them when it needs carbon dioxide, but every open gate also gives water a chance to escape."
- writes: [{{"source_sentence": "Imagine a leaf with hundreds of tiny gates.", "text": "Stomata = tiny leaf gates"}}]

HARD RULES
- {MAX_STEPS} steps maximum. Aim for 4 to 8.
- At most {MAX_QUESTIONS} question steps, and usually 0 or 1. Ask only when genuinely useful.
- Questions are curiosity, not assessment: no marks, no right/wrong quizzing, no recall drilling.
- Every supplied asset_key must appear in exactly one visual step. Never invent an asset_key. Never repeat one.
- If no visuals are supplied, use no visual steps.
- FACTUAL SOURCE OF TRUTH is AUTHORITATIVE_CONCEPT_OUTLINE. Preserve its teaching points and keep every statement scientifically correct.
- The SEED is only an analogy or narrative direction, not a fact source. TEACHER_INTENT only tells you what to emphasise.
- Do not invent curriculum facts, numbers or terminology that are absent from the outline.
- This is a hook, not the lesson: build curiosity and intuition, and do not deliver the full explanation or define every term.
- No headings, no markdown, no bullet points, no stage directions, no emoji. Only spoken teacher language in "text"; plain short phrases in writes/note.
- The first narration may use a provided student line. If none is provided, do not invent an acknowledgement.
- Orientation, attention, acknowledgement, and bridges stay in "text" only. Never put them in writes or note.

""" + TEACHER_SPEAKING_CONTRACT


def _visuals_for_prompt(visuals: Sequence[Any]) -> List[dict]:
    out: List[dict] = []
    for visual in visuals:
        get = (
            (lambda name: visual.get(name))
            if isinstance(visual, dict)
            else (lambda name: getattr(visual, name, None))
        )
        asset_key = str(get("asset_key") or "").strip().lower()
        if not asset_key:
            continue
        out.append(
            {
                "asset_key": asset_key,
                "description": str(get("description") or "").strip(),
                "teaching_purpose": str(get("teaching_purpose") or "").strip(),
            }
        )
    return out


def build_planner_prompt(
    *,
    concept_label: str,
    seed: str,
    title: str,
    teacher_intent: str,
    outline: str,
    visuals: Sequence[Any],
    retry_reason: Optional[str] = None,
    continuity: Optional[dict] = None,
) -> str:
    """Compose the planner user message. Only pedagogical visual metadata is exposed."""
    prompt_visuals = _visuals_for_prompt(visuals)
    lines: List[str] = [f"CONCEPT: {concept_label or 'this concept'}"]
    if title:
        lines.append(f"STORY_HOOK_TITLE: {title}")
    lines.append(f"SEED (analogy / narrative direction only): {seed or '(none)'}")
    if teacher_intent:
        lines.append(f"TEACHER_INTENT (what to emphasise): {teacher_intent}")

    if prompt_visuals:
        lines.append(
            f"VISUALS — use each of these {len(prompt_visuals)} exactly once, "
            "in whatever order teaches best:"
        )
        lines.append(json.dumps(prompt_visuals, ensure_ascii=False, indent=2))
    else:
        lines.append("VISUALS: none supplied — do not use visual steps.")

    lines.append("")
    lines.append("AUTHORITATIVE_CONCEPT_OUTLINE (factual source of truth):")
    lines.append(outline.strip() if outline.strip() else "(none authored)")

    if not outline.strip():
        lines.append("")
        lines.append(
            "No outline was authored, so stay close to the seed and keep claims "
            "general and safe. Do not invent specific curriculum facts."
        )

    continuity_block = continuity_instructions(continuity)
    if continuity_block:
        lines.append("")
        lines.append(continuity_block)

    if retry_reason:
        lines.append("")
        lines.append(
            "Your previous answer was rejected: "
            f"{retry_reason}. Return corrected JSON only."
        )

    lines.append("")
    lines.append("Return the JSON object now.")
    return "\n".join(lines)


def build_outline(concept: Any, *, concept_label: str) -> str:
    """
    Authoritative concept context from the authored VTSE template.

    ``story_hook=None`` on purpose: the seed is a separate planner input and must
    not be echoed back inside the factual source block.
    """
    outline = format_vtse_template_as_rag_context(
        getattr(concept, "vtse_template", None) if concept is not None else None,
        concept_label=concept_label,
        story_hook=None,
    )
    if len(outline) <= MAX_OUTLINE_CHARS:
        return outline
    # Truncate on a step boundary so no teaching point is left half-stated.
    head = outline[:MAX_OUTLINE_CHARS]
    cut = head.rfind("\n")
    return head[:cut] if cut > 0 else head


async def plan_story_hook(
    *,
    concept: Any,
    hook: Any,
    concept_label: str,
    language_mode: TutorLanguageMode = ENGLISH,
    continuity: Optional[dict] = None,
) -> StoryHookPlan:
    """
    Build a validated plan, with one controlled retry then a seed-only fallback.

    Never raises: the stage must always have something to teach.
    """
    seed = str(_hook_field(hook, "body") or "").strip()
    title = str(_hook_field(hook, "title") or "").strip()
    teacher_intent = str(_hook_field(hook, "teacher_intent") or "").strip()
    visuals = list(_hook_field(hook, "visuals") or [])
    allowed_keys = [v["asset_key"] for v in _visuals_for_prompt(visuals)]
    outline = build_outline(concept, concept_label=concept_label)

    if not outline:
        logger.warning(
            "[STORY_HOOK] no_vtse_outline concept=%s — planner limited to seed",
            concept_label,
        )

    system = apply_language_to_system_prompt(
        _PLANNER_SYSTEM, stage=STAGE_STORY_HOOK, mode=language_mode
    )
    retry_reason: Optional[str] = None

    for attempt in range(2):
        prompt = build_planner_prompt(
            concept_label=concept_label,
            seed=seed,
            title=title,
            teacher_intent=teacher_intent,
            outline=outline,
            visuals=visuals,
            retry_reason=retry_reason,
            continuity=continuity,
        )
        raw = await llm_call(prompt, system_content=system, temperature=0.6)
        if not raw:
            retry_reason = "no response"
            logger.warning("[STORY_HOOK] planner_no_response attempt=%s", attempt)
            continue
        try:
            payload = parse_plan_json(raw)
            plan = validate_plan_payload(
                payload,
                allowed_asset_keys=allowed_keys,
                language=language_mode,
            )
        except StoryHookPlanError as exc:
            retry_reason = str(exc)
            logger.warning(
                "[STORY_HOOK] planner_invalid attempt=%s reason=%s", attempt, exc
            )
            continue
        logger.info(
            "[STORY_HOOK] planned concept=%s steps=%s questions=%s visuals=%s lang=%s",
            concept_label,
            len(plan.steps),
            plan.question_count,
            len(allowed_keys),
            language_mode,
        )
        return plan

    logger.warning(
        "[STORY_HOOK] planner_fallback concept=%s reason=%s", concept_label, retry_reason
    )
    return build_fallback_plan(
        seed=seed,
        title=title,
        visuals=visuals,
        language=language_mode,
        visual_caption_fallback=static_text(
            "story_hook_visual_caption",
            language_mode,
            english="Take a look at this.",
        ),
    )


_FOLLOW_UP_SYSTEM = """You are an expert school teacher mid-way through the opening of a lesson.

The student just answered your conversational question. Reply in 1-3 spoken
sentences: acknowledge what they said, gently correct only a clear factual
mistake, and lead back into the story.

RULES
- This is not a test. Never grade, score, or say "correct"/"incorrect".
- Accept partial or uncertain answers warmly. "I don't know" is fine.
- Stay scientifically accurate and consistent with the outline you were given.
- After you acknowledge the answer, return to the story that is already underway. Do not start a new lesson and do not restate a closing handoff.
- No headings, no markdown, no bullet points, no emoji. Only spoken teacher language.
- Return plain text only, no JSON.

""" + TEACHER_SPEAKING_CONTRACT


async def respond_to_story_hook_answer(
    *,
    question: str,
    student_answer: str,
    concept_label: str,
    outline: str,
    language_mode: TutorLanguageMode = ENGLISH,
) -> str:
    """
    Reply to a student's Story Hook answer.

    A fresh call each time — replies are never pre-generated. Returns "" when the
    LLM is unavailable so the caller can use a neutral template.
    """
    system = apply_language_to_system_prompt(
        _FOLLOW_UP_SYSTEM, stage=STAGE_STORY_HOOK, mode=language_mode
    )
    prompt = "\n".join(
        [
            f"CONCEPT: {concept_label or 'this concept'}",
            f"YOUR QUESTION: {question}",
            f"STUDENT ANSWER: {student_answer}",
            "",
            "AUTHORITATIVE_CONCEPT_OUTLINE (stay consistent with this):",
            outline.strip() or "(none authored)",
            "",
            "Reply now.",
        ]
    )
    raw = await llm_call(prompt, system_content=system, temperature=0.6)
    return (raw or "").strip()


async def llm_call(
    user_content: str,
    *,
    system_content: str = "You are an expert tutor.",
    temperature: float = 0.4,
    timeout: float = 60.0,
) -> Optional[str]:
    """Minimal DeepSeek chat completion — mirrors SessionService._deepseek_chat_completion."""
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        return None
    payload = {
        "model": Settings.DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_content},
        ],
        "temperature": temperature,
        "thinking": DEEPSEEK_THINKING_DISABLED,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=timeout, http2=False) as client:
        try:
            response = await client.post(
                Settings.DEEPSEEK_API_URL, headers=headers, json=payload
            )
        except Exception:  # noqa: BLE001
            return None
    if response.status_code != 200:
        return None
    try:
        return str(response.json()["choices"][0]["message"]["content"])
    except Exception:  # noqa: BLE001
        return None


def _hook_field(hook: Any, name: str) -> Any:
    if hook is None:
        return None
    if isinstance(hook, dict):
        return hook.get(name)
    return getattr(hook, name, None)
