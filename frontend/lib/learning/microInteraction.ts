/** Micro-teaching reflection hold — visible prompt under the board. */

export type MicroInteractionLogPayload = {
  question_visible: boolean;
  question_length: number;
  flow_state: string;
  micro_quiz_hold: 0 | 1 | undefined;
  tutor_reply_length?: number;
};

export function logMicroInteraction(payload: MicroInteractionLogPayload): void {
  // eslint-disable-next-line no-console
  console.info(`[MICRO_INTERACTION] ${JSON.stringify(payload)}`);
}

export function microInteractionPrompt(meta: {
  micro_interaction_prompt?: string;
  current_question?: string;
} | null | undefined): string {
  const p = meta?.micro_interaction_prompt?.trim();
  if (p) return p;
  return meta?.current_question?.trim() ?? "";
}

/** Show micro prompt only after the board/timeline has finished (not while streaming). */
export function shouldShowMicroInteractionPrompt(
  microQuizHold: 0 | 1 | undefined,
  explanationStreaming: boolean,
  prompt: string,
): boolean {
  return microQuizHold === 1 && !explanationStreaming && prompt.length > 0;
}
