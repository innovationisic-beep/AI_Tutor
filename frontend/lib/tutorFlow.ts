import type { TutorResponse, TutorActionButton, TutorSessionMeta } from "./types";
import { protectConceptCheckMeta } from "@/lib/learning/conceptCheckOwnership";

export type ChatFlowState =
  | "idle"
  | "teaching"
  | "waiting_for_question"
  | "checking_understanding"
  | "quizzing"
  | "completed"
  | "explaining"
  | "zone0_anchor"
  | "zone0_prereq"
  | "zone0_curiosity"
  | "zone0_mirror"
  | "pedagogy_session_intro"
  | "pedagogy_cluster_intro"
  | "pedagogy_session_recall"
  | "pedagogy_session_recall_feedback"
  | "pedagogy_cluster_curiosity"
  | "pedagogy_cluster_curiosity_feedback"
  | "concept_story_hook"
  | "concept_visual_teaching"
  | "concept_vtse_opening"
  | "concept_questions"
  | "cluster_quiz"
  | "zone_2_entry"
  | "zone_3_entry"
  | "zone_4_entry";

export type SessionUiState = {
  flowState: ChatFlowState;
  currentConcept: string | undefined;
  buttons: TutorActionButton[];
  activeQuiz: { intro: string; question: string } | null;
  /** From GET /sessions/active when teacher progression is enabled */
  lessonProgress: { currentIndex: number; total: number } | null;
  /** Current learning zone (0–4); 0 = Zone 0 warm-up */
  currentZone: number;
  /** Optional cluster + concept indices from backend ``meta`` */
  sessionMeta: TutorSessionMeta | null;
};

export const INITIAL_UI: SessionUiState = {
  flowState: "zone0_anchor",
  currentConcept: undefined,
  buttons: [],
  activeQuiz: null,
  lessonProgress: null,
  currentZone: 0,
  sessionMeta: null,
};

export function flowStateFromBackend(
  flowState: string | undefined,
  meta: TutorSessionMeta | null | undefined
): ChatFlowState | null {
  if (meta?.concept_questions_active) return "concept_questions";
  if (meta?.cluster_quiz_active) return "cluster_quiz";
  const fs = (flowState || meta?.flow_state || "").trim().toLowerCase();
  switch (fs) {
    case "idle":
      return "idle";
    case "explaining":
      return "explaining";
    case "waiting_for_question":
      return "waiting_for_question";
    case "quizzing":
      return "quizzing";
    case "completed":
      return "completed";
    case "zone_2_entry":
      return "idle";
    case "zone_3_entry":
      return "zone_3_entry";
    case "zone_4_entry":
      return "zone_4_entry";
    case "pedagogy_session_intro":
      return "pedagogy_session_intro";
    case "pedagogy_cluster_intro":
      return "pedagogy_cluster_intro";
    case "pedagogy_session_recall":
      return "pedagogy_session_recall";
    case "pedagogy_session_recall_feedback":
      return "pedagogy_session_recall_feedback";
    case "pedagogy_cluster_curiosity":
      return "pedagogy_cluster_curiosity";
    case "pedagogy_cluster_curiosity_feedback":
      return "pedagogy_cluster_curiosity_feedback";
    case "zone0_mirror":
      return "zone0_mirror";
    case "concept_story_hook":
      return "concept_story_hook";
    case "concept_visual_teaching":
      return "concept_visual_teaching";
    case "concept_vtse_opening":
      return "concept_vtse_opening";
    default:
      return null;
  }
}

export function inferFlowState(res: TutorResponse): ChatFlowState {
  switch (res.type) {
    case "start":
    case "feedback":
      return "idle";
    case "understanding_check":
      return "checking_understanding";
    case "question_prompt":
    case "question_answered":
      return "waiting_for_question";
    case "quiz":
      return "quizzing";
    case "completed":
      return "completed";
    case "zone0_anchor":
      return "zone0_anchor";
    case "zone0_prereq":
      return "zone0_prereq";
    case "zone0_curiosity":
      return "zone0_curiosity";
    case "zone0_mirror":
      return "zone0_mirror";
    case "session_intro_card":
      return "pedagogy_session_intro";
    case "cluster_intro_card":
      return "pedagogy_cluster_intro";
    case "session_recall_prompt":
      return "pedagogy_session_recall";
    case "session_recall_feedback":
      return "pedagogy_session_recall_feedback";
    case "cluster_curiosity_prompt":
      return "pedagogy_cluster_curiosity";
    case "cluster_curiosity_feedback":
      return "pedagogy_cluster_curiosity_feedback";
    case "concept_story_hook":
      return "concept_story_hook";
    case "concept_visual_teaching":
      return "concept_visual_teaching";
    case "visual_teaching_sentence_ack":
      // Never derive pedagogical flow from sentence checkpoints.
      return "concept_visual_teaching";
    case "visual_teaching_advance_ack":
      return "concept_visual_teaching";
    case "vtse_opening_ack":
      return "concept_vtse_opening";
    case "concept_question":
      return "concept_questions";
    case "concept_notes":
      return "explaining";
    case "teachback_passed":
      return "idle";
    case "zone_2_entry_ready":
      return "zone_2_entry";
    case "zone_3_entry_ready":
      return "zone_3_entry";
    case "zone_4_entry_ready":
      return "zone_4_entry";
    case "root_cause":
    case "explanation":
    default:
      return "explaining";
  }
}

export function deriveSessionUi(
  res: TutorResponse,
  prev?: SessionUiState
): SessionUiState {
  const flowState = inferFlowState(res);
  let buttons: TutorActionButton[] = [];
  let currentConcept: string | undefined;
  if ("buttons" in res && Array.isArray(res.buttons)) {
    buttons = res.buttons;
  }
  if ("currentConcept" in res && res.currentConcept) {
    currentConcept = res.currentConcept;
  } else if ("current_concept" in res && (res as { current_concept?: string }).current_concept) {
    currentConcept = (res as { current_concept?: string }).current_concept;
  } else if (prev?.currentConcept) {
    currentConcept = prev.currentConcept;
  }
  let activeQuiz: SessionUiState["activeQuiz"] = null;
  if (res.type === "quiz") {
    activeQuiz = { intro: res.message, question: res.question };
    buttons = [];
  }
  if (res.type === "zone0_curiosity") {
    activeQuiz = null;
    buttons = Array.isArray(res.buttons) ? res.buttons : [];
  }
  if (res.type === "zone0_prereq") {
    activeQuiz = null;
    buttons = [];
  }
  if (res.type === "zone0_anchor") {
    activeQuiz = null;
    buttons = [];
  }
  if (res.type === "completed") {
    buttons = [];
    activeQuiz = null;
  }
  const metaFromRes = (res as { meta?: TutorSessionMeta }).meta;
  // Merge so a partial ``meta`` on one response does not drop fields (e.g. clarity_score).
  const prevMeta = prev?.sessionMeta ?? null;
  let sessionMeta =
    metaFromRes != null && prevMeta != null
      ? { ...prevMeta, ...metaFromRes }
      : (metaFromRes ?? prevMeta);
  // concept_question response: ensure stem is present even if meta omitted prompt.
  if (res.type === "concept_question") {
    const stem =
      (res.question || "").trim() ||
      (res.message || "").trim() ||
      (sessionMeta?.micro_interaction_prompt || "").trim();
    sessionMeta = {
      ...(sessionMeta ?? {
        zone: prev?.currentZone ?? 1,
        cluster_index: 0,
        total_clusters: 1,
        concept_index: 0,
        total_concepts: 1,
      }),
      concept_questions_active: true,
      concept_teaching_await_vtse_done: 0,
      micro_quiz_hold: 1,
      ...(stem
        ? { micro_interaction_prompt: stem, current_question: stem }
        : {}),
      flow_state: "concept_questions",
    };
  }
  sessionMeta = protectConceptCheckMeta(prevMeta, sessionMeta, res) ?? sessionMeta;
  const mergedMetaBase =
    sessionMeta?.concept_question_type === "fill_in_blank"
      ? { ...sessionMeta, concept_question_options: [] as string[] }
      : sessionMeta?.cluster_quiz_type === "descriptive"
        ? { ...sessionMeta, cluster_quiz_options: [] as string[] }
        : sessionMeta;
  // teachback_passed / completed clear cluster gates server-side; response often omits meta.
  const mergedMeta =
    (res.type === "teachback_passed" || res.type === "completed") && mergedMetaBase
      ? {
          ...mergedMetaBase,
          cluster_teachback_active: false,
          cluster_quiz_active: false,
          cluster_quiz_ready: false,
        }
      : mergedMetaBase;
  if (mergedMeta?.concept_questions_active) {
    activeQuiz = null;
    if (
      res.type === "feedback" ||
      (res.type === "explanation" && "buttons" in res && Array.isArray(res.buttons))
    ) {
      buttons = Array.isArray((res as { buttons?: TutorActionButton[] }).buttons)
        ? (res as { buttons: TutorActionButton[] }).buttons
        : [];
    }
    if (mergedMeta.concept_question_pending_advance) {
      buttons = [];
    }
    buttons = relabelConceptNextButton(
      buttons,
      mergedMeta.concept_question_index
    );
  }
  if (mergedMeta?.cluster_quiz_active) {
    activeQuiz = null;
    if (
      res.type === "feedback" ||
      (res.type === "explanation" && "buttons" in res && Array.isArray(res.buttons))
    ) {
      buttons = Array.isArray((res as { buttons?: TutorActionButton[] }).buttons)
        ? (res as { buttons: TutorActionButton[] }).buttons
        : [];
    }
    if (mergedMeta.cluster_quiz_pending_advance) {
      buttons = [];
    }
    buttons = relabelClusterNextButton(
      buttons,
      mergedMeta.cluster_quiz_index
    );
  }
  if (
    !mergedMeta?.concept_questions_active &&
    prev?.sessionMeta?.concept_questions_active
  ) {
    buttons = [];
  }
  const currentZone =
    metaFromRes && Number.isFinite(metaFromRes.zone)
      ? metaFromRes.zone
      : prev?.currentZone ?? 0;
  let resolvedFlow = flowState;
  if (mergedMeta?.concept_questions_active) {
    resolvedFlow = "concept_questions";
  } else if (mergedMeta?.cluster_quiz_active) {
    resolvedFlow = "cluster_quiz";
  } else if (
    res.type === "feedback" &&
    res.correct === true &&
    !mergedMeta?.concept_questions_active &&
    prev?.sessionMeta?.concept_questions_active
  ) {
    resolvedFlow = "idle";
  } else if (res.type === "teachback_passed") {
    resolvedFlow = "idle";
  } else if (
    res.type === "visual_teaching_sentence_ack" ||
    res.type === "visual_teaching_advance_ack"
  ) {
    // Sentence / advance acks are state-sync only — never leave Visual Teaching.
    resolvedFlow = "concept_visual_teaching";
  } else if (res.type === "vtse_opening_ack") {
    const ackFlow =
      "flow_state" in res && typeof res.flow_state === "string"
        ? flowStateFromBackend(res.flow_state, mergedMeta)
        : null;
    resolvedFlow = ackFlow ?? "concept_vtse_opening";
  } else if (
    res.type === "noop" &&
    prev?.flowState &&
    (prev.flowState === "pedagogy_session_intro" ||
      prev.flowState === "pedagogy_cluster_intro" ||
      prev.flowState === "pedagogy_session_recall" ||
      prev.flowState === "pedagogy_session_recall_feedback" ||
      prev.flowState === "pedagogy_cluster_curiosity" ||
      prev.flowState === "pedagogy_cluster_curiosity_feedback" ||
      prev.flowState === "zone0_mirror" ||
      prev.flowState === "concept_visual_teaching" ||
      prev.flowState === "concept_vtse_opening")
  ) {
    // Keep pedagogy waits sticky on noop. Also sticky for Visual Teaching so a
    // legacy sentence noop cannot flip concept_visual_teaching → explaining.
    // Story Hook must NOT stick here — a failed/empty advance would strand
    // the student before VTSE.
    resolvedFlow = prev.flowState;
  }
  return {
    flowState: resolvedFlow,
    currentConcept,
    buttons,
    activeQuiz,
    lessonProgress: prev?.lessonProgress ?? null,
    currentZone,
    sessionMeta: mergedMeta,
  };
}

/** After restore: backend meta overrides inferred flow from last chat row. */
export function applyRestoredSessionMeta(
  ui: SessionUiState,
  meta: TutorSessionMeta | null | undefined,
  backendFlow: ChatFlowState | null
): SessionUiState {
  if (!meta) {
    return backendFlow ? { ...ui, flowState: backendFlow } : ui;
  }
  let next: SessionUiState = {
    ...ui,
    sessionMeta: ui.sessionMeta ? { ...ui.sessionMeta, ...meta } : meta,
    currentZone: Number.isFinite(meta.zone) ? meta.zone : ui.currentZone,
  };
  next = {
    ...next,
    sessionMeta:
      protectConceptCheckMeta(ui.sessionMeta, next.sessionMeta, {
        type: "noop",
      }) ?? next.sessionMeta,
  };
  if (next.sessionMeta?.concept_questions_active) {
    next = { ...next, flowState: "concept_questions", activeQuiz: null };
  } else if (meta.concept_questions_active) {
    next = { ...next, flowState: "concept_questions", activeQuiz: null };
  } else if (meta.cluster_quiz_active) {
    next = { ...next, flowState: "cluster_quiz", activeQuiz: null };
  } else if (Number(meta.zone) === 0) {
    next = { ...next, activeQuiz: null };
  } else if (meta.micro_quiz_hold === 1) {
    next = { ...next, flowState: "explaining", buttons: [] };
  } else if (backendFlow === "zone_2_entry") {
    next = { ...next, flowState: "idle", activeQuiz: null };
  } else if (backendFlow) {
    next = { ...next, flowState: backendFlow };
  }
  if (meta.concept_question_pending_advance) {
    next = { ...next, buttons: [] };
  }
  if (meta.cluster_quiz_pending_advance) {
    next = { ...next, buttons: [] };
  }
  return next;
}

export function mainInputEnabled(ui: SessionUiState): boolean {
  if (ui.flowState === "completed") return false;
  // Story Hook asked a conversational question — the student answers in chat.
  if (ui.flowState === "concept_story_hook") {
    return ui.sessionMeta?.story_hook_awaiting === true;
  }
  if (ui.flowState === "concept_visual_teaching") {
    return false;
  }
  if (
    ui.flowState === "zone_2_entry" ||
    ui.flowState === "zone_3_entry" ||
    ui.flowState === "zone_4_entry" ||
    ui.flowState === "pedagogy_session_intro" ||
    ui.flowState === "pedagogy_cluster_intro" ||
    ui.flowState === "pedagogy_session_recall_feedback" ||
    ui.flowState === "pedagogy_cluster_curiosity_feedback" ||
    ui.flowState === "zone0_mirror"
  ) {
    return false;
  }
  if (
    ui.flowState === "pedagogy_session_recall" ||
    ui.flowState === "pedagogy_cluster_curiosity"
  ) {
    return true;
  }
  if (ui.activeQuiz !== null) return false;
  // Zone 0 anchor: student answers the opening question in chat before continuing.
  if (ui.flowState === "zone0_anchor") return true;
  // Zone 0 prereq uses the quiz card — main input box stays hidden.
  if (ui.flowState === "zone0_prereq") return true;
  // Zone 0 curiosity — student can share their thoughts freely.
  if (ui.flowState === "zone0_curiosity") return true;
  if (ui.flowState === "waiting_for_question") return true;
  if (ui.flowState === "concept_questions") {
    if (ui.sessionMeta?.concept_question_clarifying) return true;
    if (ui.sessionMeta?.concept_question_followup) return false;
    if (ui.sessionMeta?.micro_quiz_hold === 1) {
      if (
        ui.sessionMeta.concept_question_type === "mcq" &&
        (ui.sessionMeta.concept_question_options?.length ?? 0) >= 2
      ) {
        return false;
      }
      return true;
    }
    return ui.buttons.length === 0;
  }
  if (ui.flowState === "cluster_quiz") {
    if (ui.sessionMeta?.cluster_quiz_clarifying) return true;
    if (ui.sessionMeta?.cluster_quiz_followup) return false;
    if (ui.sessionMeta?.micro_quiz_hold === 1) {
      if (
        ui.sessionMeta.cluster_quiz_type === "mcq" &&
        (ui.sessionMeta.cluster_quiz_options?.length ?? 0) >= 2
      ) {
        return false;
      }
      return true;
    }
    return ui.buttons.length === 0;
  }
  /* Typing only when there are no lesson action buttons. */
  if (ui.flowState === "explaining" && ui.buttons.length === 0) return true;
  if (ui.flowState === "idle" && ui.buttons.length === 0) return true;
  return false;
}

export const CONCEPT_QUESTIONS_PER_CONCEPT = 3;
export const CLUSTER_QUESTIONS_PER_CLUSTER = 3;

/** Last concept question uses "I understand" (no "next question"). */
export function relabelConceptNextButton(
  buttons: TutorActionButton[],
  questionIndex: number | undefined
): TutorActionButton[] {
  if (
    questionIndex == null ||
    questionIndex < CONCEPT_QUESTIONS_PER_CONCEPT - 1
  ) {
    return buttons;
  }
  return buttons.map((b) =>
    b.id === "concept_q_next" ? { ...b, label: "I understand" } : b
  );
}

export function relabelClusterNextButton(
  buttons: TutorActionButton[],
  questionIndex: number | undefined
): TutorActionButton[] {
  if (
    questionIndex == null ||
    questionIndex < CLUSTER_QUESTIONS_PER_CLUSTER - 1
  ) {
    return buttons;
  }
  return buttons.map((b) =>
    b.id === "cluster_q_next" ? { ...b, label: "I understand" } : b
  );
}

export const ACTION_LABELS: Record<string, string> = {
  start: "Start Learning",
  skip: "Skip Concept",
  understand: "I understand",
  ask_question: "I have a question",
  ask_another: "I still have a confusion",
  concept_q_next: "I understand — next question",
  concept_q_auto_advance: "Next question",
  cluster_q_next: "I understand — next question",
  cluster_q_auto_advance: "Next question",
  concept_notes_continue: "Mark as read",
  explain_again: "Explain again",
  zone0_ready: "Let's dive in",
  story_hook_done: "Continue",
  visual_teaching_next: "Continue",
  visual_teaching_done: "Done",
};

/** UI-only label; backend still receives button `id`. */
export function labelForActionId(id: string, options?: { questionIndex?: number }): string {
  const key = id.trim().toLowerCase();
  if (
    key === "concept_q_next" &&
    options?.questionIndex != null &&
    options.questionIndex >= CONCEPT_QUESTIONS_PER_CONCEPT - 1
  ) {
    return "I understand";
  }
  if (
    key === "cluster_q_next" &&
    options?.questionIndex != null &&
    options.questionIndex >= CLUSTER_QUESTIONS_PER_CLUSTER - 1
  ) {
    return "I understand";
  }
  return ACTION_LABELS[key] ?? id.replace(/_/g, " ");
}

export function formatUserBubbleContent(
  sent: string,
  options?: { questionIndex?: number }
): string {
  const m = /^__action:([a-z0-9_]+)$/i.exec(sent.trim());
  if (m) {
    const id = m[1].toLowerCase();
    return labelForActionId(id, options);
  }
  return sent;
}
