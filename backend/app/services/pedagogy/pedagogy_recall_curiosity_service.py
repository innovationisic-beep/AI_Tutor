"""Session recall and cluster curiosity layers — additive pre-teach pedagogy."""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional

import httpx
from beanie.odm.fields import PydanticObjectId

from app.core.config import DEEPSEEK_THINKING_DISABLED, Settings
from app.models.classroom.class_session_plan import ClassSessionPlan
from app.models.learning.sessions import Session
from app.models.progression.student_plan_progress import StudentPlanProgress
from app.repositories.board_turn_repository import BoardTurnRepository
from app.repositories.class_session_plan_repository import ClassSessionPlanRepository
from app.repositories.curriculum_cluster_repository import CurriculumClusterRepository
from app.repositories.curriculum_concept_repository import CurriculumConceptRepository
from app.repositories.session_repository import SessionRepository
from app.repositories.student_plan_progress_repository import StudentPlanProgressRepository
from app.services.curriculum.concept_pedagogy_aggregation import (
    aggregate_concept_pedagogy_bullets,
)
from app.services.handlers.teaching_transcript_service import (
    extract_teaching_facts,
    load_teaching_transcript,
)
from app.services.progression.plan_session_cluster_registry import (
    PlanSessionClusterRegistry,
)
from app.services.progression.plan_session_cluster_registry_ext import (
    PlanSessionClusterRegistryExt,
)
from app.services.language.tutor_language_policy import (
    ENGLISH,
    STAGE_CLUSTER_CURIOSITY,
    apply_language_to_system_prompt,
    resolve_mode_for_session,
)
from app.services.speech_note_dual import (
    PROSE_DUAL_RULES,
    WRITING_MODE_NOTES,
    notes_payload,
    parse_prose_dual_full,
)

_PEDAGOGY_SYSTEM = (
    "You are a warm, conversational AI tutor companion preparing a student before teaching. "
    "Write naturally and briefly. Follow formatting instructions exactly."
)


def _pedagogy_system(mode: str = ENGLISH) -> str:
    return apply_language_to_system_prompt(
        _PEDAGOGY_SYSTEM, stage=STAGE_CLUSTER_CURIOSITY, mode=mode  # type: ignore[arg-type]
    )


async def session_recall_required(
    session: Session, *, plan_repo: Optional[ClassSessionPlanRepository] = None
) -> bool:
    plan = await _resolve_plan(session, plan_repo)
    if plan is None:
        return False
    return int(getattr(plan, "sequence_number", 1) or 1) > 1


async def session_recall_blocks_cluster_intro(session: Session) -> bool:
    if bool(getattr(session, "pedagogy_session_recall_done", False)):
        return False
    return getattr(session, "progression_session_plan_id", None) is not None


class PedagogyRecallCuriosityService:
    """Session recall (session 2+) and per-cluster curiosity (zones 1–2)."""

    def __init__(
        self,
        *,
        plan_repo: Optional[ClassSessionPlanRepository] = None,
        cluster_repo: Optional[CurriculumClusterRepository] = None,
        concept_repo: Optional[CurriculumConceptRepository] = None,
        session_repo: Optional[SessionRepository] = None,
        progress_repo: Optional[StudentPlanProgressRepository] = None,
        board_turn_repo: Optional[BoardTurnRepository] = None,
    ) -> None:
        self._plans = plan_repo or ClassSessionPlanRepository()
        self._clusters = cluster_repo or CurriculumClusterRepository()
        self._concepts = concept_repo or CurriculumConceptRepository()
        self._sessions = session_repo or SessionRepository()
        self._progress = progress_repo or StudentPlanProgressRepository()
        self._board_turns = board_turn_repo or BoardTurnRepository()

    async def maybe_emit(
        self,
        session: Session,
        *,
        action: Optional[str],
        question: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        flow = str(getattr(session, "flow_state", "idle") or "idle")

        if flow == "pedagogy_session_recall":
            return await self._handle_session_recall(session, action=action, question=question)
        if flow == "pedagogy_session_recall_feedback":
            if action == "session_recall_done":
                session.pedagogy_session_recall_done = True
                session.pedagogy_recall_stage = "done"
                session.flow_state = "idle"
                await session.save()
                return None
            return {"type": "noop"}

        if flow == "pedagogy_cluster_curiosity":
            return await self._handle_cluster_curiosity(
                session, action=action, question=question
            )
        if flow == "pedagogy_cluster_curiosity_feedback":
            if action == "cluster_curiosity_done":
                cluster_idx = int(getattr(session, "current_cluster_index", 0) or 0)
                session.pedagogy_cluster_curiosity_done_for = cluster_idx
                session.pedagogy_curiosity_stage = "done"
                session.flow_state = "idle"
                await session.save()
                return None
            return {"type": "noop"}

        if not bool(getattr(session, "pedagogy_session_intro_done", False)):
            return None

        if not bool(getattr(session, "pedagogy_session_recall_done", False)):
            if await session_recall_required(session, plan_repo=self._plans):
                return await self._emit_session_recall_prompt(session)
            session.pedagogy_session_recall_done = True
            await session.save()

        cluster_idx = int(getattr(session, "current_cluster_index", 0) or 0)
        intro_done_raw = getattr(session, "pedagogy_cluster_intro_done_for", -1)
        intro_done = -1 if intro_done_raw is None else int(intro_done_raw)
        if intro_done < cluster_idx:
            return None

        curiosity_done_raw = getattr(session, "pedagogy_cluster_curiosity_done_for", -1)
        curiosity_done = -1 if curiosity_done_raw is None else int(curiosity_done_raw)
        if curiosity_done < cluster_idx:
            if await self._cluster_curiosity_applies(session, cluster_idx):
                return await self._emit_cluster_curiosity_prompt(session, cluster_idx)
            session.pedagogy_cluster_curiosity_done_for = cluster_idx
            await session.save()

        return None

    async def _handle_session_recall(
        self,
        session: Session,
        *,
        action: Optional[str],
        question: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        if action == "session_recall_done":
            return {"type": "noop"}
        answer = (question or "").strip()
        if not answer or answer == "." or answer.lower().startswith("__action:"):
            return {"type": "noop"}
        feedback = await self._build_session_recall_feedback(session, answer)
        session.pedagogy_recall_stage = "feedback"
        session.flow_state = "pedagogy_session_recall_feedback"
        await session.save()
        return {
            "type": "session_recall_feedback",
            "message": feedback,
            "flow_state": "pedagogy_session_recall_feedback",
        }

    async def _handle_cluster_curiosity(
        self,
        session: Session,
        *,
        action: Optional[str],
        question: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        if action == "cluster_curiosity_done":
            return {"type": "noop"}
        answer = (question or "").strip()
        if not answer or answer == "." or answer.lower().startswith("__action:"):
            return {"type": "noop"}
        appreciation = await self._build_cluster_curiosity_appreciation(session, answer)
        session.pedagogy_curiosity_stage = "feedback"
        session.flow_state = "pedagogy_cluster_curiosity_feedback"
        await session.save()
        out: Dict[str, Any] = {
            "type": "cluster_curiosity_feedback",
            "flow_state": "pedagogy_cluster_curiosity_feedback",
            **appreciation,
        }
        return out

    async def _emit_session_recall_prompt(self, session: Session) -> Dict[str, Any]:
        prompt = await self._generate_session_recall_question(session)
        session.pedagogy_session_recall_question = prompt
        session.pedagogy_recall_stage = "prompt"
        session.flow_state = "pedagogy_session_recall"
        await session.save()
        return {
            "type": "session_recall_prompt",
            "message": prompt,
            "flow_state": "pedagogy_session_recall",
        }

    async def _emit_cluster_curiosity_prompt(
        self, session: Session, cluster_index: int
    ) -> Dict[str, Any]:
        prompt = await self._generate_cluster_curiosity_question(session, cluster_index)
        session.pedagogy_cluster_curiosity_question = prompt
        session.pedagogy_curiosity_stage = "prompt"
        session.flow_state = "pedagogy_cluster_curiosity"
        await session.save()
        return {
            "type": "cluster_curiosity_prompt",
            "message": prompt,
            "flow_state": "pedagogy_cluster_curiosity",
        }

    async def _cluster_curiosity_applies(
        self, session: Session, cluster_index: int
    ) -> bool:
        plan = await _resolve_plan(session, self._plans)
        if plan is None:
            return True
        assigned = PlanSessionClusterRegistry.assigned_clusters(plan)
        row = next((c for c in assigned if c.cluster_index == cluster_index), None)
        if row is None:
            return True
        zone = int(row.zone_number)
        return zone in (1, 2)

    async def _generate_session_recall_question(self, session: Session) -> str:
        ctx = await self._prior_session_teaching_context(session)
        taught_block = ctx.get("teaching_block") or ""
        concepts = ctx.get("concepts") or []
        if not taught_block and not concepts:
            topic = ctx.get("prior_title") or "our last session"
            return (
                f"Before we begin, what is one thing you remember from {topic}?"
            )

        user_msg = (
            "Write ONE warm recall question for a student starting a new session.\n"
            "CRITICAL RULES:\n"
            "- Ask ONLY about the actual teaching listed below (whiteboard / VTSE).\n"
            "- Do NOT mention topics, clusters, or concepts that are not in the list.\n"
            "- Do NOT use planning bullets or session titles as question topics.\n"
            "- ONE question only. Max 35 words. End with ?\n\n"
            f"Previous session: {ctx.get('prior_title', 'Previous session')}\n\n"
            f"{taught_block}"
        )
        result = await _llm_call(user_msg, system_content=_PEDAGOGY_SYSTEM, temperature=0.5)
        cleaned = _single_question(result)
        if cleaned:
            return cleaned
        if concepts:
            return f"Before we begin, what do you remember about {concepts[0]}?"
        return "Before we begin, what is one thing you remember from our last session?"

    async def _build_session_recall_feedback(
        self, session: Session, student_answer: str
    ) -> str:
        ctx = await self._prior_session_teaching_context(session)
        question = (
            str(getattr(session, "pedagogy_session_recall_question", "") or "").strip()
        )
        taught_block = ctx.get("teaching_block") or "General prior learning."
        user_msg = (
            "A student answered a session recall question.\n\n"
            f'Recall question: "{question}"\n'
            f'Student answer: "{student_answer.strip()}"\n\n'
            "Actual teaching from the previous session (use ONLY this):\n"
            f"{taught_block}\n\n"
            "Write the tutor response in EXACTLY this format:\n"
            "EVAL: (one warm sentence — Excellent recall / Good thinking / Nice observation / "
            "You're very close — grounded in whether their answer matches what was taught)\n"
            "EXPLAIN: (1-2 short sentences: briefly connect their answer to what was actually taught; "
            "if partial or wrong, gently clarify without lecturing)\n"
            "RECAP:\n"
            "- (main takeaway 1 from actual teaching)\n"
            "- (main takeaway 2)\n"
            "- (main takeaway 3, optional)\n"
            "Max 4 RECAP bullets. Use plain language. No meta text."
        )
        result = await _llm_call(user_msg, system_content=_PEDAGOGY_SYSTEM, temperature=0.55)
        formatted = _format_recall_feedback(result)
        if formatted:
            return formatted
        return (
            "Good thinking.\n\n"
            "Previously we learned:\n\n"
            + "\n".join(f"• {c}" for c in (ctx.get("concepts") or ["key ideas from last session"])[:4])
        )

    async def _generate_cluster_curiosity_question(
        self, session: Session, cluster_index: int
    ) -> str:
        cluster_ctx = await self._upcoming_cluster_context(session, cluster_index)
        cluster_title = cluster_ctx.get("cluster_title") or f"Cluster {cluster_index + 1}"
        concepts = cluster_ctx.get("concepts") or []
        study = cluster_ctx.get("study_points") or []
        concept_label = concepts[0] if concepts else cluster_title
        fallback = f"What do you wonder about {concept_label}?"
        language_mode = await resolve_mode_for_session(session)
        user_msg = (
            "Write ONE curiosity question before teaching begins.\n"
            "CRITICAL: Ask ONLY about the upcoming cluster/concept listed below — "
            "not other session topics.\n"
            "Spark wonder; do not explain. ONE question, max 30 words, end with ?\n"
            "Output ONLY the question — no intro, no note, no JSON.\n\n"
            f"Upcoming cluster: {cluster_title}\n"
        )
        if concepts:
            user_msg += "Concepts in this cluster:\n" + "\n".join(
                f"- {c}" for c in concepts[:6]
            )
        if study:
            user_msg += "\nStudy focus:\n" + "\n".join(f"- {p}" for p in study[:5])
        result = await _llm_call(
            user_msg,
            system_content=_pedagogy_system(language_mode),
            temperature=0.55,
        )
        cleaned = _single_question(result)
        return cleaned or fallback

    async def _build_cluster_curiosity_appreciation(
        self, session: Session, student_answer: str
    ) -> Dict[str, Any]:
        """Return message (+ optional writing_mode/display_text) for feedback."""
        cluster_idx = int(getattr(session, "current_cluster_index", 0) or 0)
        cluster_ctx = await self._upcoming_cluster_context(session, cluster_idx)
        concepts = cluster_ctx.get("concepts") or []
        concept = concepts[0] if concepts else cluster_ctx.get("cluster_title") or "this"
        question = (
            str(getattr(session, "pedagogy_cluster_curiosity_question", "") or "").strip()
        )
        language_mode = await resolve_mode_for_session(session)
        user_msg = (
            "The student shared a thought before learning begins.\n"
            f'Curiosity question: "{question}"\n'
            f'Their words: "{student_answer.strip()}"\n\n'
            "TASK: Spoken text — TWO short paragraphs (max 70 words total).\n"
            "Paragraph 1: warm appreciation referencing their words "
            "(Interesting thought / Great observation / I like your reasoning).\n"
            f'Paragraph 2: one transition sentence inviting them to learn about "{concept}".\n'
            "No teaching facts. No bullet lists."
            f"{PROSE_DUAL_RULES}"
            "A good board write is a short educational takeaway — or empty writes. "
            "Never write praise or Ready/UI filler as board text."
        )
        result = await _llm_call(
            user_msg,
            system_content=_pedagogy_system(language_mode),
            temperature=0.55,
        )
        spoken, note, writing_mode, writes = parse_prose_dual_full(
            result, language=language_mode
        )
        if not spoken:
            spoken = (
                f"Interesting thought.\n\n"
                f"Let's learn about {concept}."
            )
            return {"message": spoken}
        out: Dict[str, Any] = {"message": spoken}
        if writing_mode == WRITING_MODE_NOTES:
            out.update(
                notes_payload(
                    message=spoken,
                    display_text=note,
                    writes=writes,
                    visual_type="zone0_display",
                )
            )
        return out

    async def _prior_session_teaching_context(self, session: Session) -> Dict[str, Any]:
        """Build recall context from prior session VTSE teaching — not plan bullets."""
        plan = await _resolve_plan(session, self._plans)
        out: Dict[str, Any] = {
            "prior_title": None,
            "concepts": [],
            "facts": [],
            "teaching_block": "",
        }
        if plan is None:
            return out
        seq = int(getattr(plan, "sequence_number", 1) or 1)
        if seq <= 1:
            return out

        prior_plans: List[ClassSessionPlan] = []
        if getattr(plan, "plan_scope", "catalog") == "catalog" and plan.catalog_topic_id:
            prior_plans = await self._plans.list_published_catalog_before_sequence(
                catalog_topic_id=plan.catalog_topic_id,
                sequence_number=seq,
            )
        elif plan.teacher_topic_id:
            prior_plans = await self._plans.list_published_before_sequence(
                teacher_topic_id=plan.teacher_topic_id,
                class_id=str(getattr(plan, "class_id", "") or ""),
                sequence_number=seq,
            )
        prior = next(
            (p for p in prior_plans if int(p.sequence_number) == seq - 1),
            prior_plans[-1] if prior_plans else None,
        )
        if prior is None:
            return out

        out["prior_title"] = (prior.title or f"Session {seq - 1}").strip()
        prior_session = await self._find_prior_runtime_session(session, prior.id)
        if prior_session is None:
            return out

        concepts: List[str] = []
        for c in _clean_list(getattr(prior_session, "learned_concepts", None)):
            if c not in concepts:
                concepts.append(c)
        for c in _clean_list(getattr(prior_session, "key_concepts", None)):
            if c not in concepts:
                concepts.append(c)
        out["concepts"] = concepts[:12]

        taught_steps = _clean_list(getattr(prior_session, "topic_taught_points", None))
        transcript = ""
        if getattr(prior_session, "id", None) is not None:
            try:
                transcript = await load_teaching_transcript(
                    prior_session.id,
                    prior_session,
                    scope="zone",
                )
            except Exception:
                transcript = ""
        facts = extract_teaching_facts(transcript, steps=taught_steps)
        if not facts and taught_steps:
            facts = taught_steps[:12]
        out["facts"] = facts[:16]

        block_parts: List[str] = []
        if concepts:
            block_parts.append(
                "Key concepts taught:\n" + "\n".join(f"- {c}" for c in concepts[:8])
            )
        if facts:
            block_parts.append(
                "Main ideas from whiteboard teaching:\n"
                + "\n".join(f"- {f}" for f in facts[:12])
            )
        if transcript and len(transcript) > 80:
            excerpt = transcript[:2500].strip()
            block_parts.append(f"Teaching excerpt:\n{excerpt}")
        out["teaching_block"] = "\n\n".join(block_parts).strip()
        return out

    async def _upcoming_cluster_context(
        self, session: Session, cluster_index: int
    ) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "cluster_title": None,
            "concepts": [],
            "study_points": [],
        }
        plan = await _resolve_plan(session, self._plans)
        if plan is not None:
            assigned = PlanSessionClusterRegistry.assigned_clusters(plan)
            row = next((c for c in assigned if c.cluster_index == cluster_index), None)
            if row is not None:
                out["cluster_title"] = row.display_name
                out["concepts"] = [k for k in row.runtime_keys if k.strip()]

        cluster_id = await PlanSessionClusterRegistryExt.cluster_id_for_session_cluster_index(
            session, cluster_index, plan_repo=self._plans
        )
        if cluster_id is not None:
            cluster = await self._clusters.get_by_id(cluster_id)
            if cluster is not None:
                if not out["cluster_title"]:
                    out["cluster_title"] = (cluster.title or "").strip()
                concepts = await self._concepts.list_by_cluster(
                    cluster.id,
                    organization_id=getattr(cluster, "organization_id", None),
                )
                study, _outcomes = aggregate_concept_pedagogy_bullets(concepts)
                out["study_points"] = study
        return out

    async def _find_prior_runtime_session(
        self, session: Session, prior_plan_id: PydanticObjectId
    ) -> Optional[Session]:
        history = await self._sessions.get_student_sessions(
            session.student_id,
            limit=40,
            organization_id=session.organization_id,
        )
        matches = [
            row
            for row in history
            if str(getattr(row, "progression_session_plan_id", "")) == str(prior_plan_id)
        ]
        if not matches:
            return None

        def _score(row: Session) -> tuple[int, int]:
            completed = 1 if str(getattr(row, "completion_status", "")) == "completed" else 0
            taught = len(getattr(row, "topic_taught_points", None) or [])
            learned = len(getattr(row, "learned_concepts", None) or [])
            return (completed, taught + learned)

        return max(matches, key=_score)

    async def _load_progress(self, session: Session) -> Optional[StudentPlanProgress]:
        track = getattr(session, "progression_track_key", None)
        if not track:
            return None
        return await self._progress.get_by_track(session.student_id, track)

    async def apply_flow_state(self, session: Session, result: Dict[str, Any]) -> None:
        fs = result.get("flow_state")
        if fs:
            session.flow_state = str(fs)
            await session.save()


def _format_recall_feedback(text: Optional[str]) -> str:
    if not text:
        return ""
    raw = text.strip()
    eval_m = re.search(r"EVAL:\s*(.+?)(?:\n|EXPLAIN:|$)", raw, re.I | re.S)
    explain_m = re.search(r"EXPLAIN:\s*(.+?)(?:\n|RECAP:|$)", raw, re.I | re.S)
    recap_m = re.search(r"RECAP:\s*(.+)$", raw, re.I | re.S)
    if not eval_m:
        return raw
    parts: List[str] = [eval_m.group(1).strip()]
    if explain_m and explain_m.group(1).strip():
        parts.append("")
        parts.append(explain_m.group(1).strip())
    parts.append("")
    parts.append("Previously we learned:")
    parts.append("")
    if recap_m:
        for line in recap_m.group(1).strip().splitlines():
            line = line.strip().lstrip("-•*").strip()
            if line:
                parts.append(f"• {line}")
    body = "\n".join(parts).strip()
    return body if "•" in body else ""


def _clean_list(values: Optional[List[str]]) -> List[str]:
    return [str(v).strip() for v in (values or []) if str(v).strip()]


def _single_question(text: Optional[str]) -> str:
    if not text:
        return ""
    s = text.strip().strip('"').strip("'")
    s = re.sub(r"^(question|q)\s*:\s*", "", s, flags=re.I).strip()
    if s and not s.endswith("?"):
        s = s.rstrip(".!") + "?"
    return s[:500]


async def _resolve_plan(
    session: Session, plan_repo: Optional[ClassSessionPlanRepository] = None
) -> Optional[ClassSessionPlan]:
    plan_id = getattr(session, "progression_session_plan_id", None)
    if plan_id is None:
        return None
    repo = plan_repo or ClassSessionPlanRepository()
    return await repo.get_by_id(plan_id)


async def _llm_call(
    user_content: str,
    *,
    system_content: str = _PEDAGOGY_SYSTEM,
    temperature: float = 0.5,
    timeout: float = 60.0,
) -> Optional[str]:
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        return None
    url = Settings.DEEPSEEK_API_URL
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": Settings.DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_content},
        ],
        "temperature": temperature,
        "thinking": DEEPSEEK_THINKING_DISABLED,
    }
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            choices = data.get("choices") or []
            if not choices:
                return None
            msg = choices[0].get("message") or {}
            return str(msg.get("content") or "").strip() or None
    except Exception:
        return None
