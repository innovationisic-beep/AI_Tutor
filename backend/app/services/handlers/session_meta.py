"""
Optional session metadata for teacher-progression UIs (zones + clusters).

Read-only helpers — never mutates session state.
"""

from __future__ import annotations

from typing import Any, Optional

from app.core.constants import MICRO_TEACH_STEP_READY_QUIZ
from app.services.handlers.cluster_utils import flat_index_is_last_in_its_cluster, resolve_clusters
from app.services.handlers.micro_interaction_meta import extract_micro_interaction_prompt


def _debug_bloom_from_sus(sus_score: float) -> str:
    # DEBUG ONLY — remove later
    if sus_score < 40.0:
        return "LOW"
    if sus_score > 70.0:
        return "HIGH"
    return "MEDIUM"


def build_teacher_session_meta(session: Any, topic: Any) -> Optional[dict[str, Any]]:
    """
    Return UI metadata for session UIs.

    Shape matches the optional ``meta`` contract on tutor responses:
      zone, cluster_index, total_clusters, concept_index, total_concepts,
      micro_quiz_hold (0|1): 1 = defer auto quiz trigger; micro-teaching awaits chat.
      micro_interaction_prompt: learner-facing question extracted from current_question.
    """
    total = int(getattr(session, "total_concepts", 0) or 0)

    kc = list(getattr(session, "key_concepts", None) or [])
    if not kc and topic is not None:
        kc = [
            str(c).strip()
            for c in (getattr(topic, "key_concepts", None) or [])
            if c is not None and str(c).strip()
        ]
    clusters = resolve_clusters(kc, getattr(session, "concept_clusters", None)) if total > 0 else []
    n_clusters = max(1, len(clusters)) if clusters else 1

    micro_hold = 0
    if getattr(session, "explanation_mode", None) != "six_step":
        if int(getattr(session, "current_zone", 0) or 0) in (1, 2):
            cq_active = bool(getattr(session, "concept_questions_active", False))
            cluster_q_active = bool(getattr(session, "cluster_quiz_active", False))
            cq_q = (getattr(session, "current_question", None) or "").strip()
            cq_pending = bool(getattr(session, "concept_question_pending_advance", False))
            cq_clarifying = bool(
                getattr(session, "concept_question_clarifying", False)
            )
            cluster_pending = bool(
                getattr(session, "cluster_quiz_pending_advance", False)
            )
            cluster_clarifying = bool(
                getattr(session, "cluster_quiz_clarifying", False)
            )
            cluster_tb_active = bool(
                getattr(session, "cluster_teachback_active", False)
            )
            if (
                cq_active
                and cq_q
                and not bool(getattr(session, "concept_question_followup", False))
                and not cq_pending
                and not cq_clarifying
            ):
                micro_hold = 1
            elif (
                cluster_tb_active
                and cq_q
                and str(getattr(session, "flow_state", "") or "") == "teachback"
            ):
                micro_hold = 1
            elif (
                cluster_q_active
                and cq_q
                and not bool(getattr(session, "cluster_quiz_followup", False))
                and not cluster_pending
                and not cluster_clarifying
            ):
                micro_hold = 1
            else:
                step = int(getattr(session, "current_step_in_concept", 0) or 0)
                if step < MICRO_TEACH_STEP_READY_QUIZ and cq_q and not cq_active:
                    micro_hold = 1
    # DEBUG ONLY — remove later: enforce visible fallback to avoid undefined depth in UI.
    _z2_depth = str(getattr(session, "zone2_depth", "medium") or "medium").strip().lower()
    if _z2_depth not in ("shallow", "medium", "deep"):
        _z2_depth = "medium"

    meta = {
        "zone": int(getattr(session, "current_zone", 0) or 0),
        "cluster_index": int(getattr(session, "current_cluster_index", 0) or 0),
        "total_clusters": int(n_clusters),
        "concept_index": int(getattr(session, "current_concept_index", 0) or 0),
        "total_concepts": int(total),
        "cluster_quiz_ready": bool(
            flat_index_is_last_in_its_cluster(
                int(getattr(session, "current_concept_index", 0) or 0),
                clusters,
            )
        ) if total > 0 else False,
        "micro_quiz_hold": micro_hold,
        "concept_teaching_await_vtse_done": (
            1 if bool(getattr(session, "concept_teaching_await_vtse_done", False)) else 0
        ),
        "concept_vtse_opening_status": (
            str(getattr(session, "concept_vtse_opening_status", "unclaimed") or "unclaimed")
            .strip()
            .lower()
            or "unclaimed"
        ),
        "story_hook_status": (
            str(getattr(session, "story_hook_status", "idle") or "idle").strip()
            or "idle"
        ),
        "story_hook_awaiting": (
            str(getattr(session, "story_hook_status", "") or "") == "waiting_for_student"
        ),
        "visual_teaching_status": (
            str(getattr(session, "visual_teaching_status", "idle") or "idle").strip()
            or "idle"
        ),
        "student_questions_active": bool(
            getattr(session, "student_questions_active", False)
        ),
        "concept_questions_active": bool(
            getattr(session, "concept_questions_active", False)
        ),
        "concept_question_index": int(getattr(session, "concept_question_index", 0) or 0),
        "concept_question_followup": bool(
            getattr(session, "concept_question_followup", False)
        ),
        "concept_question_clarifying": bool(
            getattr(session, "concept_question_clarifying", False)
        ),
        "concept_question_pending_advance": bool(
            getattr(session, "concept_question_pending_advance", False)
        ),
        "concept_question_type": (
            str(getattr(session, "current_concept_question_type", "") or "").strip()
            or None
        ),
        "concept_question_options": [
            str(o).strip()
            for o in (getattr(session, "current_concept_question_options", None) or [])
            if str(o).strip()
        ],
        "concept_notes_active": bool(getattr(session, "concept_notes_active", False)),
        "concept_notes_concept": (
            str(getattr(session, "concept_notes_concept", "") or "").strip() or None
        ),
        "concept_notes_markdown": (
            str(getattr(session, "concept_notes_markdown", "") or "").strip() or None
        ),
        "concept_notes_history": [
            {
                "concept": str(item.get("concept") or "").strip(),
                "markdown": str(item.get("markdown") or "").strip(),
            }
            for item in (getattr(session, "concept_notes_history", None) or [])
            if isinstance(item, dict)
            and str(item.get("concept") or "").strip()
            and str(item.get("markdown") or "").strip()
        ],
        "cluster_quiz_active": bool(getattr(session, "cluster_quiz_active", False)),
        "cluster_quiz_index": int(getattr(session, "cluster_quiz_index", 0) or 0),
        "cluster_quiz_followup": bool(
            getattr(session, "cluster_quiz_followup", False)
        ),
        "cluster_quiz_clarifying": bool(
            getattr(session, "cluster_quiz_clarifying", False)
        ),
        "cluster_quiz_pending_advance": bool(
            getattr(session, "cluster_quiz_pending_advance", False)
        ),
        "cluster_quiz_type": (
            str(getattr(session, "cluster_quiz_question_type", "") or "").strip()
            or None
        ),
        "cluster_quiz_options": [
            str(o).strip()
            for o in (getattr(session, "cluster_quiz_question_options", None) or [])
            if str(o).strip()
        ],
        "cluster_teachback_active": bool(
            getattr(session, "cluster_teachback_active", False)
        ),
        "cluster_teachback_question": (
            str(getattr(session, "cluster_teachback_question", "") or "").strip()
            or None
        ),
        "cluster_teachback_phase": (
            str(getattr(session, "cluster_teachback_phase", "main") or "main").strip()
            or "main"
        ),
        "zone_transition_gate_pending": bool(
            getattr(session, "zone_transition_gate_pending", False)
        ),
        "clarity_gate_active": bool(getattr(session, "clarity_gate_active", False)),
        # DEBUG ONLY — remove later
        "sus_score": float(getattr(session, "sus_score", 50.0) or 50.0),
        # DEBUG ONLY — remove later
        "bloom_level": _debug_bloom_from_sus(
            float(getattr(session, "sus_score", 50.0) or 50.0)
        ),
        # DEBUG ONLY — remove later
        "zone2_depth": _z2_depth,
    }
    _clarity_score = getattr(session, "clarity_score", None)
    if _clarity_score is not None:
        # DEBUG ONLY — remove later
        meta["clarity_score"] = float(_clarity_score)
    if micro_hold:
        prompt = extract_micro_interaction_prompt(
            getattr(session, "current_question", None),
        )
        if prompt:
            meta["micro_interaction_prompt"] = prompt
    # Concept Check: always expose stem when armed, even if hold is briefly 0
    # (follow-up / clarifying). FE panel ownership depends on this field.
    if bool(getattr(session, "concept_questions_active", False)):
        cq_prompt = extract_micro_interaction_prompt(
            getattr(session, "current_question", None),
        )
        if cq_prompt:
            meta["micro_interaction_prompt"] = cq_prompt
            meta["current_question"] = cq_prompt
    # Always emit so FE merge can clear stale pending=true after continue ack.
    meta["flow_checkpoint_pending"] = bool(
        getattr(session, "flow_checkpoint_pending", False)
    )
    if meta["flow_checkpoint_pending"]:
        fc_labels = list(getattr(session, "flow_checkpoint_step_labels", None) or [])
        if fc_labels:
            meta["flow_checkpoint_step_labels"] = fc_labels
    flow_state = str(getattr(session, "flow_state", "") or "").strip()
    if flow_state:
        meta["flow_state"] = flow_state
    # Waiting for VTSE board TTS before Story Hook / Visual Teaching — never hold for micro input.
    # Do NOT wipe Concept Check stems once questions are armed (await cleared).
    if (
        meta.get("concept_teaching_await_vtse_done") == 1
        or flow_state
        in ("concept_story_hook", "concept_visual_teaching")
    ) and not bool(getattr(session, "concept_questions_active", False)):
        meta["micro_quiz_hold"] = 0
        meta.pop("micro_interaction_prompt", None)
        meta.pop("current_question", None)
    return meta
