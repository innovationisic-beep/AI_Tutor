/**
 * Debug-only lifecycle traces for Zone 1 instruction board orchestration release.
 * Enable with NEXT_PUBLIC_CIR_INSTRUCTION_DEBUG=1.
 */

export type InstructionLifecycleOutcome =
  | "started"
  | "started_skip_already_finalized"
  | "completed"
  | "runtime_failed"
  | "validation_failed"
  | "released";

export type HandleExplanationCompleteBranch =
  | "noop_no_session"
  | "noop_end_result"
  | "noop_no_active_board"
  | "noop_already_triggered"
  | "noop_zone0_curiosity"
  | "noop_teachback_or_active_quiz"
  | "micro_quiz_hold"
  | "student_questions_active"
  | "cluster_quiz_ready_false_continue"
  | "quiz_sent";

export function instructionLifecycleDebugEnabled(): boolean {
  return process.env.NEXT_PUBLIC_CIR_INSTRUCTION_DEBUG === "1";
}

export function logInstructionLifecycle(
  outcome: InstructionLifecycleOutcome,
  detail?: Record<string, unknown>,
): void {
  if (!instructionLifecycleDebugEnabled()) return;
  const payload = detail ? ` ${JSON.stringify(detail)}` : "";
  // eslint-disable-next-line no-console
  console.info(`[INSTRUCTION_LIFECYCLE] ${outcome}${payload}`);
}

export function logInstructionFinalize(
  reason: string,
  alreadyFinalized: boolean,
  timelineId: string,
  detail?: Record<string, unknown>,
): void {
  if (!instructionLifecycleDebugEnabled()) return;
  const extra = detail ? ` ${JSON.stringify(detail)}` : "";
  // eslint-disable-next-line no-console
  console.info(
    `[INSTRUCTION_FINALIZE] reason=${reason} alreadyFinalized=${alreadyFinalized} timeline_id=${timelineId}${extra}`,
  );
}

export type TimelineRenderPhase = "mounted" | "unmounted" | "rerendered";

export function logTimelineRender(
  phase: TimelineRenderPhase,
  timelineId: string,
  detail?: Record<string, unknown>,
): void {
  if (!instructionLifecycleDebugEnabled()) return;
  const extra = detail ? ` ${JSON.stringify(detail)}` : "";
  // eslint-disable-next-line no-console
  console.info(`[TIMELINE_RENDER] ${phase} timeline_id=${timelineId}${extra}`);
}

export function logExplanationStreaming(payload: {
  activeBoardStreamingId: string | null;
  completedBoardItemId: string | null;
  quizHeld: boolean;
}): void {
  if (!instructionLifecycleDebugEnabled()) return;
  // eslint-disable-next-line no-console
  console.info(`[EXPLANATION_STREAMING] ${JSON.stringify(payload)}`);
}

export function logHandleExplanationComplete(branch: HandleExplanationCompleteBranch): void {
  if (!instructionLifecycleDebugEnabled()) return;
  // eslint-disable-next-line no-console
  console.info(`[HANDLE_EXPLANATION_COMPLETE] branch=${branch}`);
}

export type NarrationSyncPhase =
  | "eligible"
  | "ineligible"
  | "cadence_skipped_playback_done"
  | "cadence_blocked_finalized_guard"
  | "started"
  | "cancelled"
  | "completed"
  | "segment_missing_binding"
  | "beat_orchestrated"
  | "beat_legacy_frames"
  | "speech_reveal_chunk"
  | "speech_reveal_complete";

export function logNarrationSync(
  phase: NarrationSyncPhase,
  detail?: Record<string, unknown>,
): void {
  if (!instructionLifecycleDebugEnabled()) return;
  const extra = detail ? ` ${JSON.stringify(detail)}` : "";
  // eslint-disable-next-line no-console
  console.info(`[NARRATION_SYNC] ${phase}${extra}`);
}

export function logHighlightLifecycle(detail: Record<string, unknown>): void {
  if (!instructionLifecycleDebugEnabled()) return;
  // eslint-disable-next-line no-console
  console.info(`[HIGHLIGHT_LIFECYCLE] ${JSON.stringify(detail)}`);
}

export function logAnnotationLifecycle(detail: Record<string, unknown>): void {
  if (!instructionLifecycleDebugEnabled()) return;
  // eslint-disable-next-line no-console
  console.info(`[ANNOTATION_LIFECYCLE] ${JSON.stringify(detail)}`);
}

export { logProductionVisualRenderer } from "@/lib/learning/productionVisualRenderer";
