"""
Teaching-transcript sourcing for concept-check and cluster-quiz question generation.

Loads VTSE board-turn prose for the current concept/cluster, splits it into
quizable facts, and assigns one focus fact per question slot so the LLM cannot
drift into broad "main ideas / characteristics" stems or invent counts.
"""

from __future__ import annotations

import random
import re
from typing import Any, Literal

from beanie.odm.fields import PydanticObjectId

from app.repositories.board_turn_repository import BoardTurnRepository
from app.services.handlers.cluster_utils import (
    derive_current_cluster_index,
    resolve_clusters,
)
from app.services.handlers.concept_taught_context import (
    _answer_keywords,
    build_taught_context,
    format_taught_context_block,
    is_broad_quiz_stem,
    question_count_matches_taught,
)

QuestionScope = Literal["concept", "cluster", "zone"]

ZONE1_TEACHING_ZONE = 1

_ZONE0_RESPONSE_TYPES = frozenset({
    "zone0_anchor",
    "zone0_curiosity",
    "zone0_prereq",
})

_META_INSTRUCTION_RE = re.compile(
    r"(?i)("
    r"follow along on the board|follow along.{0,30}whiteboard|"
    r"answer the question in chat|answer in chat|question in chat|"
    r"warm[- ]?up questions?|purpose of warm[- ]?up|"
    r"get your mind curious|not a test|just a way to get your mind|"
    r"let's explore .{0,40} together|when you.?re ready|"
    r"open teachback|concept check|cluster quiz|"
    r"use the buttons|i still have a confusion|"
    r"before we dive|what do you already think|"
    r"zone 0|warm[- ]?up|"
    r"captures the full idea|full idea we talked|talked about today|"
    r"nailed the big idea|big idea right from|right from the beginning|"
    r"what we (?:talked|covered|learned) (?:about )?today|"
    r"what the lesson (?:means?|says)|when (?:the lesson|it) says|"
    r"what does the lesson mean|what does the teacher mean|"
    r"main topic of today|topic of today.?s lesson|"
    r"good thinking|exactly right|great job|nice work|well done|"
    r"that.?s correct|you.?ve got it|spot on"
    r")"
)

_META_QUESTION_RE = re.compile(
    r"(?i)\b("
    r"what does the lesson mean|what did the lesson mean|"
    r"what does the teacher mean|what did the teacher mean|"
    r"teacher mean when|when (?:the )?teacher says|"
    r"what does the lesson say|when the lesson says|when it says|"
    r"main topic of|topic of today|what is the (?:main )?topic|"
    r"purpose of warm[- ]?up|follow along|answer in chat"
    r")\b"
)

_MD_RE = re.compile(r"[*_#`]+")
_BOILERPLATE_STARTS = (
    "before we dive",
    "what do you already think",
    "great question",
    "let's explore",
    "let us explore",
    "open teachback",
    "nice work",
    "well done",
    "any questions",
    "do you have questions",
)

_MCQ_ARCHETYPES = ("which_true", "what_means", "why_matters")
_FILL_ARCHETYPES = ("term_blank", "complete_fact")
_DESC_ARCHETYPES = ("explain_own_words", "what_happens", "why_important")

_ARCHETYPE_PROMPTS: dict[str, str] = {
    "which_true": (
        "Write a multiple-choice question where exactly one option states the "
        "focus fact correctly and the others are clearly false."
    ),
    "what_means": (
        "Write a multiple-choice question that checks what the focus fact means "
        "in simple student language."
    ),
    "why_matters": (
        "Write a multiple-choice question about why the focus fact matters, "
        "with one clearly correct option grounded in the focus fact."
    ),
    "term_blank": (
        "Write a fill-in-the-blank question with exactly one _____ blank; "
        "the answer is a short KEY subject term taken directly from the focus fact "
        "(not a pronoun or filler like themselves/things/own)."
    ),
    "complete_fact": (
        "Write a fill-in-the-blank sentence that completes the focus fact; "
        "include _____ for the missing KEY subject word(s); answer is 1-4 content words "
        "(never pronouns/fillers)."
    ),
    "explain_own_words": (
        "Write a short-answer question asking the student to explain the focus "
        "fact in their own words (1-2 sentences)."
    ),
    "what_happens": (
        "Write a short-answer question about what happens according to the "
        "focus fact."
    ),
    "why_important": (
        "Write a short-answer question about why the focus fact is important "
        "according to the lesson."
    ),
}


def fact_key(text: str) -> str:
    t = re.sub(r"\s+", " ", (text or "").strip().lower())
    return t[:160]


def _strip_markdown(text: str) -> str:
    t = _MD_RE.sub("", text or "")
    t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", t)
    return re.sub(r"\s+", " ", t).strip()


def is_meta_instruction_text(text: str) -> bool:
    """True for Zone 0 / UI / tutor-process lines — not quizable subject content."""
    low = (text or "").strip().lower()
    if not low:
        return True
    if _META_INSTRUCTION_RE.search(low):
        return True
    if re.search(
        r"(?i)follow along.{0,50}(board|whiteboard).{0,50}(chat|answer)",
        low,
    ):
        return True
    if re.search(r"(?i)\bwarm[- ]?up\b", low) and re.search(
        r"(?i)\b(purpose|questions?|not a test|curious|mind)\b", low
    ):
        return True
    if re.search(r"(?i)\bcaptures?\b.{0,30}\b(full )?idea\b", low):
        return True
    if re.search(r"(?i)\b(talked|covered|learned)\b.{0,20}\btoday\b", low):
        return True
    if re.search(r"(?i)\bnailed\b.{0,30}\b(big )?idea\b", low):
        return True
    if re.search(r"(?i)\bright from the beginning\b", low):
        return True
    return False


def is_meta_quiz_question(question: str) -> bool:
    """True when a generated quiz stem is about lesson mechanics, not subject content."""
    q = (question or "").strip()
    if not q:
        return True
    if is_meta_instruction_text(q):
        return True
    return bool(_META_QUESTION_RE.search(q))


def _is_boilerplate_sentence(sent: str) -> bool:
    low = sent.lower().strip()
    if not low or len(low) < 18:
        return True
    if is_meta_instruction_text(low):
        return True
    if low.endswith("?"):
        return True
    if any(low.startswith(p) for p in _BOILERPLATE_STARTS):
        return True
    if re.search(r"(?i)\b(click|open the whiteboard|type your answer)\b", low):
        return True
    return False


def _timeline_representation(cache: dict[str, Any]) -> str:
    meta = cache.get("metadata") or {}
    rep = str(meta.get("representation_type") or "").strip().lower()
    if rep:
        return rep
    layout = cache.get("layout_metadata") or {}
    profile = str(
        layout.get("layout_profile") or layout.get("layout_mode") or ""
    ).strip().lower()
    if "hierarchy" in profile:
        return "hierarchy"
    if "cycle" in profile:
        return "cycle"
    if "comparison" in profile:
        return "comparison"
    if "process" in profile:
        return "flow"
    return ""


def _entity_label_from_entity(entity: dict[str, Any] | None) -> str:
    if not isinstance(entity, dict):
        return ""
    return str(entity.get("label") or "").strip()


def _beat_add_entity(beat: dict[str, Any]) -> dict[str, Any] | None:
    for op in beat.get("operations") or []:
        if not isinstance(op, dict) or op.get("op_type") != "add_entity":
            continue
        payload = op.get("payload") or {}
        entity = payload.get("entity") if isinstance(payload, dict) else None
        if isinstance(entity, dict):
            return entity
    return None


def _beat_annotation_text(beat: dict[str, Any]) -> str:
    for op in beat.get("operations") or []:
        if not isinstance(op, dict) or op.get("op_type") != "annotate_entity":
            continue
        payload = op.get("payload") or {}
        if isinstance(payload, dict):
            text = str(payload.get("text") or "").strip()
            if text:
                return text
    return ""


def _beat_narration_text(beat: dict[str, Any]) -> str:
    for field in ("narration_text", "narration", "text", "spoken_text"):
        text = str(beat.get(field) or "").strip()
        if text:
            return text
    for seg in beat.get("narration_segments") or []:
        if not isinstance(seg, dict):
            continue
        text = str(seg.get("text") or "").strip()
        if text:
            return text
    return ""


def _hierarchy_is_root(semantic: dict[str, Any]) -> bool:
    role = str(semantic.get("role") or "").strip().lower()
    payload = semantic.get("payload") or {}
    tier = ""
    if isinstance(payload, dict):
        tier = str(payload.get("hierarchy_tier") or "").strip().lower()
    return role == "anchor_root" or tier == "root"


def _hierarchy_is_branch(semantic: dict[str, Any]) -> bool:
    role = str(semantic.get("role") or "").strip().lower()
    payload = semantic.get("payload") or {}
    tier = ""
    if isinstance(payload, dict):
        tier = str(payload.get("hierarchy_tier") or "").strip().lower()
    return role == "trait" or tier == "branch"


def _comparison_is_header(semantic: dict[str, Any]) -> bool:
    role = str(semantic.get("role") or "").strip().lower()
    payload = semantic.get("payload") or {}
    tier = ""
    if isinstance(payload, dict):
        tier = str(payload.get("comparison_tier") or "").strip().lower()
    return "header" in role or tier == "header"


def _empty_quizable_items() -> dict[str, Any]:
    return {
        "representation": "",
        "topic_anchor": "",
        "steps": [],
        "teaching_facts": [],
        "transcript_lines": [],
    }


def _merge_quizable_items(*items: dict[str, Any]) -> dict[str, Any]:
    merged = _empty_quizable_items()
    seen_step: set[str] = set()
    seen_fact: set[str] = set()
    seen_line: set[str] = set()

    for item in items:
        if not item:
            continue
        if not merged["representation"] and item.get("representation"):
            merged["representation"] = str(item["representation"])
        if not merged["topic_anchor"] and item.get("topic_anchor"):
            merged["topic_anchor"] = str(item["topic_anchor"])
        for step in item.get("steps") or []:
            label = str(step).strip()
            key = label.lower()
            if label and key not in seen_step:
                seen_step.add(key)
                merged["steps"].append(label)
        for fact in item.get("teaching_facts") or []:
            text = str(fact).strip()
            if not text:
                continue
            key = fact_key(text)
            if key not in seen_fact:
                seen_fact.add(key)
                merged["teaching_facts"].append(text)
        for line in item.get("transcript_lines") or []:
            text = str(line).strip()
            if not text:
                continue
            key = fact_key(text)
            if key not in seen_line:
                seen_line.add(key)
                merged["transcript_lines"].append(text)
    return merged


def extract_quizable_items_from_timeline(
    cache: dict[str, Any] | None,
) -> dict[str, Any]:
    """
    Representation-aware extraction of quiz items from a Zone 1 VTSE timeline.

    For hierarchy layouts the root anchor (topic name) is context only — branch
    traits/steps are the quizable items.
    """
    if not isinstance(cache, dict) or not cache.get("beats"):
        return _empty_quizable_items()

    rep = _timeline_representation(cache)
    topic_anchor = ""
    steps: list[str] = []
    facts: list[str] = []
    transcript_lines: list[str] = []
    seen_step: set[str] = set()
    seen_fact: set[str] = set()
    seen_line: set[str] = set()

    beats = sorted(
        [b for b in cache.get("beats") or [] if isinstance(b, dict)],
        key=lambda b: int(b.get("index", 0) or 0),
    )

    for beat in beats:
        entity = _beat_add_entity(beat)
        semantic_raw = (entity or {}).get("semantic")
        semantic = semantic_raw if isinstance(semantic_raw, dict) else {}
        payload_raw = semantic.get("payload")
        payload = payload_raw if isinstance(payload_raw, dict) else {}

        narration = _beat_narration_text(beat)
        annotation = _beat_annotation_text(beat)
        if narration and not is_meta_instruction_text(narration):
            key = fact_key(narration)
            if key not in seen_line:
                seen_line.add(key)
                transcript_lines.append(narration)

        quizable = True
        identity = ""
        fact = ""

        if rep == "hierarchy":
            if _hierarchy_is_root(semantic):
                topic_anchor = (
                    str(payload.get("hierarchy_identity") or "").strip()
                    or _entity_label_from_entity(entity)
                    or topic_anchor
                )
                quizable = False
            elif _hierarchy_is_branch(semantic):
                identity = (
                    str(payload.get("hierarchy_identity") or "").strip()
                    or _entity_label_from_entity(entity)
                )
                fact = (
                    annotation
                    or str(payload.get("hierarchy_explanation") or "").strip()
                    or narration
                )
            else:
                quizable = int(beat.get("index", 0) or 0) > 0
                if quizable:
                    identity = _entity_label_from_entity(entity)
                    fact = annotation or narration
        elif rep == "comparison":
            if _comparison_is_header(semantic):
                quizable = False
            else:
                identity = (
                    str(payload.get("comparison_dimension") or "").strip()
                    or _entity_label_from_entity(entity)
                )
                fact = (
                    str(payload.get("row_detail") or "").strip()
                    or annotation
                    or narration
                )
        elif rep in ("flow", "cycle"):
            identity = (
                str(payload.get("process_identity") or "").strip()
                or _entity_label_from_entity(entity)
            )
            fact = (
                annotation
                or str(payload.get("process_explanation") or "").strip()
                or narration
            )
        else:
            if semantic and _hierarchy_is_root(semantic):
                topic_anchor = (
                    str(payload.get("hierarchy_identity") or "").strip()
                    or topic_anchor
                )
                quizable = False
            else:
                identity = _entity_label_from_entity(entity)
                fact = annotation or narration

        if quizable and fact and not is_meta_instruction_text(fact):
            fk = fact_key(fact)
            if fk not in seen_fact:
                seen_fact.add(fk)
                facts.append(fact.strip())
        if quizable and identity:
            ik = identity.lower()
            if ik not in seen_step:
                seen_step.add(ik)
                steps.append(identity)

    return {
        "representation": rep,
        "topic_anchor": topic_anchor,
        "steps": steps,
        "teaching_facts": facts,
        "transcript_lines": transcript_lines,
    }


def extract_narrations_from_timeline(cache: dict[str, Any] | None) -> list[str]:
    """Pull beat/node narration from a Zone 1 VTSE timeline payload."""
    if not isinstance(cache, dict):
        return []
    out: list[str] = []
    seen: set[str] = set()

    def _add(raw: str) -> None:
        text = _strip_markdown(str(raw or "").strip())
        if not text or is_meta_instruction_text(text):
            return
        key = fact_key(text)
        if key in seen:
            return
        seen.add(key)
        out.append(text)

    beats = cache.get("beats") or []
    sorted_beats = sorted(
        [b for b in beats if isinstance(b, dict)],
        key=lambda b: int(b.get("index", 0) or 0),
    )
    for beat in sorted_beats:
        _add(_beat_narration_text(beat))

    nodes = cache.get("nodes") or []
    if isinstance(nodes, list):
        for node in nodes:
            if not isinstance(node, dict):
                continue
            for field in ("narration_text", "narration", "text"):
                _add(str(node.get(field) or ""))

    return out


def _turn_is_zone1_teaching(turn: Any) -> bool:
    if int(getattr(turn, "zone", 0) or 0) != ZONE1_TEACHING_ZONE:
        return False
    rt = str(getattr(turn, "response_type", None) or "").strip().lower()
    return rt not in _ZONE0_RESPONSE_TYPES


def _prose_from_turn(turn: Any) -> list[str]:
    """Subject teaching lines from one board turn — VTSE timeline narrations only."""
    timeline = getattr(turn, "instruction_timeline_v3", None)
    if isinstance(timeline, dict):
        return extract_narrations_from_timeline(timeline)
    return []


def _append_unique(parts: list[str], seen: set[str], chunk: str) -> None:
    text = chunk.strip()
    if not text or is_meta_instruction_text(text):
        return
    key = fact_key(text[:500])
    if key in seen:
        return
    seen.add(key)
    parts.append(text)


def _concept_matches_turn(
    turn: Any,
    *,
    concept_low: str,
    concept_index: int,
) -> bool:
    if not _turn_is_zone1_teaching(turn):
        return False
    cid = str(getattr(turn, "concept_id", None) or "").strip().lower()
    if concept_low and cid == concept_low:
        return True
    return int(getattr(turn, "concept_index", -1) or -1) == concept_index


def _cluster_matches_turn(
    turn: Any,
    *,
    cluster_names: set[str],
    cluster_index: int,
) -> bool:
    if not _turn_is_zone1_teaching(turn):
        return False
    cid = str(getattr(turn, "concept_id", None) or "").strip().lower()
    if cid and cid in cluster_names:
        return True
    return int(getattr(turn, "cluster_index", -1) or -1) == cluster_index


def _session_timeline_for_concept(session: Any, concept_low: str) -> dict[str, Any] | None:
    cache = getattr(session, "zone1_timeline_cache", None)
    if not isinstance(cache, dict) or not cache.get("beats"):
        return None
    board_concept = str(getattr(session, "zone1_board_concept_id", None) or "").strip().lower()
    current = str(getattr(session, "current_concept", None) or "").strip().lower()
    target = concept_low or current
    if board_concept and target and board_concept != target:
        return None
    return cache


def extract_teaching_facts(
    transcript: str,
    *,
    steps: list[str] | None = None,
) -> list[str]:
    """Turn lesson prose into ordered, deduplicated quizable facts."""
    facts: list[str] = []
    seen: set[str] = set()

    for step in steps or []:
        text = _strip_markdown(str(step).strip())
        if not text or is_meta_instruction_text(text):
            continue
        key = fact_key(text)
        if key in seen:
            continue
        seen.add(key)
        facts.append(text)

    clean = _strip_markdown(transcript)
    if clean:
        for sent in re.split(r"(?<=[.!?])\s+", clean):
            text = sent.strip()
            if not text or _is_boilerplate_sentence(text):
                continue
            if not (12 <= len(text) <= 280):
                continue
            word_count = len(text.split())
            if word_count < 2 or word_count > 40:
                continue
            if word_count < 3 and len(text) < 10:
                continue
            key = fact_key(text)
            if key in seen:
                continue
            seen.add(key)
            facts.append(text)
            if len(facts) >= 24:
                break

    if not facts and clean:
        for para in re.split(r"\n{2,}", transcript):
            text = _strip_markdown(para.strip())
            if 20 <= len(text) <= 400:
                key = fact_key(text)
                if key not in seen:
                    seen.add(key)
                    facts.append(text)
            if len(facts) >= 12:
                break

    return facts[:24]


def _cluster_concept_names(session: Any) -> set[str]:
    kc = [
        str(c).strip()
        for c in (getattr(session, "key_concepts", None) or [])
        if str(c).strip()
    ]
    if not kc:
        return set()
    clusters = resolve_clusters(kc, getattr(session, "concept_clusters", None))
    if not clusters:
        return set()
    idx = int(getattr(session, "current_concept_index", 0) or 0)
    cluster_idx = derive_current_cluster_index(idx, clusters)
    if cluster_idx < 0 or cluster_idx >= len(clusters):
        return set()
    return {c.strip().lower() for c in clusters[cluster_idx] if str(c).strip()}


async def load_teaching_transcript(
    session_id: PydanticObjectId,
    session: Any,
    *,
    scope: QuestionScope,
) -> str:
    """Collect Zone 1 VTSE teaching prose only — never Zone 0 or UI instructions."""
    repo = BoardTurnRepository()
    turns = await repo.get_turns(session_id, limit=200)
    parts: list[str] = []
    seen_blocks: set[str] = set()

    if scope == "zone":
        for turn in turns:
            for line in _prose_from_turn(turn):
                _append_unique(parts, seen_blocks, line)
    elif scope == "concept":
        concept = str(getattr(session, "current_concept", None) or "").strip()
        concept_low = concept.lower()
        concept_index = int(getattr(session, "current_concept_index", 0) or 0)

        session_cache = _session_timeline_for_concept(session, concept_low)
        if session_cache:
            for line in extract_narrations_from_timeline(session_cache):
                _append_unique(parts, seen_blocks, line)

        for turn in turns:
            if not _concept_matches_turn(
                turn, concept_low=concept_low, concept_index=concept_index
            ):
                continue
            for line in _prose_from_turn(turn):
                _append_unique(parts, seen_blocks, line)
    else:
        cluster_names = _cluster_concept_names(session)
        cluster_index = int(getattr(session, "current_cluster_index", 0) or 0)
        for turn in turns:
            if not _cluster_matches_turn(
                turn,
                cluster_names=cluster_names,
                cluster_index=cluster_index,
            ):
                continue
            for line in _prose_from_turn(turn):
                _append_unique(parts, seen_blocks, line)

    transcript = "\n\n".join(parts).strip()
    return transcript[:12_000]


def _cluster_base_taught_context(session: Any) -> dict[str, Any]:
    points = [
        str(p).strip()
        for p in (getattr(session, "cluster_taught_points", None) or [])
        if str(p).strip()
    ]
    if points:
        return {
            "taught_points": points,
            "steps": points,
            "lesson_excerpt": "\n".join(points[:16]),
            "step_count": len(points),
            "representation": "",
        }
    return build_taught_context(session)


async def collect_timeline_quizable_items(
    session_id: PydanticObjectId,
    session: Any,
    *,
    scope: QuestionScope,
) -> dict[str, Any]:
    """Merge representation-aware quizable items from session cache and board turns."""
    sources: list[dict[str, Any]] = []
    repo = BoardTurnRepository()
    turns = await repo.get_turns(session_id, limit=200)

    if scope == "zone":
        for turn in turns:
            timeline = getattr(turn, "instruction_timeline_v3", None)
            if isinstance(timeline, dict):
                sources.append(extract_quizable_items_from_timeline(timeline))
    elif scope == "concept":
        concept = str(getattr(session, "current_concept", None) or "").strip()
        concept_low = concept.lower()
        concept_index = int(getattr(session, "current_concept_index", 0) or 0)
        session_cache = _session_timeline_for_concept(session, concept_low)
        if session_cache:
            sources.append(extract_quizable_items_from_timeline(session_cache))
        for turn in turns:
            if not _concept_matches_turn(
                turn, concept_low=concept_low, concept_index=concept_index
            ):
                continue
            timeline = getattr(turn, "instruction_timeline_v3", None)
            if isinstance(timeline, dict):
                sources.append(extract_quizable_items_from_timeline(timeline))
    else:
        cluster_names = _cluster_concept_names(session)
        cluster_index = int(getattr(session, "current_cluster_index", 0) or 0)
        for turn in turns:
            if not _cluster_matches_turn(
                turn,
                cluster_names=cluster_names,
                cluster_index=cluster_index,
            ):
                continue
            timeline = getattr(turn, "instruction_timeline_v3", None)
            if isinstance(timeline, dict):
                sources.append(extract_quizable_items_from_timeline(timeline))

    if not sources:
        return _empty_quizable_items()
    return _merge_quizable_items(*sources)


def _apply_structured_quizable(
    out: dict[str, Any],
    structured: dict[str, Any],
) -> dict[str, Any]:
    facts = [
        str(f).strip()
        for f in (structured.get("teaching_facts") or [])
        if str(f).strip() and not is_meta_instruction_text(str(f))
    ]
    if not facts:
        return out

    steps = [
        str(s).strip() for s in (structured.get("steps") or []) if str(s).strip()
    ]
    out["teaching_facts"] = facts
    out["taught_points"] = facts
    out["steps"] = steps or list(facts)
    out["step_count"] = len(facts)
    if structured.get("representation"):
        out["representation"] = str(structured["representation"])
    if structured.get("topic_anchor"):
        out["topic_anchor"] = str(structured["topic_anchor"]).strip()
    lines = [
        str(line).strip()
        for line in (structured.get("transcript_lines") or [])
        if str(line).strip()
    ]
    if lines:
        out["teaching_transcript"] = "\n\n".join(lines)[:8000]
        out["lesson_excerpt"] = out["teaching_transcript"][:3500]
    return out


def merge_transcript_into_taught_context(
    base_ctx: dict[str, Any],
    transcript: str,
    *,
    structured: dict[str, Any] | None = None,
) -> dict[str, Any]:
    out = dict(base_ctx)
    if structured and structured.get("teaching_facts"):
        out = _apply_structured_quizable(out, structured)
        if transcript and not out.get("teaching_transcript"):
            out["teaching_transcript"] = transcript[:8000]
            out["lesson_excerpt"] = transcript[:3500]
        return out

    steps = list(out.get("steps") or [])
    teaching_facts = extract_teaching_facts(transcript, steps=steps)
    if teaching_facts:
        out["teaching_facts"] = [
            f for f in teaching_facts if not is_meta_instruction_text(f)
        ]
        if out["teaching_facts"]:
            out["taught_points"] = out["teaching_facts"]
            out["step_count"] = len(out["teaching_facts"])
    if transcript:
        out["teaching_transcript"] = transcript[:8000]
        out["lesson_excerpt"] = transcript[:3500]
    return out


async def build_concept_quiz_taught_context(
    session_id: PydanticObjectId,
    session: Any,
) -> dict[str, Any]:
    """Transcript-only context for concept check — no session lexicon or tutor chat."""
    cache = getattr(session, "zone1_timeline_cache", None) or {}
    representation = ""
    if isinstance(cache, dict):
        representation = str(
            cache.get("representation_type")
            or (cache.get("layout_metadata") or {}).get("layout_mode")
            or _timeline_representation(cache)
            or ""
        ).strip().lower()
    base: dict[str, Any] = {
        "step_count": 0,
        "steps": [],
        "taught_points": [],
        "representation": representation,
        "lesson_excerpt": "",
    }
    structured = await collect_timeline_quizable_items(
        session_id, session, scope="concept"
    )
    transcript = await load_teaching_transcript(session_id, session, scope="concept")
    return merge_transcript_into_taught_context(
        base, transcript, structured=structured
    )


async def build_zone_clarity_gate_taught_context(
    session_id: PydanticObjectId,
    session: Any,
) -> dict[str, Any]:
    """Authoritative Zone 1 lesson — all clusters taught on the whiteboard this session."""
    structured = await collect_timeline_quizable_items(
        session_id, session, scope="zone"
    )
    base_points = [
        str(p).strip()
        for p in (getattr(session, "topic_taught_points", None) or [])
        if str(p).strip()
    ]
    if structured.get("teaching_facts"):
        base: dict[str, Any] = {
            "step_count": 0,
            "steps": [],
            "taught_points": [],
            "representation": str(structured.get("representation") or ""),
            "lesson_excerpt": "",
        }
    else:
        base = {
            "taught_points": base_points,
            "steps": base_points,
            "lesson_excerpt": "\n".join(base_points[:24]),
            "step_count": len(base_points),
            "representation": "",
        }
    transcript = await load_teaching_transcript(session_id, session, scope="zone")
    return merge_transcript_into_taught_context(
        base, transcript, structured=structured
    )


async def build_cluster_quiz_taught_context(
    session_id: PydanticObjectId,
    session: Any,
) -> dict[str, Any]:
    structured = await collect_timeline_quizable_items(
        session_id, session, scope="cluster"
    )
    if structured.get("teaching_facts"):
        base: dict[str, Any] = {
            "step_count": 0,
            "steps": [],
            "taught_points": [],
            "representation": str(structured.get("representation") or ""),
            "lesson_excerpt": "",
        }
    else:
        base = _cluster_base_taught_context(session)
    transcript = await load_teaching_transcript(session_id, session, scope="cluster")
    return merge_transcript_into_taught_context(
        base, transcript, structured=structured
    )


def _format_hierarchy_taught_block(ctx: dict[str, Any]) -> str:
    topic = str(ctx.get("topic_anchor") or "").strip()
    facts = list(ctx.get("teaching_facts") or [])
    steps = list(ctx.get("steps") or [])
    if not topic or not facts:
        return ""

    lines = [
        f'TOPIC ANCHOR (context only — do NOT count as a taught item or quiz on it): "{topic}"',
        f"CHARACTERISTICS TAUGHT ON THE BOARD (exactly {len(facts)} — quiz ONLY on these):",
    ]
    for i, fact in enumerate(facts, 1):
        label = steps[i - 1] if i - 1 < len(steps) else f"Characteristic {i}"
        lines.append(f"{i}. {label} — {fact}")
    lines.append(
        f"\nRULES: The lesson taught exactly {len(facts)} characteristics, not "
        f"{len(facts) + 1}. Do NOT treat \"{topic}\" as a separate learned item."
    )
    return "\n".join(lines)


def format_transcript_taught_block(ctx: dict[str, Any]) -> str:
    """Zone 1 board teaching only — never session meta or tutor chat."""
    hierarchy_block = _format_hierarchy_taught_block(ctx)
    if hierarchy_block:
        return hierarchy_block

    transcript = str(ctx.get("teaching_transcript") or "").strip()
    facts = list(ctx.get("teaching_facts") or [])
    if transcript:
        return (
            "FULL LESSON TAUGHT ON THE BOARD (authoritative — use ONLY this):\n"
            + transcript[:3200]
        )
    if facts:
        return (
            "Facts taught on the board:\n"
            + "\n".join(f"- {f}" for f in facts[:12])
        )
    return ""


def archetype_for_slot(question_type: str, index: int) -> str:
    if question_type == "mcq":
        pool = _MCQ_ARCHETYPES
    elif question_type == "fill_in_blank":
        pool = _FILL_ARCHETYPES
    else:
        pool = _DESC_ARCHETYPES
    return pool[index % len(pool)]


def pick_focus_fact(
    taught_ctx: dict[str, Any],
    *,
    used_fact_keys: list[str],
    question_index: int,
) -> tuple[str, str]:
    facts = list(taught_ctx.get("teaching_facts") or [])
    if not facts:
        facts = [
            str(f).strip()
            for f in list(taught_ctx.get("steps") or [])
            + list(taught_ctx.get("taught_points") or [])
            if str(f).strip()
        ]
    if not facts:
        excerpt = str(taught_ctx.get("lesson_excerpt") or "").strip()
        facts = extract_teaching_facts(excerpt)
    facts = [f for f in facts if not is_meta_instruction_text(f)]
    if not facts:
        return "", ""

    used = {k for k in used_fact_keys if k}
    pool = [f for f in facts if fact_key(f) not in used]
    if not pool:
        pool = list(facts)

    rng = random.Random(question_index * 31 + sum(ord(c) for k in used for c in k))
    ordered = list(pool)
    rng.shuffle(ordered)
    fact = ordered[0]
    return fact, fact_key(fact)


def build_focus_assignment_block(
    *,
    concept: str,
    focus_fact: str,
    archetype: str,
    question_type: str,
    taught_count: int,
    topic_anchor: str = "",
) -> str:
    archetype_line = _ARCHETYPE_PROMPTS.get(
        archetype, "Ask one clear teacher-style question about the focus fact only."
    )
    count_line = ""
    if taught_count > 0:
        if topic_anchor:
            count_line = (
                f"\n- The topic \"{topic_anchor}\" is context only — NOT a separate "
                f"taught item."
                f"\n- The lesson taught exactly {taught_count} characteristics/ideas "
                f"under that topic. Do NOT ask about any other count (e.g. do not say "
                f"\"{taught_count + 1} characteristics\" or \"four key points\")."
            )
        else:
            count_line = (
                f"\n- The lesson taught exactly {taught_count} distinct ideas. "
                f"Do NOT ask about any other count (e.g. do not say "
                f"\"{taught_count + 1} characteristics\" or \"four key points\")."
            )
    return (
        f'CONCEPT: "{concept}"\n\n'
        f'FOCUS FACT — ask ONLY about this (do not ask about other lesson topics):\n'
        f'"{focus_fact}"\n\n'
        f"QUESTION STYLE: {archetype_line}\n\n"
        "STRICT RULES:\n"
        "- Test ONLY the focus fact above.\n"
        "- Do NOT ask \"what are the main ideas\", \"list all characteristics\", "
        "\"what is the main topic\", \"what does the teacher mean\", "
        "or similar broad summary / meta questions.\n"
        "- Do NOT ask about warm-up questions, following the board, chat instructions, "
        "or how the lesson works — only subject content.\n"
        "- The correct_answer MUST restate or complete the focus fact. "
        "Do NOT introduce names, numbers, stages, or processes absent from the focus fact.\n"
        "- Distractors may be false contrasts; they must not be other true lesson facts "
        "that would also be acceptable answers."
        f"{count_line}"
    )


def text_relates_to_fact(text: str, focus_fact: str) -> bool:
    if not focus_fact:
        return True
    blob = (text or "").lower()
    fact_low = focus_fact.lower()
    if fact_low[:48] in blob:
        return True
    fact_kw = _answer_keywords(focus_fact)
    if not fact_kw:
        return False
    text_kw = _answer_keywords(text)
    overlap = fact_kw & text_kw
    if len(overlap) >= 1:
        return True
    if len(fact_kw) <= 3:
        return bool(overlap)
    return len(overlap) >= min(2, len(fact_kw))


def text_strongly_grounded_in_fact(text: str, fact: str) -> bool:
    """
    True when ``text`` is clearly taken from ``fact`` (not a loose 1-word skim).

    Used to stop AI/bank concept-check items from drifting onto neighboring facts.
    """
    if not fact:
        return True
    blob = (text or "").strip().lower()
    fact_low = (fact or "").strip().lower()
    if not blob:
        return False
    # Substantial shared substring either direction.
    chunk = fact_low[: min(48, len(fact_low))]
    if len(chunk) >= 12 and chunk in blob:
        return True
    text_chunk = blob[: min(48, len(blob))]
    if len(text_chunk) >= 12 and text_chunk in fact_low:
        return True
    fact_kw = _answer_keywords(fact)
    text_kw = _answer_keywords(text)
    if not fact_kw or not text_kw:
        return False
    overlap = fact_kw & text_kw
    if len(fact_kw) <= 2:
        return fact_kw <= text_kw
    # Require about half of the fact's content words (min 2).
    need = max(2, (len(fact_kw) + 1) // 2)
    return len(overlap) >= min(need, len(fact_kw))


def taught_fact_strings(taught_ctx: dict[str, Any]) -> list[str]:
    facts: list[str] = []
    seen: set[str] = set()
    for item in list(taught_ctx.get("teaching_facts") or []) + list(
        taught_ctx.get("taught_points") or []
    ) + list(taught_ctx.get("steps") or []):
        text = str(item).strip()
        if not text or is_meta_instruction_text(text):
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        facts.append(text)
    return facts


def _numeric_count_answer_matches_board(
    pack: dict[str, Any],
    taught_ctx: dict[str, Any],
) -> bool:
    """Allow how-many MCQs whose correct option equals the board item count."""
    question = str(pack.get("question") or "").strip()
    correct = str(pack.get("correct_answer") or "").strip()
    if not re.search(r"(?i)\bhow many\b", question):
        return False
    if not re.fullmatch(r"\d+", correct):
        return False
    from app.services.handlers.concept_taught_context import effective_taught_item_count

    n = effective_taught_item_count(taught_ctx)
    if n <= 0:
        n = int(taught_ctx.get("step_count") or 0)
    return n > 0 and correct == str(n)


def pack_matches_focus_fact(pack: dict[str, Any], focus_fact: str) -> bool:
    if not focus_fact:
        return True
    question = str(pack.get("question") or "").strip()
    correct = str(pack.get("correct_answer") or "").strip()
    if is_broad_quiz_stem(question):
        return False
    if not text_relates_to_fact(f"{question} {correct}", focus_fact):
        return False
    # Correct key must stay on the assigned focus fact (prevents AI drift).
    if correct and not text_strongly_grounded_in_fact(correct, focus_fact):
        return False
    return True


def pack_matches_taught(
    pack: dict[str, Any],
    taught_ctx: dict[str, Any],
    *,
    required_type: str,
    focus_fact: str = "",
) -> bool:
    question = str(pack.get("question") or "").strip()
    correct = str(pack.get("correct_answer") or "").strip()
    if not question:
        return False
    if is_meta_instruction_text(question):
        return False
    if is_meta_quiz_question(question):
        return False
    if is_broad_quiz_stem(question):
        return False
    if not question_count_matches_taught(question, taught_ctx):
        return False
    if focus_fact and is_meta_instruction_text(focus_fact):
        return False
    if focus_fact and not pack_matches_focus_fact(pack, focus_fact):
        return False

    facts = taught_fact_strings(taught_ctx)

    if required_type == "mcq":
        from app.services.handlers.concept_check_question_service import (
            is_quality_mcq_pack,
        )

        options = [str(o).strip() for o in (pack.get("options") or []) if str(o).strip()]
        if len(options) < 3 or correct not in options:
            return False
        if not is_quality_mcq_pack(pack, taught_ctx):
            return False
        if focus_fact:
            if not text_strongly_grounded_in_fact(correct, focus_fact):
                return False
        elif facts:
            # Bank / unfocused: correct option must match this session's board.
            if not (
                _numeric_count_answer_matches_board(pack, taught_ctx)
                or any(text_strongly_grounded_in_fact(correct, f) for f in facts)
            ):
                return False

    elif required_type == "fill_in_blank":
        if not correct:
            return False
        from app.services.handlers.concept_check_question_types import (
            is_strong_fill_in_answer,
        )

        if not is_strong_fill_in_answer(correct):
            return False
        if focus_fact:
            if not text_strongly_grounded_in_fact(correct, focus_fact):
                return False
        elif facts:
            if not any(
                text_strongly_grounded_in_fact(correct, f)
                or text_relates_to_fact(correct, f)
                for f in facts
            ):
                return False
            # Prefer strong grounding when the bank answer is multi-word.
            if len(_answer_keywords(correct)) >= 3 and not any(
                text_strongly_grounded_in_fact(correct, f) for f in facts
            ):
                return False

    return True


def record_used_fact(session: Any, focus_fact_key: str, *, scope: QuestionScope) -> None:
    if not focus_fact_key:
        return
    field = (
        "concept_quiz_used_facts"
        if scope == "concept"
        else "cluster_quiz_used_facts"
    )
    used = list(getattr(session, field, None) or [])
    if focus_fact_key not in used:
        used.append(focus_fact_key)
    setattr(session, field, used)


def used_fact_keys(session: Any, *, scope: QuestionScope) -> list[str]:
    field = (
        "concept_quiz_used_facts"
        if scope == "concept"
        else "cluster_quiz_used_facts"
    )
    return list(getattr(session, field, None) or [])


def build_rule_based_pack_from_focus(
    *,
    focus_fact: str,
    archetype: str,
    question_type: str,
    concept: str,
    index: int,
    taught_ctx: dict[str, Any],
) -> dict[str, Any] | None:
    """Deterministic teacher-style question when LLM output fails validation."""
    if not focus_fact:
        return None

    c = (concept or "this topic").strip()
    fact = focus_fact.strip()

    if question_type == "mcq":
        from app.services.handlers.concept_check_question_service import (
            _statement_mcq_from_taught,
        )

        pack = _statement_mcq_from_taught(c, [fact], index)
        pack["source"] = "transcript_focus"
        return pack

    if question_type == "fill_in_blank":
        from app.services.handlers.concept_check_question_types import (
            pick_fill_in_answer_from_fact,
        )

        answer = pick_fill_in_answer_from_fact(fact)
        if not answer:
            return None
        blanked = re.sub(
            re.escape(answer),
            "_____",
            fact,
            count=1,
            flags=re.IGNORECASE,
        )
        if "_____" not in blanked:
            blanked = f"According to the lesson, {c} _____."
        return {
            "question": blanked if blanked.endswith("?") else f"{blanked.rstrip('.')}?",
            "options": [],
            "correct_answer": answer,
            "explanation": fact,
            "type": "fill_in_blank",
            "source": "transcript_focus",
        }

    templates = {
        "explain_own_words": f"In your own words, what did the lesson say about {c} regarding: {fact.rstrip('.')}?",
        "what_happens": f"According to the lesson, what happens when we talk about {fact.rstrip('.')}?",
        "why_important": f"Why is this idea from the lesson important: {fact.rstrip('.')}?",
    }
    question = templates.get(
        archetype,
        f"Briefly explain this idea from the lesson in 1-2 sentences: {fact.rstrip('.')}?",
    )
    return {
        "question": question if question.endswith("?") else f"{question}?",
        "options": [],
        "correct_answer": fact,
        "explanation": fact,
        "type": "descriptive",
        "source": "transcript_focus",
    }
