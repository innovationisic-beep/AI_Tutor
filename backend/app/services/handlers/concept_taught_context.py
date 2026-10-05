"""
Extract what was actually taught on the VTSE board for concept-question grading.

Questions and answers must align with the current lesson — not generic DB/curriculum text.
"""

from __future__ import annotations

import re
from typing import Any

_WORD_NUMS: dict[str, int] = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}

_STEP_COUNT_Q_RE = re.compile(
    r"(?i)\b(how many|number of|count of|total)\b.{0,40}\b("
    r"step|stage|phase|part|process|cycle"
    r")\w*\b"
)
_THIS_CYCLE_Q_RE = re.compile(r"(?i)\b(this|the)\s+(cycle|process)\b")


def is_step_count_question(question: str) -> bool:
    q = (question or "").strip()
    if not q:
        return False
    if _STEP_COUNT_Q_RE.search(q):
        return True
    if _THIS_CYCLE_Q_RE.search(q) and re.search(r"(?i)\bhow many\b", q):
        return True
    return bool(re.search(r"(?i)\bhow many steps\b", q))


def _entity_label(entity: dict[str, Any]) -> str:
    for key in ("label", "title", "step_display_label", "name"):
        val = str(entity.get(key) or "").strip()
        if val:
            return val
    return ""


def extract_taught_steps_from_timeline(cache: dict[str, Any] | None) -> list[str]:
    if not isinstance(cache, dict):
        return []
    from app.services.handlers.teaching_transcript_service import (
        extract_quizable_items_from_timeline,
    )

    structured = extract_quizable_items_from_timeline(cache)
    if structured.get("steps"):
        return list(structured["steps"])

    steps: list[str] = []
    seen: set[str] = set()

    nodes = cache.get("nodes")
    if isinstance(nodes, list):
        for node in nodes:
            if not isinstance(node, dict):
                continue
            kind = str(node.get("kind") or "").strip().lower()
            label = _entity_label(node)
            if not label:
                continue
            if kind in ("process", "cycle_stage", "step", "") and label not in seen:
                seen.add(label)
                steps.append(label)

    beats = cache.get("beats") or []
    sorted_beats = sorted(
        [b for b in beats if isinstance(b, dict)],
        key=lambda b: int(b.get("index", 0) or 0),
    )
    for beat in sorted_beats:
        for op in beat.get("operations") or []:
            if not isinstance(op, dict) or op.get("op_type") != "add_entity":
                continue
            payload = op.get("payload") or {}
            ent = payload.get("entity") if isinstance(payload, dict) else None
            if not isinstance(ent, dict):
                continue
            kind = str(ent.get("kind") or "").strip().lower()
            label = _entity_label(ent)
            if not label or label in seen:
                continue
            if kind in ("process", "cycle_stage", "step", "", "entity", "primitive"):
                seen.add(label)
                steps.append(label)
    return steps


def build_taught_context(session: Any) -> dict[str, Any]:
    cache = getattr(session, "zone1_timeline_cache", None) or {}
    fc_labels = [
        str(x).strip()
        for x in (getattr(session, "flow_checkpoint_step_labels", None) or [])
        if str(x).strip()
    ]
    timeline_steps = extract_taught_steps_from_timeline(cache)
    steps = fc_labels if fc_labels else timeline_steps

    taught_points = [
        str(p).strip()
        for p in (getattr(session, "taught_points", None) or [])
        if str(p).strip()
    ]
    last_answer = str(getattr(session, "last_answer", None) or "").strip()
    representation = ""
    if isinstance(cache, dict):
        representation = str(
            cache.get("representation_type")
            or (cache.get("layout_metadata") or {}).get("layout_mode")
            or ""
        ).strip().lower()

    return {
        "step_count": len(steps),
        "steps": steps,
        "taught_points": taught_points,
        "representation": representation,
        "lesson_excerpt": last_answer[:3500] if last_answer else "",
    }


def format_taught_context_block(ctx: dict[str, Any]) -> str:
    from app.services.handlers.teaching_transcript_service import (
        _format_hierarchy_taught_block,
    )

    hierarchy_block = _format_hierarchy_taught_block(ctx)
    if hierarchy_block:
        return hierarchy_block

    parts: list[str] = []
    steps = ctx.get("steps") or []
    if steps:
        parts.append(f"Steps shown on the board ({len(steps)}): " + " → ".join(steps))
    elif int(ctx.get("step_count") or 0) > 0:
        parts.append(f"Number of steps taught: {ctx['step_count']}")
    teaching_facts = ctx.get("teaching_facts") or []
    taught_points = ctx.get("taught_points") or []
    if teaching_facts:
        parts.append(
            f"Facts taught ({len(teaching_facts)}): "
            + "\n".join(f"- {f}" for f in teaching_facts[:10])
        )
    elif taught_points:
        parts.append("Key points from this lesson: " + "; ".join(taught_points[:8]))
    excerpt = str(ctx.get("lesson_excerpt") or "").strip()
    if excerpt:
        parts.append("Lesson narration excerpt:\n" + excerpt[:1800])
    return "\n\n".join(parts).strip()


def format_grading_context_block(ctx: dict[str, Any]) -> str:
    """Authoritative lesson block for answer grading — prefers full teaching transcript."""
    from app.services.handlers.teaching_transcript_service import (
        _format_hierarchy_taught_block,
    )

    hierarchy_block = _format_hierarchy_taught_block(ctx)
    if hierarchy_block:
        return hierarchy_block

    parts: list[str] = []
    transcript = str(ctx.get("teaching_transcript") or "").strip()
    if transcript:
        parts.append(
            "FULL LESSON TAUGHT ON THE BOARD (authoritative — grade ONLY against this):\n"
            + transcript[:3500]
        )
    block = format_taught_context_block(ctx)
    if block and block not in "\n\n".join(parts):
        parts.append(block)
    return "\n\n".join(parts).strip()


_LIST_COUNT_Q_RE = re.compile(
    r"(?i)\b(one|two|three|four|five|six|seven|eight|nine|ten|\d+)\s+"
    r"(?:key\s+|main\s+)?"
    r"(step|steps|stage|stages|phase|phases|part|parts|"
    r"characteristic|characteristics|trait|traits|feature|features|"
    r"point|points|idea|ideas|thing|things|item|items"
    r")\b"
)

_BROAD_QUIZ_STEM_RE = re.compile(
    r"(?i)\b("
    r"main ideas?|key ideas?|main points?|key points?|main topic|"
    r"topic of today|today.?s lesson|summary of (?:the )?lesson|"
    r"all (?:the )?(?:characteristics|traits|features|steps|ideas|points)|"
    r"list (?:all|the)|how many (?:characteristics|traits|features|steps|ideas|points)|"
    r"what are the (?:main|key) (?:ideas|points|characteristics|topics?)"
    r")\b"
)


def is_broad_quiz_stem(question: str) -> bool:
    """True when a stem asks for a whole-lesson summary instead of one taught fact."""
    return bool(_BROAD_QUIZ_STEM_RE.search((question or "").strip()))


def effective_taught_item_count(taught_ctx: dict[str, Any]) -> int:
    """Authoritative count of distinct items taught — prefer transcript facts."""
    facts = taught_ctx.get("teaching_facts") or []
    if facts:
        return len(facts)
    steps = taught_ctx.get("steps") or []
    if steps:
        return len(steps)
    points = taught_ctx.get("taught_points") or []
    if points:
        return len(points)
    return int(taught_ctx.get("step_count") or 0)


def asked_quantity_in_question(question: str) -> int | None:
    """Parse 'four steps' / '3 characteristics' style quantities from a stem."""
    m = _LIST_COUNT_Q_RE.search(question or "")
    if not m:
        return None
    token = m.group(1).lower()
    if token.isdigit():
        return int(token)
    return _WORD_NUMS.get(token)


def question_count_matches_taught(question: str, taught_ctx: dict[str, Any]) -> bool:
    """False when a question asserts a list/count that disagrees with the lesson."""
    taught_n = effective_taught_item_count(taught_ctx)
    if taught_n <= 0:
        return True
    asked = asked_quantity_in_question(question)
    if asked is not None and asked != taught_n:
        return False
    if is_step_count_question(question):
        for n in parse_numeric_tokens(question):
            if 0 < n < 20 and n != taught_n:
                return False
    return True


def parse_numeric_tokens(text: str) -> set[int]:
    out: set[int] = set()
    for m in re.findall(r"\b(\d+)\b", text or ""):
        try:
            out.add(int(m))
        except ValueError:
            continue
    for word, val in _WORD_NUMS.items():
        if re.search(rf"\b{word}\b", (text or "").lower()):
            out.add(val)
    return out


def resolve_reference_for_question(
    question: str,
    db_reference: str,
    taught_ctx: dict[str, Any],
) -> str:
    """Build the authoritative reference — lesson content overrides generic DB text."""
    taught_block = format_grading_context_block(taught_ctx)
    db_ref = (db_reference or "").strip()

    if is_step_count_question(question):
        n = effective_taught_item_count(taught_ctx)
        steps = taught_ctx.get("steps") or []
        if n > 0:
            step_line = ", ".join(steps) if steps else ""
            taught_ref = f"{n} step{'s' if n != 1 else ''}"
            if step_line:
                taught_ref += f" ({step_line})"
            if taught_block:
                return (
                    f"Correct answer for THIS lesson: {taught_ref}.\n\n"
                    f"TAUGHT ON THE BOARD:\n{taught_block}"
                )
            return f"Correct answer for THIS lesson: {taught_ref}."

    if taught_block:
        if db_ref:
            return (
                f"{db_ref}\n\n"
                "AUTHORITATIVE — grade ONLY against what was taught in this lesson:\n"
                f"{taught_block}"
            )
        return f"TAUGHT ON THE BOARD:\n{taught_block}"
    return db_ref


def question_asks_about_process_step(question: str) -> bool:
    """True when the question targets a step/order in a process (not a trait list)."""
    q = (question or "").strip()
    if not q or is_step_count_question(q):
        return False
    return bool(
        re.search(
            r"(?i)\b("
            r"first|next|then|after|before|step|stage|phase|"
            r"what happens|which step|order|sequence"
            r")\b",
            q,
        )
    )


_NEGATION_RE = re.compile(
    r"(?i)\b("
    r"no|not|never|n't|cannot|can't|isn't|aren't|wasn't|weren't|"
    r"don't|doesn't|didn't|won't|without|non-?"
    r")\b",
)


def answer_contradicts_lesson(
    student: str,
    question: str,
    reference: str = "",
) -> bool:
    """Detect negated or contradictory answers that must never auto-pass."""
    st = (student or "").strip()
    if not st:
        return False
    st_low = st.lower()
    if not _NEGATION_RE.search(st_low):
        return False

    q_low = (question or "").lower()
    ref_low = (reference or "").lower()
    topic = f"{q_low} {ref_low}"

    if re.search(r"\b(living|alive|life|organism)\b", topic):
        if re.search(
            r"(?:not|non-?)\s*(?:a\s+)?(?:living|alive)|"
            r"cannot\s+(?:be\s+)?(?:considered\s+)?(?:as\s+)?(?:a\s+)?(?:living|alive)|"
            r"isn't\s+(?:a\s+)?(?:living|alive)|"
            r"not\s+considered\s+(?:as\s+)?(?:a\s+)?(?:living|alive)",
            st_low,
        ):
            return True

    if re.match(r"^no\b", st_low) and re.search(
        r"\b(living|alive|plant|animal|characteristic|thing)\b", topic
    ):
        return True

    if re.search(
        r"\b(not|don't|doesn't|do not|does not|cannot|can't)\b.{0,35}\b"
        r"(grow|move|reproduce|breathe|respire|living|alive)\b",
        st_low,
    ):
        return True

    return False


def taught_content_supports_answer(
    question: str,
    student: str,
    taught_ctx: dict[str, Any],
) -> bool:
    """Rule-based check against what was actually taught (before / after LLM eval)."""
    st = (student or "").strip()
    if not st:
        return False

    if answer_contradicts_lesson(st, question):
        return False

    if is_step_count_question(question):
        taught_n = int(taught_ctx.get("step_count") or 0)
        if taught_n > 0 and taught_n in parse_numeric_tokens(st):
            return True
        return False

    if not question_asks_about_process_step(question):
        return False

    steps = [str(s).lower() for s in (taught_ctx.get("steps") or []) if str(s).strip()]
    st_low = st.lower()
    for step in steps:
        step_words = [
            w for w in re.findall(r"[a-z]{4,}", step) if w not in {"step", "then", "from"}
        ]
        if not step_words:
            continue
        hits = sum(1 for w in step_words if w in st_low)
        if hits >= min(2, len(step_words)) or (len(step_words) == 1 and hits == 1):
            return True

    return False


_GRADING_BOILERPLATE = (
    "use the lesson content below",
    "answer key",
    "grade only against",
    "authoritative",
    "taught on the board:",
    "correct answer for this lesson",
    "steps shown on the board",
    "key points from this lesson",
    "lesson narration excerpt",
)


def is_grading_boilerplate(text: str) -> bool:
    low = (text or "").strip().lower()
    if not low:
        return True
    return any(m in low for m in _GRADING_BOILERPLATE)


def _cap_sentences(text: str, max_sentences: int = 2) -> str:
    t = (text or "").strip()
    if not t:
        return t
    parts = re.split(r"(?<=[.!?])\s+", t)
    kept = [p for p in parts if p.strip()][:max_sentences]
    return " ".join(kept).strip()


def clean_db_answer_for_display(db_answer: str) -> str:
    """Return a short, student-safe explanation snippet from the question bank answer."""
    raw = (db_answer or "").strip()
    if not raw or is_grading_boilerplate(raw):
        return ""
    for marker in ("\n\nAUTHORITATIVE", "\n\nTAUGHT ON THE BOARD"):
        idx = raw.find(marker)
        if idx > 0:
            raw = raw[:idx].strip()
    raw = re.sub(r"^Correct answer for THIS lesson:\s*", "", raw, flags=re.I)
    if is_grading_boilerplate(raw):
        return ""
    return _cap_sentences(raw, 2)


def _answer_keywords(text: str) -> set[str]:
    stop = {
        "that", "this", "with", "from", "they", "them", "what", "when", "where",
        "which", "about", "things", "thing", "make", "does", "student", "students",
        "plants", "plant", "during",
    }
    words = {w.lower() for w in re.findall(r"[a-z][a-z'-]{2,}", text or "", re.I)}
    return {w for w in words if w not in stop and len(w) >= 3}


def find_relevant_lesson_snippet(
    student: str,
    taught_ctx: dict[str, Any],
) -> str:
    """Find a taught point or lesson sentence that relates to the student's words."""
    st_kw = _answer_keywords(student)
    st_low = (student or "").lower()

    for pt in taught_ctx.get("taught_points") or []:
        pt_s = str(pt).strip()
        if not pt_s or len(pt_s) < 15:
            continue
        pt_kw = _answer_keywords(pt_s)
        if st_kw & pt_kw:
            snippet = _cap_sentences(pt_s, 2)
            if len(snippet) >= 15:
                return snippet

    for step in taught_ctx.get("steps") or []:
        step_s = str(step).strip()
        if not step_s:
            continue
        step_kw = _answer_keywords(step_s)
        if st_kw & step_kw or step_s.lower() in st_low:
            return step_s

    excerpt = str(taught_ctx.get("lesson_excerpt") or "").strip()
    if excerpt and st_kw:
        for sent in re.split(r"(?<=[.!?])\s+", excerpt):
            sent = sent.strip()
            if not sent:
                continue
            if any(w in sent.lower() for w in st_kw):
                return _cap_sentences(sent, 2)

    return ""


def build_correct_answer_message(
    student: str,
    question: str,
    db_answer: str,
    taught_ctx: dict[str, Any],
    *,
    praise: str,
) -> str:
    """
    Student-facing praise + brief explanation of why their answer is correct.
    Never includes grading or answer-key boilerplate.
    """
    st = (student or "").strip().rstrip(".")
    if not st:
        return praise

    q_low = (question or "").lower()
    clean_ref = clean_db_answer_for_display(db_answer)
    lesson_bit = find_relevant_lesson_snippet(st, taught_ctx)

    if is_step_count_question(question):
        n = int(taught_ctx.get("step_count") or 0)
        if not n:
            nums = parse_numeric_tokens(st)
            n = next(iter(nums), 0) if nums else 0
        steps = taught_ctx.get("steps") or []
        if n and steps:
            preview = ", ".join(steps[:5])
            suffix = "…" if len(steps) > 5 else ""
            return (
                f"{praise} **{st}** is correct — we showed **{n} steps** on the board: "
                f"{preview}{suffix}."
            )
        if n:
            return (
                f"{praise} **{st}** is correct — that matches the **{n} steps** "
                f"we walked through in this lesson."
            )

    if "photosynth" in q_low:
        product = st
        return (
            f"{praise} **{product}** is correct — during photosynthesis, plants use "
            f"sunlight to make {product} (food) that powers their growth and survival."
        )

    if question_expects_single_item(question):
        if lesson_bit:
            return f"{praise} **{st}** is right — {lesson_bit}"
        if clean_ref:
            return f"{praise} **{st}** is correct. {clean_ref}"
        return (
            f"{praise} **{st}** is one of the key ideas we just covered — nice work."
        )

    if re.search(r"\b(what|which)\b.{0,30}\b(make|produce|create|form|get)\b", q_low):
        if clean_ref:
            return f"{praise} **{st}** is correct. {clean_ref}"
        if lesson_bit:
            return f"{praise} **{st}** is right — {lesson_bit}"
        return (
            f"{praise} **{st}** is what we were looking for — "
            f"that is the main product from this process."
        )

    matched_kw = sorted(_answer_keywords(st) & _answer_keywords(clean_ref or db_answer))
    if matched_kw and clean_ref:
        return f"{praise} **{st}** is correct. {clean_ref}"

    if lesson_bit:
        return f"{praise} **{st}** is right — {lesson_bit}"

    if clean_ref:
        return f"{praise} **{st}** is correct. {clean_ref}"

    return f"{praise} **{st}** is the right idea — well done."


def question_expects_single_item(question: str) -> bool:
    q = (question or "").lower()
    partial_re = re.compile(
        r"(?i)\b("
        r"one|a single|single|any one|any|name one|give one|tell one|"
        r"mention one|provide one|state one|list one|an example of"
        r")\b"
    )
    if partial_re.search(q):
        return True
    if re.search(r"\bone\b.{0,40}\b(characteristic|feature|trait|property|example)", q):
        return True
    if re.search(r"\b(characteristic|feature|trait).{0,24}\bone\b", q):
        return True
    return False
