from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from beanie.odm.fields import PydanticObjectId
from pydantic import Field
from pymongo import IndexModel

from app.models.base import BaseDocument


class Session(BaseDocument):
    """One learning execution session for a student and topic. subject_id is denormalized for query performance."""

    organization_id: PydanticObjectId = Field(...)
    student_id: PydanticObjectId = Field(...)
    topic_id: PydanticObjectId = Field(...)
    subject_id: Optional[PydanticObjectId] = Field(
        default=None,
        description="Curriculum Subject id when known; null for teacher-topic-only sessions. ",
    )
    mode: Literal["explorer", "revision", "exam"] = Field(...)
    ai_model_used: str = Field(..., min_length=2, max_length=80)
    start_time: datetime = Field(...)
    end_time: Optional[datetime] = Field(default=None)
    duration_seconds: int = Field(default=0, ge=0)
    confusion_count: int = Field(default=0, ge=0)
    teachback_score: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    completion_status: Literal["in_progress", "completed", "abandoned"] = Field(
        default="in_progress"
    )
    current_mode: str = Field(default="normal")
    student_questions_active: bool = Field(
        default=False,
        description="Temporary post-concept question phase flag.",
    )
    student_questions_concept: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Concept currently open for student follow-up questions.",
    )
    current_question: Optional[str] = Field(default=None, max_length=5000)
    current_concept: Optional[str] = Field(default=None, max_length=500)
    current_concept_id: Optional[PydanticObjectId] = Field(
        default=None,
        description="Mongo id of the active curriculum concept (structured v2).",
    )
    last_question: Optional[str] = Field(default=None, max_length=5000)
    last_answer: Optional[str] = Field(default=None, max_length=12000)
    learning_state: str = Field(default="explaining")
    # Track concepts the student has been exposed to via tutor explanations/questions.
    learned_concepts: List[str] = Field(default_factory=list)
    used_question_ids: List[str] = Field(default_factory=list)
    last_questions: List[str] = Field(default_factory=list)
    quiz_target_count: Optional[int] = Field(default=None, ge=1, le=50)
    quiz_asked_count: int = Field(default=0, ge=0)
    # Resolved curriculum for this run (teacher topic when scoped, else admin topic concepts)
    key_concepts: List[str] = Field(default_factory=list)
    # Parallel Mongo ids for key_concepts (v2 manifest / structured curriculum).
    key_concept_ids: List[PydanticObjectId] = Field(default_factory=list)
    # Cluster snapshot — copied from Topic/TeacherTopic at session start.
    # None = auto-derive from key_concepts in chunks of 3–5.
    # This is a READ-ONLY view; key_concepts remains the canonical sequence.
    concept_clusters: Optional[List[List[str]]] = Field(default=None)
    # Optional org class/subject ids (strings) to match TeacherTopic rows
    curriculum_class_id: Optional[str] = Field(default=None, max_length=64)
    curriculum_subject_id: Optional[str] = Field(default=None, max_length=64)
    # Teacher-driven concept progression (index into session.key_concepts)
    current_concept_index: int = Field(default=0, ge=0)
    total_concepts: int = Field(default=0, ge=0)
    # Micro-teaching: counts completed student reply cycles for this concept while
    # teaching (0 after opening). Value MICRO_TEACH_STEP_READY_QUIZ means done → quiz.
    current_step_in_concept: int = Field(
        default=0,
        ge=0,
        le=20,
        description=(
            "Micro-teaching reply-cycle counter for the current concept; sentinel "
            "MICRO_TEACH_STEP_READY_QUIZ means ready for main quiz. Reset on concept change."
        ),
    )
    current_concept_correct_count: int = Field(
        default=0,
        ge=0,
        le=20,
        description=(
            "Consecutive confirmed micro-teaching answers with no missing points "
            "for the current concept. Reset on concept change."
        ),
    )
    micro_last_connection_round: int = Field(
        default=-1,
        ge=-1,
        le=30,
        description=(
            "Exchange index (vs current_step_in_concept) of last connection-style "
            "micro-teaching prompt; -1 = none. Drives periodic connection every few turns."
        ),
    )
    post_learning_streak: int = Field(
        default=0,
        ge=0,
        le=20,
        description="Deprecated — retained for document compatibility only.",
    )
    post_learning_turns_in_zone: int = Field(
        default=0,
        ge=0,
        le=50,
        description="Deprecated — retained for document compatibility only.",
    )
    zone2_gate_hold_streak: int = Field(
        default=0,
        ge=0,
        le=10,
        description="Deprecated — retained for document compatibility only.",
    )
    flow_state: str = Field(
        default="idle",
        max_length=40,
        description=(
            "idle | teaching | waiting_for_question | checking_understanding | "
            "quizzing | zone_2_entry | zone_3_entry | zone_4_entry | completed"
        ),
    )
    # Flow checkpoint runtime (flow_vertical_process playback only)
    flow_checkpoint_index: int = Field(
        default=0,
        ge=0,
        description="Count of flow checkpoints shown this concept/timeline run.",
    )
    flow_checkpoint_pending: bool = Field(
        default=False,
        description="True while timeline is paused at a flow checkpoint gate.",
    )
    flow_checkpoint_resolved: bool = Field(
        default=False,
        description="True after student continued or received clarification.",
    )
    flow_checkpoint_step_labels: List[str] = Field(
        default_factory=list,
        description="Labels for the last completed flow steps at checkpoint.",
    )
    flow_completed_node_count: int = Field(
        default=0,
        ge=0,
        description="Completed flow process nodes when last checkpoint fired.",
    )
    # Zone 1 structured concept questions (after main VTSE explanation per key concept)
    concept_questions_active: bool = Field(
        default=False,
        description="True while the 3-question loop runs for the current key concept.",
    )
    concept_question_index: int = Field(
        default=0,
        ge=0,
        le=10,
        description="0-based index of the current concept question (0..2).",
    )
    concept_question_followup: bool = Field(
        default=False,
        description="True after an answer was processed; awaiting next Q or clarification.",
    )
    concept_question_clarifying: bool = Field(
        default=False,
        description="True while student may ask follow-up confusion about the current question.",
    )
    concept_question_pending_advance: bool = Field(
        default=False,
        description="True after a correct answer; praise shown before auto-advancing to next question.",
    )
    current_concept_question_answer: Optional[str] = Field(
        default=None,
        max_length=5000,
        description="Reference answer for the active concept question (DB or AI).",
    )
    current_concept_question_type: Optional[Literal["mcq", "fill_in_blank"]] = Field(
        default=None,
        max_length=20,
        description="Active concept-check question format.",
    )
    current_concept_question_options: List[str] = Field(
        default_factory=list,
        max_length=10,
        description="MCQ options for the active concept-check question.",
    )
    concept_question_confusion_log: List[str] = Field(
        default_factory=list,
        description="Student wrong answers and clarifications during concept check (for notes).",
    )
    concept_quiz_used_facts: List[str] = Field(
        default_factory=list,
        description="Normalized fact keys already used in the current concept-check round.",
    )
    concept_notes_active: bool = Field(
        default=False,
        description="True while post-concept LLM notes await student dismiss.",
    )
    concept_notes_concept: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Key concept name for the active notes popup.",
    )
    concept_notes_markdown: Optional[str] = Field(
        default=None,
        max_length=12000,
        description="Generated markdown for the active notes popup.",
    )
    concept_notes_history: List[dict] = Field(
        default_factory=list,
        description="Appended notes per key concept: {concept, markdown}.",
    )
    # Root-cause diagnostic (prerequisite checks); does not replace session.topic_id.
    diagnostic_mode: bool = Field(default=False)
    diagnostic_step: int = Field(default=0, ge=0, le=2)
    diagnostic_topic_ids: List[str] = Field(default_factory=list)
    diagnostic_current_index: int = Field(default=0, ge=0)
    diagnostic_original_topic_id: Optional[str] = Field(
        default=None, max_length=24, description="Hex ObjectId of topic when diagnostic started."
    )
    diagnostic_pending_question: Optional[str] = Field(
        default=None, max_length=5000, description="Last diagnostic question shown to the student."
    )
    diagnostic_resume_question: Optional[str] = Field(
        default=None, max_length=8000, description="User message to resume main RAG after diagnostic."
    )
    diagnostic_attempt_count: int = Field(
        default=0,
        ge=0,
        description=(
            "Teacher quiz/wait struggle signals before prerequisite diagnostic triggers "
            "(increment per struggle; trigger at >=2)."
        ),
    )
    # Structured learning flow control fields
    current_zone: int = Field(
        default=0,
        ge=0,
        le=4,
        description="Learning zone (0–4) representing structured depth progression",
    )
    teachback_attempts: int = Field(
        default=0,
        ge=0,
        description="Number of teachback attempts for the current concept",
    )
    teachback_required: bool = Field(
        default=False,
        description="Whether a teachback step is required before progressing",
    )
    current_concept_mastered: bool = Field(
        default=False,
        description="Whether the current concept is fully mastered",
    )
    sus_score: float = Field(
        default=50.0,
        ge=0.0,
        le=100.0,
        description="Student Understanding Score (0–100); updated in real-time on quiz and teachback outcomes",
    )
    sus_correct_history: List[bool] = Field(
        default_factory=list,
        description=(
            "Rolling correctness history for SUS refinement (latest 7 answer outcomes)."
        ),
    )
    sus_streak: int = Field(
        default=0,
        ge=0,
        le=100,
        description="Consecutive correct-answer streak used by SUS refinement.",
    )
    sus_confusion_count: int = Field(
        default=0,
        ge=0,
        le=1000,
        description=(
            "Cumulative struggle marker for SUS refinement (low-score or missing-point incorrect attempts)."
        ),
    )
    sus_hint_count: int = Field(
        default=0,
        ge=0,
        le=1000,
        description="Cumulative hint/guidance usage marker used by SUS refinement.",
    )
    sus_reinforcement_done: bool = Field(
        default=False,
        description=(
            "One-time SUS reinforcement guard for current concept/cluster teachback "
            "(prevents repeated low-SUS reinforcement loops)."
        ),
    )
    clarity_sus_retry_done: bool = Field(
        default=False,
        description=(
            "One-time SUS reinforcement guard for clarity gate completion "
            "(prevents repeated low-SUS clarity retries)."
        ),
    )
    teacher_flag: bool = Field(
        default=False,
        description="Internal flag for potential teacher intervention on persistent struggle.",
    )
    # ── Zone 0 pre-flight state ───────────────────────────────────────────────
    # zone0_phase tracks progress through the Zone 0 micro-phases.
    # Values: "anchoring" → "anchor_wait" → "prereq" → "prereq_active" →
    #         "curiosity_pending" (mirror on board, awaiting zone0_mirror_done) →
    #         "curiosity" → "curiosity_wait" (Q2 shown) →
    #         "curiosity_ready" (AI reply + ready button) → "done"
    # Legacy documents may still have "curiosity_active" — treat like "curiosity_wait".
    # Once "done", current_zone is set to 1 and normal Zone 1–4 flow resumes.
    zone0_phase: str = Field(
        default="anchoring",
        max_length=20,
        description="Current Zone 0 sub-phase; 'done' means Zone 0 is complete.",
    )
    zone0_prereq_done: bool = Field(
        default=False,
        description="True once the Zone 0 prerequisite check has been resolved.",
    )
    zone0_curiosity_shown: bool = Field(
        default=False,
        description="True once the Zone 0 curiosity question has been shown.",
    )
    zone0_prereq_question: Optional[str] = Field(
        default=None,
        max_length=5000,
        description="The prerequisite question shown during Zone 0 (needed for answer evaluation).",
    )
    zone0_curiosity_question: Optional[str] = Field(
        default=None,
        max_length=5000,
        description="The Zone 0 curiosity (Q2) question text; used to respond to the student's answer.",
    )
    zone0_pending_anchor_reply: Optional[str] = Field(
        default=None,
        max_length=5000,
        description=(
            "Substantive anchor reply stashed while zone0_mirror is on the board "
            "(curiosity_pending); cleared when Q2 is emitted."
        ),
    )
    zone0_student_thread: Optional[str] = Field(
        default=None,
        max_length=200,
        description=(
            "Clipped Zone 0 curiosity reply, used only as continuity for the "
            "first teaching stage. Empty when the student did not answer."
        ),
    )
    # ── Clarity Gate (Phase 3) ────────────────────────────────────────────────
    # When active the teachback handler switches to multi-concept evaluation
    # mode.  All three fields default to off/None so existing sessions and
    # old MongoDB documents continue to work without any migration.
    clarity_gate_active: bool = Field(
        default=False,
        description=(
            "When True the teachback handler runs multi-concept clarity-gate "
            "evaluation instead of the standard single-concept path."
        ),
    )
    clarity_gate_step: Optional[int] = Field(
        default=None,
        ge=0,
        description="Number of clarity-gate evaluation rounds completed so far.",
    )
    clarity_gate_concepts: Optional[List[str]] = Field(
        default=None,
        description="Ordered list of concepts the student must explain to pass the clarity gate.",
    )
    clarity_score: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=100.0,
        description=(
            "Clarity Gate composite score (0–100) computed from coverage, "
            "evaluator understanding, and reasoning quality."
        ),
    )
    zone2_depth: Optional[str] = Field(
        default=None,
        max_length=16,
        description="Deprecated — retained for document compatibility only.",
    )
    zone_transition_from_zone: Optional[int] = Field(
        default=None,
        ge=0,
        le=4,
        description="Source zone for an in-flight zone transition gate.",
    )
    zone_transition_target_zone: Optional[int] = Field(
        default=None,
        ge=0,
        le=4,
        description="Target zone after the zone transition gate passes.",
    )
    zone_transition_complete_session: bool = Field(
        default=False,
        description="When True, session completes after the zone transition gate passes.",
    )
    zone_transition_gate_pending: bool = Field(
        default=False,
        description=(
            "When True, cluster teachback feedback was shown and the zone "
            "transition Clarity Gate will open on the next begin action."
        ),
    )
    clarity_gate_question: Optional[str] = Field(
        default=None,
        max_length=4000,
        description="Prompt shown to the student during the zone transition Clarity Gate.",
    )
    # Cluster progression (optional grouping over key_concepts; see concept_clusters).
    current_cluster_index: int = Field(
        default=0,
        ge=0,
        description="Index of the cluster aligned with current_concept_index (0-based).",
    )
    cluster_check_pending: bool = Field(
        default=False,
        description=(
            "When True, the next student message is a short cluster-level reflection "
            "before continuing deeper in the topic."
        ),
    )
    cluster_check_concepts: Optional[List[str]] = Field(
        default=None,
        description="Concepts in the cluster just completed (prompted by cluster_check).",
    )
    cluster_quiz_active: bool = Field(
        default=False,
        description="True while a cluster-level quiz batch is running.",
    )
    cluster_quiz_questions: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Generated cluster-quiz questions (2-3 questions per cluster).",
    )
    cluster_quiz_index: int = Field(
        default=0,
        ge=0,
        description="Current index in the structured cluster quiz (0..2).",
    )
    cluster_quiz_followup: bool = Field(
        default=False,
        description="True after a cluster quiz answer; awaiting next Q or clarification.",
    )
    cluster_quiz_clarifying: bool = Field(
        default=False,
        description="True while student may ask follow-up confusion about the cluster quiz question.",
    )
    cluster_quiz_pending_advance: bool = Field(
        default=False,
        description="True after a correct cluster quiz answer; praise shown before auto-advance.",
    )
    cluster_quiz_question_type: Optional[Literal["mcq", "descriptive"]] = Field(
        default=None,
        max_length=20,
        description="Active cluster-quiz question format.",
    )
    cluster_quiz_question_options: List[str] = Field(
        default_factory=list,
        max_length=10,
        description="MCQ options for the active cluster-quiz question.",
    )
    cluster_quiz_question_answer: Optional[str] = Field(
        default=None,
        max_length=5000,
        description="Reference answer for the active cluster-quiz question (DB or AI).",
    )
    cluster_quiz_confusion_log: List[str] = Field(
        default_factory=list,
        description="Wrong answers and clarifications during cluster quiz.",
    )
    cluster_quiz_used_facts: List[str] = Field(
        default_factory=list,
        description="Normalized fact keys already used in the current cluster-quiz round.",
    )
    cluster_teachback_active: bool = Field(
        default=False,
        description="True during cluster-end teachback (whiteboard panel).",
    )
    cluster_teachback_question: Optional[str] = Field(
        default=None,
        max_length=8000,
        description="Long grounded teachback prompt for the current cluster.",
    )
    cluster_teachback_phase: Literal["main", "socratic", "reteach_pending"] = Field(
        default="main",
        description=(
            "main = long teachback answer; socratic = partial-score probes; "
            "reteach_pending = weak score intro shown, VTSE re-teach not started yet."
        ),
    )
    cluster_teachback_socratic_turn: int = Field(
        default=0,
        ge=0,
        le=5,
        description="How many Socratic follow-ups completed in the current partial-score round.",
    )
    cluster_teachback_last_score: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=100.0,
        description="LLM score (0–100) from the latest cluster teachback evaluation.",
    )
    teachback_concepts: List[str] = Field(
        default_factory=list,
        description="Concept set currently being checked in teachback mode.",
    )
    asked_missing_concepts: List[str] = Field(
        default_factory=list,
        description="Cluster teachback: missing concepts already prompted to avoid repeats.",
    )
    recent_weak_concepts: List[str] = Field(
        default_factory=list,
        description="Lightweight memory of recent weak concepts (max 3).",
    )
    explained_points: List[str] = Field(
        default_factory=list,
        description="Per-concept micro-teaching points already explained to reduce repetition.",
    )
    taught_points: List[str] = Field(
        default_factory=list,
        description="Session-scoped taught idea points used for teachback alignment.",
    )
    # Cluster vs Topic taught_points separation for correct teachback and clarity gate
    cluster_taught_points: List[str] = Field(
        default_factory=list,
        description=(
            "Canonical tokens derived from curriculum for the current cluster only; "
            "reset when advancing to the next cluster. Used for cluster teachback."
        ),
    )
    topic_taught_points: List[str] = Field(
        default_factory=list,
        description=(
            "Canonical tokens accumulated across the topic (all clusters); "
            "used for clarity gate evaluation."
        ),
    )
    concept_stage: int = Field(
        default=0,
        ge=0,
        le=3,
        description="Micro-teaching progression stage: 0=intro, 1=components, 2=process, 3=outcome.",
    )
    # Optional counter for session-level Zone 2+ progression (not used during concept teachback).
    zone_round_successes: int = Field(
        default=0,
        ge=0,
        le=10,
        description="Reserved for optional Zone 2→3→4 counters after the clarity gate; unused in Zone 1 teaching.",
    )
    # ── Six-step teaching mode (Phase 4) ─────────────────────────────────────
    # None → standard RAG-based explanation (all existing sessions are unaffected).
    # "six_step" → structured template: familiarity check, real-life hook,
    #              short explanation, guided question.
    explanation_mode: Optional[str] = Field(
        default=None,
        max_length=20,
        description=(
            "Teaching mode for the explanation handler. "
            "None = standard RAG explanation. "
            "'six_step' = structured 4-step template (no LLM call)."
        ),
    )
    # ── Zone 1 Timeline V3 cache ─────────────────────────────────────────────
    # Incremental beat payload from the last zone-1 board finalization.
    # Attached by zone1_timeline_finalize.finalize_zone1_tutor_payload().
    zone1_timeline_cache: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Cached Zone 1 Timeline V3 payload for incremental beat delivery.",
    )
    zone1_board_cluster_index: Optional[int] = Field(
        default=None,
        description="Cluster index active when zone1_timeline_cache was last rebuilt.",
    )
    zone1_board_concept_id: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Concept id active when zone1_timeline_cache was last rebuilt.",
    )
    zone1_last_completed_beat_index: Optional[int] = Field(
        default=None,
        ge=0,
        description=(
            "Last VTSE beat index the student completed on the client before reload "
            "(used for partial board restore)."
        ),
    )
    student_scratchpad_notes: Optional[str] = Field(
        default=None,
        max_length=50_000,
        description=(
            "Student-authored scratchpad notes for this session (whiteboard My Notes)."
        ),
    )

    # ── Pedagogy introduction cards (pre-teaching; does not affect Zone 1) ──
    pedagogy_session_intro_done: bool = Field(
        default=False,
        description="True once the session introduction card has finished (TTS complete).",
    )
    pedagogy_cluster_intro_done_for: int = Field(
        default=-1,
        ge=-1,
        le=500,
        description="Highest cluster_index for which the cluster intro card has completed.",
    )
    pedagogy_session_recall_done: bool = Field(
        default=False,
        description="True once session recall Q&A has completed (session 2+ only).",
    )
    pedagogy_session_recall_question: Optional[str] = Field(
        default=None,
        max_length=4000,
        description="Last generated session recall question (restore).",
    )
    pedagogy_recall_stage: str = Field(
        default="none",
        max_length=20,
        description="Session recall stage: none | prompt | feedback | done.",
    )
    pedagogy_cluster_curiosity_done_for: int = Field(
        default=-1,
        ge=-1,
        le=500,
        description="Highest cluster_index for which cluster curiosity has completed.",
    )
    pedagogy_cluster_curiosity_question: Optional[str] = Field(
        default=None,
        max_length=4000,
        description="Last generated cluster curiosity question (restore).",
    )
    pedagogy_curiosity_stage: str = Field(
        default="none",
        max_length=20,
        description="Cluster curiosity stage: none | prompt | feedback | done.",
    )

    # ── Concept teaching orchestration (Story Hook / VTSE / Media-future) ──
    concept_teaching_for_index: int = Field(
        default=-1,
        ge=-1,
        le=500,
        description="current_concept_index this teaching sequence snapshot applies to.",
    )
    concept_teaching_sequence_snapshot: Optional[List[str]] = Field(
        default=None,
        description="Frozen effective teaching stages for the current concept.",
    )
    concept_teaching_stage_index: int = Field(
        default=0,
        ge=0,
        le=10,
        description="Index of the next teaching stage in the frozen sequence.",
    )
    concept_teaching_sequence_source: Optional[str] = Field(
        default=None,
        max_length=32,
        description="How the frozen sequence was chosen: manual | auto | auto_fallback.",
    )
    concept_teaching_story_hook_snapshot: Optional[Dict[str, Any]] = Field(
        default=None,
        description=(
            "Frozen story hook {title, body, teacher_intent, visuals[]} for the "
            "current concept."
        ),
    )
    concept_teaching_vtse_visuals_snapshot: Optional[Dict[str, Any]] = Field(
        default=None,
        description=(
            "Frozen VTSE image package for the current concept. None means this "
            "concept had no VTSE images when the snapshot was taken."
        ),
    )
    concept_teaching_visual_teaching_snapshot: Optional[Dict[str, Any]] = Field(
        default=None,
        description=(
            "Frozen Visual Teaching authored package (images/regions/anchors/"
            "connections) for the current concept."
        ),
    )
    concept_teaching_await_vtse_done: bool = Field(
        default=False,
        description=(
            "True after a VTSE timeline is attached until playback completion "
            "is accepted. FE sends __action:concept_vtse_stage_done with timeline identity."
        ),
    )
    concept_vtse_opening_status: str = Field(
        default="unclaimed",
        max_length=24,
        description=(
            "Atomic VTSE opening ownership for the current concept: "
            "unclaimed | starting | ready | failed (failed is retryable)."
        ),
    )
    concept_vtse_opening_for_index: int = Field(
        default=-1,
        ge=-1,
        le=500,
        description="current_concept_index this VTSE opening claim applies to.",
    )

    # ── Story Hook bounded AI runtime (plan generated once per concept) ───────
    story_hook_for_index: int = Field(
        default=-1,
        ge=-1,
        le=500,
        description="current_concept_index this Story Hook plan applies to.",
    )
    story_hook_plan: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Backend-validated StoryHookPlan {steps[], language, source}.",
    )
    story_hook_step_index: int = Field(
        default=0,
        ge=0,
        le=50,
        description="Index of the next Story Hook step to emit.",
    )
    story_hook_status: str = Field(
        default="idle",
        max_length=24,
        description="idle | playing | waiting_for_student | done | failed.",
    )
    story_hook_pending_question: Optional[str] = Field(
        default=None,
        max_length=400,
        description="Question the student is currently answering (restore).",
    )
    story_hook_qa: List[Dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Conversational Q&A log [{question, answer, reply}]. Not mastery-scored."
        ),
    )
    story_hook_language: str = Field(
        default="english",
        max_length=16,
        description="Language mode the current plan was generated in.",
    )

    # ── Visual Teaching runtime (plan frozen at stage start) ──────────────────
    visual_teaching_for_index: int = Field(
        default=-1,
        ge=-1,
        le=500,
        description="current_concept_index this Visual Teaching plan applies to.",
    )
    visual_teaching_plan: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Backend-validated VisualTeachingPlan.",
    )
    visual_teaching_scene_index: int = Field(
        default=0,
        ge=0,
        le=50,
        description="Current scene index within the Visual Teaching plan.",
    )
    visual_teaching_beat_index: int = Field(
        default=0,
        ge=0,
        le=50,
        description="Current beat index within the current scene.",
    )
    visual_teaching_sentence_index: int = Field(
        default=-1,
        ge=-1,
        le=500,
        description="Last completed sentence index in the current beat (-1 = beat start).",
    )
    visual_teaching_status: str = Field(
        default="idle",
        max_length=24,
        description="idle | playing | done | failed.",
    )
    visual_teaching_skipped_scenes: List[int] = Field(
        default_factory=list,
        description="Scene indexes skipped due to missing/unreadable binaries.",
    )

    # ── Phase 3B.2: multi-session plan progression (does not affect Zone 1) ───
    progression_track_key: Optional[str] = Field(default=None, max_length=200)
    progression_session_plan_id: Optional[PydanticObjectId] = Field(default=None)
    progression_class_instance_id: Optional[PydanticObjectId] = Field(default=None)

    # ── Phase 7: Interactive retrieval state ─────────────────────────────────
    # retrieval_active is set for exactly ONE turn when a spaced-retrieval
    # recall question is prepended to an explanation.  The student's next
    # message is evaluated as a recall answer and the flag is cleared.
    # Clarity Gate always has higher priority: retrieval_active is forced to
    # False whenever clarity_gate_active is set to True.
    retrieval_active: bool = Field(
        default=False,
        description=(
            "When True the next student message is evaluated as an answer to "
            "the spaced-retrieval recall question shown in the previous turn."
        ),
    )
    retrieval_concept: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Concept name used in the last spaced-retrieval recall prompt.",
    )

    class Settings:
        name = "sessions"
        indexes = [
            IndexModel([("organization_id", 1), ("student_id", 1)]),
            IndexModel([("organization_id", 1), ("topic_id", 1)]),
            IndexModel([("organization_id", 1), ("subject_id", 1)]),
            IndexModel(
                [("student_id", 1), ("topic_id", 1), ("completion_status", 1)]
            ),
            # One in_progress session per (student, topic, org); prevents duplicate inserts under concurrency.
            IndexModel(
                [("student_id", 1), ("topic_id", 1), ("organization_id", 1)],
                name="uq_in_progress_student_topic_org",
                unique=True,
                partialFilterExpression={"completion_status": "in_progress"},
            ),
        ]
