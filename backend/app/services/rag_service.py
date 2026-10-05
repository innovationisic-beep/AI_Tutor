import os
from typing import Any, List, Optional, Sequence, TypeVar

import httpx
import numpy as np
from beanie.odm.fields import PydanticObjectId
from beanie.operators import Inc
from sklearn.metrics.pairwise import cosine_similarity

from app.core.config import DEEPSEEK_THINKING_DISABLED, Settings
from app.models.content.topic_notes import TopicNote
from app.repositories.topic_note_repository import TopicNoteRepository
from app.repositories.topic_question_repository import TopicQuestionRepository
from app.repositories.topic_repository import TopicRepository
from app.repositories.video_subtitle_repository import VideoSubtitleRepository
from app.services.embedding_service import get_embedding
from app.services.teacher_topic_service import normalize_topic_name

TItem = TypeVar("TItem")

# Appended to narrative tutor prompts only (not EVALUATE / quiz generation branches).
TEACHER_RESPONSE_PRESENTATION_SUFFIX = """
---

Additionally, format your response like a friendly teacher:

1. ENGAGING START (CONTEXT-AWARE)

Use an engaging hook ONLY when introducing a new concept or topic.

Examples:
- "Have you ever wondered..."
- "Imagine if..."
- "Do you know why..."

IMPORTANT:
- DO NOT use a hook when answering a direct question
- DO NOT use a hook for follow-up explanations
- DO NOT repeat the same hook pattern frequently
- Vary your openings naturally

---

2. DIRECT QUESTION HANDLING

If the student asks a direct question:
- Answer immediately and clearly
- Do NOT add a hook
- Do NOT add unnecessary introduction

---

3. NATURAL FLOW

- Continue explanations naturally without restarting tone
- Avoid sounding repetitive or scripted
- Keep responses context-aware

---

4. STRUCTURE (keep existing)

- Short explanation (2–3 lines)
- Bullet points if needed
- Example if helpful
- Quick summary if useful

---

5. FORMAT RULES (keep existing)

- No markdown symbols like *, **
- Clean readable text

---

IMPORTANT:

- Adapt your tone based on context
- Do NOT force structure if not needed
- Do NOT behave like a template
- Behave like a real human teacher
"""


def _rank_by_similarity(
    query_embedding: List[float],
    items: Sequence[TItem],
    get_embedding_fn: Any,
) -> List[TItem]:
    """Order items by cosine similarity to query_embedding; skip items with no embedding."""
    _ = get_embedding_fn  # reserved for API symmetry / future use
    scored: List[tuple[float, TItem]] = []
    if not query_embedding or not items:
        return []
    try:
        q = np.asarray(query_embedding, dtype=np.float64).reshape(1, -1)
    except Exception:
        return []
    for item in items:
        try:
            if item.embedding is None:
                continue
            emb = item.embedding
            v = np.asarray(emb, dtype=np.float64).reshape(1, -1)
            if v.shape[1] != q.shape[1]:
                continue
            sim = float(cosine_similarity(q, v)[0][0])
            scored.append((sim, item))
        except Exception:
            continue
    scored.sort(key=lambda x: x[0], reverse=True)
    return [x[1] for x in scored]


class RAGService:
    """Retrieves approved topic notes for RAG context building."""

    def __init__(
        self,
        topic_note_repository: TopicNoteRepository,
        video_subtitle_repository: VideoSubtitleRepository,
        topic_question_repository: TopicQuestionRepository,
        topic_repository: TopicRepository,
    ) -> None:
        self.topic_note_repository = topic_note_repository
        self.video_subtitle_repository = video_subtitle_repository
        self.topic_question_repository = topic_question_repository
        self.topic_repository = topic_repository

    async def _extra_teacher_topic_storage_ids(
        self,
        topic_id: PydanticObjectId,
        organization_id: PydanticObjectId,
        curriculum_class_id: str | None,
        curriculum_subject_id: str | None,
    ) -> list[PydanticObjectId]:
        """
        When sessions use the admin Topic id but teachers authored notes under
        TeacherTopic.id, return those teacher-topic ids (same org, class, subject, name).
        """
        from app.models.organization import Organization

        org_row = await Organization.get(organization_id)
        if org_row is None or org_row.organization_type != "institution":
            return []

        cc = (curriculum_class_id or "").strip() or None
        cs = (curriculum_subject_id or "").strip() or None
        if not cc or not cs:
            return []
        topic = await self.topic_repository.get_by_id(topic_id)
        if topic is None:
            return []
        if (
            topic.organization_id is not None
            and topic.organization_id != organization_id
        ):
            return []
        tk = normalize_topic_name(topic.topic_name or "")
        if not tk:
            return []
        from app.models.teacher_topic import TeacherTopic

        trows = await TeacherTopic.find(
            TeacherTopic.organization_id == organization_id,
            TeacherTopic.class_id == cc,
            TeacherTopic.subject_id == cs,
        ).to_list()
        tt = next(
            (r for r in trows if normalize_topic_name(r.topic_name) == tk),
            None,
        )
        if tt is None or tt.id == topic_id:
            return []
        return [tt.id]

    async def detect_topic_from_query(
        self,
        question: str,
        organization_id: PydanticObjectId,
    ) -> PydanticObjectId | None:
        question_lower = question.lower()

        topics = await self.topic_repository.get_many(
            filters={"organization_id": organization_id},
            limit=50,
        )

        for topic in topics:
            if topic.topic_name.lower() in question_lower:
                return topic.id

            for concept in topic.key_concepts or []:
                if concept.lower() in question_lower:
                    return topic.id

        return None

    @staticmethod
    def _norm(value: str | None) -> str | None:
        return value.strip().lower() if value else value

    def _score_note(
        self,
        note: TopicNote,
        teaching_style: str | None,
        interest_category: str | None,
        difficulty_level: str | None,
        current_concept: str | None = None,
        concept_id: PydanticObjectId | None = None,
    ) -> float:
        score = 0.0

        st = (note.source_type or "teacher").lower()
        if st in ("teacher", "admin", "teacher_override"):
            score += 50
        elif st == "ai":
            score += 10
        else:
            score += 10

        score += min(note.usage_count or 0, 20)

        if teaching_style and note.teaching_style == teaching_style:
            score += 15

        if interest_category and note.interest_category == interest_category:
            score += 15

        if difficulty_level and note.difficulty_level == difficulty_level:
            score += 10

        if current_concept and self._norm(getattr(note, "concept", None)) == self._norm(
            current_concept
        ):
            score += 35

        linked_id = getattr(note, "concept_id", None)
        if linked_id is not None and concept_id is not None and linked_id == concept_id:
            score += 50

        if note.updated_at:
            score += 5

        return score

    # Maps current_zone → the set of difficulty_level DB values that are
    # appropriate for that zone.  Zone 1 uses basic/medium so there is always
    # a reasonable pool; Zone 2 tightens to medium; Zones 3–4 prefer harder
    # material while keeping medium as a fallback.
    _ZONE_DIFFICULTY_BUCKETS: dict[int, list[str]] = {
        1: ["basic", "medium"],
        2: ["medium"],
        3: ["medium", "hard"],
        4: ["medium", "hard"],
    }

    async def _collect_notes_by_concept_id(
        self,
        *,
        topic_id: PydanticObjectId,
        concept_id: PydanticObjectId,
        organization_id: PydanticObjectId,
        curriculum_class_id: str | None,
        curriculum_subject_id: str | None,
        limit: int = 80,
    ) -> List[TopicNote]:
        """Approved notes for a structured curriculum concept id (primary lookup)."""
        raw_notes: list[TopicNote] = []
        raw_notes.extend(
            await self.topic_note_repository.get_notes_by_concept_id(
                topic_id,
                concept_id,
                organization_id=organization_id,
                limit=limit,
            )
        )
        extra_ids = await self._extra_teacher_topic_storage_ids(
            topic_id,
            organization_id,
            curriculum_class_id,
            curriculum_subject_id,
        )
        for xid in extra_ids:
            raw_notes.extend(
                await self.topic_note_repository.get_notes_by_concept_id(
                    xid,
                    concept_id,
                    organization_id=organization_id,
                    limit=limit,
                )
            )
        seen: set[PydanticObjectId] = set()
        out: list[TopicNote] = []
        for note in raw_notes:
            if note.id in seen:
                continue
            seen.add(note.id)
            if not getattr(note, "approved", False):
                continue
            if note.organization_id is not None and note.organization_id != organization_id:
                continue
            out.append(note)
        return out

    async def get_topic_notes(
        self,
        topic_id: PydanticObjectId,
        organization_id: PydanticObjectId,
        limit: int = 5,
        teaching_style: str | None = None,
        interest_category: str | None = None,
        difficulty_level: str | None = None,
        current_concept: str | None = None,
        concept_id: PydanticObjectId | None = None,
        user_query: str | None = None,
        curriculum_class_id: str | None = None,
        curriculum_subject_id: str | None = None,
        strict_concept: bool = False,
        vtse_authoring: bool = False,
        zone: int | None = None,
    ) -> List[TopicNote]:
        """
        Load notes for the topic; when current_concept is set, prefer notes tagged with
        that concept while still including general (untagged) notes.

        When ``concept_id`` is set (structured v2 curriculum), notes linked to that
        Mongo id are loaded first — stable even when runtime key strings differ.

        strict_concept=True: when a current_concept is provided the returned set is
        limited to notes whose concept field exactly matches that concept.  General
        (concept=None) notes are only included as a last-resort fallback when no
        concept-specific notes exist.  Use this for quiz generation where returning
        off-concept notes could cause out-of-scope questions.

        vtse_authoring=True: VTSE whiteboard authoring only — exact concept match,
        no fallback to general or off-concept notes from the wider topic.

        zone: when set, maps session.current_zone to an appropriate difficulty bucket
        (see _ZONE_DIFFICULTY_BUCKETS).  This takes precedence over difficulty_level
        when the zone value is known.  Falls back to difficulty_level if the zone
        produces no matching notes.
        """
        from app.models.learning.mastery_records import normalize_concept

        def _note_visible(n: TopicNote, org_id: PydanticObjectId) -> bool:
            return getattr(n, "approved", False) and (
                n.organization_id is None or n.organization_id == org_id
            )

        cc = normalize_concept(current_concept)
        cc_norm = self._norm(current_concept)
        notes: list[TopicNote] = []
        used_concept_id_lookup = False

        if concept_id is not None:
            id_notes = await self._collect_notes_by_concept_id(
                topic_id=topic_id,
                concept_id=concept_id,
                organization_id=organization_id,
                curriculum_class_id=curriculum_class_id,
                curriculum_subject_id=curriculum_subject_id,
            )
            if id_notes:
                notes = id_notes
                used_concept_id_lookup = True

        if not used_concept_id_lookup:
            raw_notes = await self.topic_note_repository.get_notes(
                topic_id,
                concept=cc,
                organization_id=organization_id,
                limit=80,
            )
            extra_ids = await self._extra_teacher_topic_storage_ids(
                topic_id,
                organization_id,
                curriculum_class_id,
                curriculum_subject_id,
            )
            for xid in extra_ids:
                more = await self.topic_note_repository.get_notes(
                    xid,
                    concept=cc,
                    organization_id=organization_id,
                    limit=80,
                )
                raw_notes.extend(more)
            seen_ids: set[PydanticObjectId] = set()
            deduped_notes: list[TopicNote] = []
            for n in raw_notes:
                if n.id in seen_ids:
                    continue
                seen_ids.add(n.id)
                deduped_notes.append(n)
            raw_notes = deduped_notes
            notes = [n for n in raw_notes if _note_visible(n, organization_id)]

        if used_concept_id_lookup and vtse_authoring:
            notes = [n for n in notes if getattr(n, "concept_id", None) == concept_id]

        # ── Strict concept mode: exclude general (concept=None) notes when possible ──
        if strict_concept and notes and not used_concept_id_lookup and cc_norm:
            concept_notes = [
                n
                for n in notes
                if self._norm(getattr(n, "concept", None)) == cc_norm
            ]
            # Only apply the strict filter when concept-specific notes actually exist;
            # fall back to the full set (concept + general) to avoid an empty context.
            if concept_notes:
                notes = concept_notes

        if vtse_authoring and not used_concept_id_lookup and cc_norm:
            notes = [
                n
                for n in notes
                if self._norm(getattr(n, "concept", None)) == cc_norm
            ]

        if not vtse_authoring and not used_concept_id_lookup:
            if not notes and cc is not None:
                raw_notes = await self.topic_note_repository.get_notes(
                    topic_id,
                    concept=None,
                    organization_id=organization_id,
                    limit=80,
                )
                notes = [n for n in raw_notes if _note_visible(n, organization_id)]
            if not notes:
                raw_notes = await self.topic_note_repository.get_notes(
                    topic_id,
                    concept=None,
                    organization_id=organization_id,
                    limit=50,
                )
                notes = [n for n in raw_notes if _note_visible(n, organization_id)]
        teacher_tier = ("teacher", "admin", "teacher_override")
        teacher_notes = [
            n
            for n in notes
            if (getattr(n, "source_type", None) or "teacher").lower() in teacher_tier
        ]
        ai_notes = [n for n in notes if getattr(n, "source_type", None) == "ai"]

        # ── Zone → difficulty bucket ─────────────────────────────────────────────
        # Resolved once here so apply_filters (a closure) can reference it.
        # Zone takes precedence; difficulty_level is the fallback for callers that
        # do not pass a zone (e.g. explanation flow).
        zone_difficulties: list[str] | None = None
        if zone is not None and zone >= 1:
            clamped_zone = min(int(zone), 4)
            zone_difficulties = self._ZONE_DIFFICULTY_BUCKETS.get(
                clamped_zone, ["medium", "hard"]
            )

        def apply_filters(note_list: List[TopicNote]) -> List[TopicNote]:
            result = note_list

            if teaching_style:
                result = [
                    n
                    for n in result
                    if self._norm(getattr(n, "teaching_style", None))
                    == self._norm(teaching_style)
                ]

            if interest_category:
                result = [
                    n
                    for n in result
                    if self._norm(getattr(n, "interest_category", None))
                    == self._norm(interest_category)
                ]

            # Zone bucket takes precedence; fall back to the single difficulty_level
            # string for callers that don't supply a zone.
            if zone_difficulties:
                filtered = [
                    n
                    for n in result
                    if self._norm(getattr(n, "difficulty_level", None))
                    in zone_difficulties
                ]
                # Preserve the full result as a fallback so we never return empty
                # just because notes lack a difficulty_level tag.
                result = filtered if filtered else result
            elif difficulty_level:
                result = [
                    n
                    for n in result
                    if self._norm(getattr(n, "difficulty_level", None))
                    == self._norm(difficulty_level)
                ]

            return result

        teacher_filtered = apply_filters(teacher_notes)
        ai_filtered = apply_filters(ai_notes)

        if teacher_filtered:
            working_set = teacher_filtered
        elif ai_filtered:
            working_set = ai_filtered
        else:
            working_set = notes

        working_set = working_set[:10]

        pool_for_scoring: List[TopicNote] = list(working_set)
        uq = (user_query or "").strip()
        if uq and not vtse_authoring:
            try:
                query_embedding = get_embedding(uq[:1000])
                ranked_notes = _rank_by_similarity(
                    query_embedding, working_set, get_embedding
                )
                if not ranked_notes:
                    ranked_notes = list(working_set)
                pool_for_scoring = ranked_notes[:5]
            except Exception:
                pool_for_scoring = list(working_set)

        cc_norm = self._norm(current_concept)

        def _concept_rank(note: TopicNote) -> int:
            if concept_id is not None and getattr(note, "concept_id", None) == concept_id:
                return 0
            if not cc_norm:
                return 0
            n = self._norm(getattr(note, "concept", None))
            if n == cc_norm:
                return 0
            if not n:
                return 1
            return 2

        scored_notes = [
            (
                self._score_note(
                    n,
                    teaching_style,
                    interest_category,
                    difficulty_level,
                    current_concept=current_concept,
                    concept_id=concept_id,
                ),
                n,
            )
            for n in pool_for_scoring
        ]
        scored_notes.sort(key=lambda x: (_concept_rank(x[1]), -x[0]))
        ranked_notes = [n for _, n in scored_notes]
        if vtse_authoring and concept_id is not None:
            ranked_notes = [
                n for n in ranked_notes if getattr(n, "concept_id", None) == concept_id
            ]
        elif vtse_authoring and cc_norm:
            ranked_notes = [
                n
                for n in ranked_notes
                if self._norm(getattr(n, "concept", None)) == cc_norm
            ]

        summary_notes = [n for n in ranked_notes if n.note_type == "summary"]
        detailed_notes = [n for n in ranked_notes if n.note_type == "detailed"]
        revision_notes = [n for n in ranked_notes if n.note_type == "revision"]

        selected_notes: List[TopicNote] = []

        selected_notes.extend(summary_notes[:2])

        remaining = limit - len(selected_notes)
        if remaining > 0:
            selected_notes.extend(detailed_notes[: min(2, remaining)])

        remaining = limit - len(selected_notes)
        if remaining > 0:
            selected_notes.extend(revision_notes[:remaining])

        selected_notes = selected_notes[:limit]
        for note in selected_notes:
            # Increment usage only via $inc so in-memory embeddings are not written to MongoDB.
            emb = note.embedding
            await note.update(Inc({"usage_count": 1}))
            note.embedding = emb
        return selected_notes

    async def get_video_subtitles(
        self,
        topic_id: PydanticObjectId,
        organization_id: PydanticObjectId,
        limit: int = 3,
    ):
        filters = {
            "topic_id": topic_id,
            "organization_id": organization_id,
        }
        return await self.video_subtitle_repository.get_many(
            filters=filters,
            limit=limit,
        )

    async def get_topic_questions(
        self,
        topic_id: PydanticObjectId,
        organization_id: PydanticObjectId,
        limit: int = 3,
        curriculum_class_id: str | None = None,
        curriculum_subject_id: str | None = None,
    ):
        raw = await self.topic_question_repository.get_questions(
            topic_id,
            concept=None,
            organization_id=organization_id,
            limit=max(limit * 3, 20),
        )
        extra_ids = await self._extra_teacher_topic_storage_ids(
            topic_id,
            organization_id,
            curriculum_class_id,
            curriculum_subject_id,
        )
        for xid in extra_ids:
            more = await self.topic_question_repository.get_questions(
                xid,
                concept=None,
                organization_id=organization_id,
                limit=max(limit * 3, 20),
            )
            raw.extend(more)
        seen_q: set[PydanticObjectId] = set()
        deduped: list[Any] = []
        for q in raw:
            if q.id in seen_q:
                continue
            seen_q.add(q.id)
            deduped.append(q)
        raw = deduped
        out = [
            q
            for q in raw
            if getattr(q, "approved", False)
            and (q.organization_id is None or q.organization_id == organization_id)
        ]
        return out[:limit]

    async def build_context(
        self,
        notes: List[TopicNote],
        topic_id: PydanticObjectId | None = None,
        organization_id: PydanticObjectId | None = None,
        curriculum_class_id: str | None = None,
        curriculum_subject_id: str | None = None,
    ) -> str:
        # Cap to the top 5 most relevant notes so the context stays focused and
        # does not dilute the LLM's attention with low-relevance material.
        notes = notes[:5]

        context_parts: List[str] = []
        for note in notes:
            content = note.content_markdown.strip()
            if not content or len(content) < 10:
                continue
            # Include the concept label in the header so the LLM can see which
            # concept each note belongs to at a glance.
            concept_label = (note.concept or "general").strip()
            context_parts.append(
                f"[{note.note_type.capitalize()} — concept: {concept_label}]\n{content}\n\n"
            )

        if topic_id is not None and organization_id is not None:
            subtitles = await self.get_video_subtitles(
                topic_id, organization_id, limit=3
            )
            subtitles = subtitles[:2]
            for s in subtitles:
                text = (s.text or "")[:300]
                if text.strip():
                    context_parts.append(
                        f"[Video Explanation - Subtitle]\n{text}\n\n"
                    )

            questions = await self.get_topic_questions(
                topic_id,
                organization_id,
                limit=3,
                curriculum_class_id=curriculum_class_id,
                curriculum_subject_id=curriculum_subject_id,
            )
            questions = questions[:2]
            for q in questions:
                qtext = (q.question_text or "").strip()
                if qtext:
                    context_parts.append(
                        f"[Practice Question - For Reference Only]\n{qtext}\n\n"
                    )

        context = "".join(context_parts)

        max_chars = 3000
        if len(context) > max_chars:
            context = context[:max_chars]

        return context

    @staticmethod
    def _teaching_style_guidance(student_profile: dict | None) -> str:
        if not student_profile:
            return ""
        st = (student_profile.get("preferred_teaching_style") or "").strip().lower()
        if not st:
            return ""
        if st == "visual":
            return (
                "Teaching style is visual: use concrete examples, analogies, and comparisons; "
                "describe relationships clearly as if sketching them in words."
            )
        if st == "practical":
            return (
                "Teaching style is practical: use real-life examples, everyday situations, "
                "and short, relatable scenarios."
            )
        if st == "theory":
            return (
                "Teaching style is theory: use structured definitions, logical order, "
                "and precise terminology before examples."
            )
        return f"Adapt tone to preferred teaching style: {st}."

    @staticmethod
    def _few_shot_teaching_block() -> str:
        return """
## FEW-SHOT EXAMPLES (imitate tone and structure, do not copy verbatim):

Student: what is numerator
Tutor: The numerator is the top number in a fraction. For example, in 3/4, the 3 is the numerator — it tells how many parts you have. The denominator (bottom) tells how many equal parts make a whole.

Student: I don't get why we flip the fraction when dividing
Tutor: Let's take it in small steps. Dividing by a fraction asks "how many of those pieces fit in one unit?" Flipping gives the size of one piece, so multiplying by that reciprocal answers the question — we'll walk through one numeric example next.

---
"""

    @staticmethod
    def _strict_knowledge_boundary_block(
        current_concept_label: str,
        learned_concepts: list[str] | None,
        next_concept: str | None,
    ) -> str:
        cur = (current_concept_label or "(not specified)").strip()
        learned_list = learned_concepts or []
        learned_str = (
            ", ".join(str(x).strip() for x in learned_list if str(x).strip())
            if learned_list
            else "(none yet)"
        )
        if next_concept is not None and str(next_concept).strip():
            next_line = str(next_concept).strip()
        else:
            next_line = "(none — you are on the last concept in this sequence)"
        return f"""
## STRICT KNOWLEDGE BOUNDARY (MANDATORY):
You are teaching ONLY the concept: {cur}
You may refer to previously learned concepts: {learned_str}
DO NOT mention or use the next concept: {next_line}
DO NOT introduce any concept not already taught.
If a term belongs to a future concept, you MUST NOT use it.
"""

    async def generate_prompt(
        self,
        question: str,
        context: str,
        student_profile: dict | None = None,
        topic_name: str | None = None,
        *,
        learning_state: str = "explaining",
        user_intent: str = "UNKNOWN",
        last_answer: Optional[str] = None,
        is_followup: bool = False,
        current_concept: Optional[str] = None,
        mastery_score: Optional[float] = None,
        last_answer_correct: Optional[bool] = None,
        enforce_knowledge_boundary: bool = False,
        learned_concepts_list: Optional[list[str]] = None,
        next_concept: Optional[str] = None,
    ) -> str:
        style_instruction = ""
        interest_instruction = ""
        style_guidance = self._teaching_style_guidance(student_profile)

        if student_profile:
            if "preferred_teaching_style" in student_profile and student_profile["preferred_teaching_style"]:
                style_instruction = (
                    f"Teach in a {student_profile['preferred_teaching_style']} style."
                )

            if "interests" in student_profile and student_profile["interests"]:
                interests = ", ".join(student_profile["interests"])
                interest_instruction = (
                    f"Use examples related to: {interests} when possible."
                )

        topic_line = (
            f"Topic: {topic_name}" if topic_name else "Topic: (not specified)"
        )
        concept_line = (
            str(current_concept).strip()
            if current_concept is not None and str(current_concept).strip()
            else "(not specified)"
        )
        has_concept_lock = concept_line != "(not specified)"
        last_block = ""
        if last_answer and str(last_answer).strip():
            last_block = (
                "\n---\nPrevious tutor response (use as base if follow-up):\n"
                f"{str(last_answer).strip()[:8000]}\n"
            )
        follow_block = (
            "This is a follow-up: expand and clarify the previous explanation; do not restart from unrelated ideas."
            if is_followup
            else "This is a new message in the conversation (not a follow-up to the previous answer)."
        )

        mastery_block = ""
        if mastery_score is not None:
            mastery_block = f"""
## DIFFICULTY / MASTERY ADAPTATION:
Estimated mastery score (0–100): {mastery_score:.1f}
* If mastery is low (below about 40): simplify the explanation; use smaller steps; avoid jargon.
* If mastery is high (above about 70): be slightly more concise; skip redundant basics unless the student asks.
* If mastery is in between: balance clarity with a normal level of detail.
"""

        mistake_block = ""
        if last_answer_correct is False:
            mistake_block = """
## MISTAKE-AWARE TEACHING:
The student's last submitted answer was marked incorrect.
* Explain more carefully and patiently.
* Briefly name or paraphrase the mistake, then give the correct idea clearly.
"""

        concept_lock_block = ""
        if has_concept_lock:
            concept_lock_block = f"""
## CONCEPT LOCK:
Current concept scope: {concept_line}
* Stay strictly within this concept.
* Do NOT introduce unrelated topics or ideas outside this concept unless the student explicitly widens the scope.
"""

        few_shot = self._few_shot_teaching_block()
        style_adapt_block = (
            style_guidance
            if style_guidance
            else "Use clear, neutral teaching; still apply preferences above."
        )

        strict_boundary_block = ""
        if enforce_knowledge_boundary:
            learned_safe = learned_concepts_list or []
            if not isinstance(learned_safe, list):
                learned_safe = []
            next_safe = next_concept or "None"
            strict_boundary_block = f"""
## STRICT KNOWLEDGE BOUNDARY:

You are teaching ONLY the concept: {current_concept}

You may refer to previously learned concepts:
{', '.join(str(x) for x in learned_safe)}

DO NOT mention or use the next concept: {next_safe}

DO NOT introduce any concept not already taught.

If a term belongs to a future concept, you MUST NOT use it.
"""

        # ── Context quality check ────────────────────────────────────────────────
        # Warn the model explicitly when the notes pool is thin so it stays
        # conservative rather than hallucinating to fill the gap.
        context_chars = len((context or "").strip())
        if context_chars < 150:
            context_quality_note = (
                "\nNOTE: The notes context for this concept is very limited. "
                "Keep your response concise and simple. "
                "Do NOT fabricate facts, examples, or details not present in the context above.\n"
            )
        else:
            context_quality_note = (
                "\nBase your response strictly on the notes context provided above. "
                "Do NOT introduce facts or examples that are absent from those notes.\n"
            )

        # ── Concept anchor ───────────────────────────────────────────────────────
        # A short, hard reminder placed right before the task/question in every
        # prompt branch so the model cannot overlook the scope constraint.
        concept_anchor = (
            f"\nCurrent concept being taught: **{concept_line}**\n"
            "Do NOT go beyond this concept. Do NOT introduce future concepts.\n"
            f"When explaining, name this concept explicitly near the start of your response — "
            f"the student must know they are learning about \"{concept_line}\" right now. "
            "Do not assume the student will infer it from context.\n"
            if has_concept_lock
            else ""
        )

        # Evaluation / structured outputs: keep topic safety + prefs; avoid long teaching prose that breaks JSON.
        if user_intent == "EVALUATE":
            prompt = f"""
You are a human tutor teaching a student.

Student Intent: {user_intent}
Learning State: {learning_state}
Current Concept: {concept_line}

{strict_boundary_block}
{topic_line}

Use the following context as the ONLY source of knowledge for your evaluation.
{context_quality_note}
Context:
{context}
{concept_anchor}
Student Preferences:
{style_instruction}
{interest_instruction}

Safety (unchanged):
* If the content is unrelated to the topic, politely refuse and guide the student back to the topic.
* Do not answer questions outside the topic.

Task (follow format exactly):
{question}
"""
        elif user_intent in ("QUESTION_GENERATION", "QUIZ"):
            prompt = f"""
You are a human tutor teaching a student.

Student Intent: {user_intent}
Learning State: {learning_state}
Current Concept: {concept_line}

{strict_boundary_block}
{topic_line}

Use the following context as the ONLY source of knowledge for generating questions.
Questions MUST be based on the content in these notes — do NOT invent scenarios or facts.
{context_quality_note}
Context:
{context}
{concept_anchor}
Student Preferences:
{style_instruction}
{interest_instruction}

Safety (unchanged):
* Stay on the topic above; do not jump to unrelated subjects.
* If the question is unrelated to the topic, politely refuse and guide the student back to the topic.

Output rules:
* Follow the task below exactly (e.g. output only the question line if asked).
* Do not add a lesson or explanation unless the task explicitly asks for it.

Task:
{question}
"""
        else:
            prompt = f"""
You are a human tutor teaching a student.

{few_shot}
Student Intent: {user_intent}
Learning State: {learning_state}
Current Concept: {concept_line}

{mastery_block}{mistake_block}{concept_lock_block}{strict_boundary_block}
{follow_block}
{last_block}

---

## TONE & STYLE RULES (apply to every response):

* Write like a calm, encouraging human tutor — not a textbook.
* Use short paragraphs (2–4 sentences max per paragraph).
* Prefer simple, conversational words over formal terminology.
* Use natural bridging phrases when they fit:
  - "Let's break this down..." (before stepping through a concept)
  - "Think about it this way..." (before an analogy or reframe)
  - "You're on the right track — " (before a gentle correction)
  - "Here's the key idea: " (before the core point)
* Never string multiple such phrases together; pick one if relevant, or use none.
* Avoid bullet-point overload — use prose for explanations, bullets only for lists of steps or items.

---

## TEACHING RULES:

1. If intent is EXPLAIN:
   * Open by clearly naming the concept being taught — use the "Current Concept" value above.
     State it naturally, e.g. "Today we're looking at [concept]" or "Let's explore [concept]".
     Never leave the student to guess what they are learning.
   * After any opening hook, introduce the concept by name before going deeper.
   * Explicitly introduce and define every important term or sub-category within the concept.
     Example: if the concept is "types of animals", you must name and define terms such as
     "domestic animals" and "wild animals" — do NOT leave terminology implicit.
     Students cannot be expected to know labels they have not been taught.
   * Then explain step-by-step, starting simple.
   * Finish with a concrete example tied directly to the named concept and its key terms.

2. If student is confused (intent UNKNOWN):
   * Simplify explanation
   * Use smaller steps
   * Avoid complex language

3. If follow-up:
   * Expand previous answer
   * Clarify confusion
   * Use last_answer as base when provided above

4. NEVER ask a question unless explicitly required

5. Do NOT jump topics (unless concept lock above allows only this concept)

6. Keep explanation structured:
   * simple definition
   * example
   * quick summary

---

{topic_line}

Use the following context as the PRIMARY and ONLY knowledge source for your explanation.
{context_quality_note}
Context:
{context}
{concept_anchor}
Question:
{question}

Student Preferences:
{style_instruction}
{interest_instruction}

## STYLE ADAPTATION (if profile indicates a style, follow this closely):
{style_adapt_block}

Safety (unchanged):
* If the question is unrelated to the topic, politely refuse and guide the student back to the topic.
* Do not answer questions outside the topic.
* Only use general knowledge when the context does not cover a detail AND it is directly relevant to the current concept.

Instructions:
* Explain clearly and simply; be concrete and non-generic where possible.
* Use examples when helpful.
* Adapt explanation based on student preferences and mastery level when given.
{TEACHER_RESPONSE_PRESENTATION_SUFFIX}
"""

        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            raise ValueError("DEEPSEEK_API_KEY not set")

        url = Settings.DEEPSEEK_API_URL
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        # System prompt: personality first, then grounding rules.
        # The personality layer shapes tone and style for every response.
        # The grounding layer prevents hallucination and scope drift.
        system_prompt = (
            # ── Tutor personality ──────────────────────────────────────────────
            "You are a friendly, calm, and encouraging tutor. "
            "Always speak to the student in a warm, natural, human tone — "
            "never robotic, never overly formal. "
            "Use simple, everyday language; avoid jargon unless it is the concept being taught. "
            "Guide the student step-by-step rather than dumping information all at once. "
            "Prefer short, well-structured responses over long paragraphs. "
            "Be warm and patient when the student struggles. "
            "Be concise and slightly more direct when the student is performing well. "
            "Use natural, encouraging phrases where they fit naturally — for example: "
            "'Let's break this down', 'Think about it this way', "
            "'You're on the right track', 'Great thinking — let's take it one step further'. "
            "Never paste these phrases mechanically; use them only when they feel genuine. "
            "\n\n"
            # ── Grounding rules (mandatory) ────────────────────────────────────
            "GROUNDING RULES (mandatory): "
            "Your ONLY knowledge source for explanations and questions is the context "
            "provided in the user message. "
            "Do NOT introduce facts, concepts, or examples that are not present in "
            "the provided context. "
            "If the context is insufficient for a detail, simplify rather than inventing. "
            "Stay strictly within the concept currently being taught. "
            "Never mention concepts that belong to future parts of the curriculum."
        )
        payload = {
            "model": Settings.DEEPSEEK_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.7,
            "thinking": DEEPSEEK_THINKING_DISABLED,
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.post(url, headers=headers, json=payload)
            except Exception:
                return "Sorry, the AI service is currently unavailable. Please try again."

        if response.status_code != 200:
            return "AI service error. Please try again later."

        try:
            data = response.json()
            return data["choices"][0]["message"]["content"]
        except Exception:
            return "AI response parsing failed. Please try again."

