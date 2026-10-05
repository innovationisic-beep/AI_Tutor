import type { TutorResponse, TutorSessionMeta } from "@/lib/types";

/**
 * Whether ``concept_vtse_stage_done`` advanced / was accepted.
 *
 * Backend pending-gate returns noop while still awaiting VTSE completion.
 * Idempotent re-sends after questions are armed also return noop with await cleared —
 * treat those as already completed so we do not duplicate stage completion.
 */
export function isConceptVtseStageDoneAccepted(
  tutor: TutorResponse | null | undefined,
  meta?: TutorSessionMeta | null,
): boolean {
  if (!tutor) return false;

  const awaitStill =
    meta?.concept_teaching_await_vtse_done === 1 ||
    meta?.concept_teaching_await_vtse_done === true;
  const questionsActive = meta?.concept_questions_active === true;

  if (tutor.type === "concept_question") {
    return true;
  }

  if (tutor.type === "noop") {
    // Blocked (e.g. flow_checkpoint_pending) while still awaiting → not accepted.
    if (awaitStill && !questionsActive) return false;
    // Already completed / questions armed → idempotent success.
    return true;
  }

  // Checkpoint / sync-only responses never mean stage completion.
  if (
    tutor.type === "flow_checkpoint_continue_ack" ||
    tutor.type === "flow_checkpoint_clarification" ||
    tutor.type === "visual_teaching_sentence_ack" ||
    tutor.type === "vtse_opening_ack"
  ) {
    return false;
  }

  return true;
}
