/**
 * Board thinking ownership — conversational vs stage-transition.
 * Never persist thinking into messages.
 */

export type BoardLoadingKind = "none" | "conversation" | "stage_transition";

export type BoardSendOptions = {
  silent?: boolean;
  background?: boolean;
  /**
   * Popup / overlay owns the interaction UI — do not append to board messages
   * and do not show board thinking for this request.
   */
  omitFromMessages?: boolean;
};

/**
 * Silent/internal traffic that must never show stage-transition thinking.
 * (Background sends already skip global loading entirely.)
 */
export function isAckOrStateSyncAction(actionBody: string): boolean {
  const a = actionBody.replace(/^__action:/i, "").trim().toLowerCase();
  if (!a) return true;
  if (a.startsWith("flow_checkpoint_pause")) return true;
  if (a === "flow_checkpoint_continue") return true;
  if (a.startsWith("visual_teaching_sentence")) return true;
  if (a === "concept_q_auto_advance") return true;
  if (a.startsWith("concept_q_")) return true;
  if (a.startsWith("cluster_q_")) return true;
  return false;
}

/**
 * Stage handoffs that generate visible next board/panel content while waiting.
 */
export function isVisibleStageAdvanceAction(actionBody: string): boolean {
  const a = actionBody.replace(/^__action:/i, "").trim().toLowerCase();
  if (!a || isAckOrStateSyncAction(actionBody)) return false;
  if (a === "story_hook_done") return true;
  if (a === "story_hook_next") return true;
  if (a.split("|")[0] === "concept_vtse_stage_done") return true;
  if (a === "session_intro_done") return true;
  if (a === "cluster_intro_done") return true;
  if (a === "session_recall_done") return true;
  if (a === "cluster_curiosity_done") return true;
  if (a === "zone0_mirror_done") return true;
  if (a === "ready") return true;
  if (a === "quiz") return true;
  if (a === "understand") return true;
  if (a.startsWith("visual_teaching_next:")) return true;
  if (a.startsWith("visual_teaching_done:")) return true;
  return false;
}

/**
 * Classify an in-flight send for board thinking presentation.
 * Do not use raw `loading` alone for stage thinking.
 */
export function classifyBoardLoadingKind(
  text: string,
  opts?: BoardSendOptions
): BoardLoadingKind {
  if (opts?.background) return "none";
  if (opts?.omitFromMessages) return "none";
  const trimmed = (text || "").trim();
  if (!trimmed) return "none";
  if (trimmed.toLowerCase().startsWith("__action:")) {
    if (isVisibleStageAdvanceAction(trimmed)) return "stage_transition";
    return "none";
  }
  // Silent free-text (e.g. flow-checkpoint popup question) — popup owns UX.
  if (opts?.silent) return "none";
  return "conversation";
}

/**
 * Stage-transition thinking at the absolute bottom of the whiteboard timeline.
 * Never simultaneous with conversational thinking.
 */
export function shouldShowStageTransitionThinking(opts: {
  loadingKind: BoardLoadingKind;
  conversationThinkingActive: boolean;
}): boolean {
  if (opts.conversationThinkingActive) return false;
  return opts.loadingKind === "stage_transition";
}
