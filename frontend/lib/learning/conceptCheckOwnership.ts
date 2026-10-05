import type { TutorResponse, TutorSessionMeta } from "@/lib/types";

/**
 * Prevent stale continue/active-session metas from wiping an already-armed
 * Concept Check question (linear_process checkpoint race).
 */
export function protectConceptCheckMeta(
  prev: TutorSessionMeta | null | undefined,
  incoming: TutorSessionMeta | null | undefined,
  res?: Pick<TutorResponse, "type"> | null,
): TutorSessionMeta | null | undefined {
  if (incoming == null) return incoming;
  if (prev == null) return incoming;

  const merged: TutorSessionMeta = { ...prev, ...incoming };
  const prevArmed = prev.concept_questions_active === true;
  const prevStem = (prev.micro_interaction_prompt || "").trim();
  const prevAwait =
    prev.concept_teaching_await_vtse_done === 1 ||
    prev.concept_teaching_await_vtse_done === true;
  const incomingAwait =
    incoming.concept_teaching_await_vtse_done === 1 ||
    incoming.concept_teaching_await_vtse_done === true;

  const resType = res?.type;
  const isAckOrNoop =
    resType === "flow_checkpoint_continue_ack" ||
    resType === "noop" ||
    resType === "flow_checkpoint_clarification" ||
    resType === "vtse_opening_ack" ||
    resType === "visual_teaching_advance_ack" ||
    resType === "visual_teaching_sentence_ack";

  // Stale pre-stage_done snapshot: await still 1 and CQ cleared after we had
  // already armed Concept Check with VTSE complete.
  if (
    prevArmed &&
    !prevAwait &&
    prevStem &&
    incoming.concept_questions_active === false &&
    incomingAwait
  ) {
    return {
      ...merged,
      concept_questions_active: true,
      concept_teaching_await_vtse_done: 0,
      micro_quiz_hold: prev.micro_quiz_hold === 0 ? 0 : 1,
      micro_interaction_prompt: prev.micro_interaction_prompt,
      concept_question_index: prev.concept_question_index ?? 0,
      concept_question_type: prev.concept_question_type ?? merged.concept_question_type,
      concept_question_options:
        prev.concept_question_options ?? merged.concept_question_options,
      concept_question_followup: prev.concept_question_followup ?? false,
      concept_question_clarifying: prev.concept_question_clarifying ?? false,
      concept_question_pending_advance:
        prev.concept_question_pending_advance ?? false,
      flow_state: "concept_questions",
    };
  }

  // Continue/noop/ack (or hold wipe without prompt) must not erase an armed stem.
  const incomingLostStem =
    !(incoming.micro_interaction_prompt || "").trim() &&
    (incoming.micro_quiz_hold === 0 || incoming.micro_quiz_hold == null);
  if (
    prevArmed &&
    prevStem &&
    incomingLostStem &&
    (isAckOrNoop || incomingAwait || incoming.concept_questions_active !== false)
  ) {
    const keepActive =
      incoming.concept_questions_active !== false || isAckOrNoop || incomingAwait;
    if (keepActive) {
      merged.concept_questions_active = true;
      merged.micro_interaction_prompt = prev.micro_interaction_prompt;
      if (prev.micro_quiz_hold === 1) {
        merged.micro_quiz_hold = 1;
      }
      if (prev.concept_question_type != null) {
        merged.concept_question_type = prev.concept_question_type;
      }
      if (prev.concept_question_options != null) {
        merged.concept_question_options = prev.concept_question_options;
      }
      if (typeof prev.concept_question_index === "number") {
        merged.concept_question_index = prev.concept_question_index;
      }
      if (incomingAwait && !prevAwait) {
        merged.concept_teaching_await_vtse_done = 0;
      }
    }
  }

  return merged;
}

/** Stem text for ConceptQuestionPanel — authoritative when Concept Check is armed. */
export function resolveConceptCheckStem(
  meta: TutorSessionMeta | null | undefined,
): string {
  if (!meta || meta.concept_questions_active !== true) return "";
  const fromPrompt = (meta.micro_interaction_prompt || "").trim();
  if (fromPrompt) return fromPrompt;
  return (meta.current_question || "").trim();
}

/**
 * Show the current Concept Check stem in the panel body.
 * Independent of micro_quiz_hold so the panel never looks "armed but empty".
 */
export function shouldShowConceptCheckQuestion(meta: {
  concept_questions_active?: boolean;
  concept_question_clarifying?: boolean;
  concept_question_pending_advance?: boolean;
  concept_question_followup?: boolean;
  micro_interaction_prompt?: string;
  current_question?: string;
} | null | undefined): boolean {
  if (!meta || meta.concept_questions_active !== true) return false;
  if (meta.concept_question_clarifying) return false;
  if (meta.concept_question_pending_advance) return false;
  return resolveConceptCheckStem(meta as TutorSessionMeta).length > 0;
}
