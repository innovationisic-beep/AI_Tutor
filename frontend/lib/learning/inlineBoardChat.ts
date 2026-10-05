/**
 * Full-width board inline conversation — presentation predicates + filters.
 * Source of truth remains useChat.messages; no second store.
 *
 * Visibility contract (keep separate):
 * 1. History visible — shouldShowInlineBoardChatHistory / resolveInlineBoardChatHistoryMode
 * 2. Input enabled — shouldShowBoardComposer / mainInputEnabled
 * 3. Tutor generating — loading prop to InlineBoardChat (thinking row only)
 */

import type { ChatItem } from "@/hooks/useChat";
import type { SessionUiState } from "@/lib/tutorFlow";
import { mainInputEnabled } from "@/lib/tutorFlow";

/** Flows that show WhatsApp-style inline chat under the whiteboard. */
export type InlineBoardChatMode =
  | "zone0_answer"
  | "pedagogy_recall"
  | "pedagogy_curiosity"
  | "story_hook_await"
  | "clarity_teachback"
  | "waiting_for_question"
  | "legacy_quiz"
  | null;

export type InlineBoardChatVisibilityOpts = {
  isTeachbackMode?: boolean;
  conceptQuestionsActive?: boolean;
  clusterQuizActive?: boolean;
  clusterTeachbackActive?: boolean;
  /** Ask/send in flight — hold history through transient flow flips. */
  loading?: boolean;
  /** Last conversational filter mode while the episode was active. */
  stickyMode?: InlineBoardChatMode;
};

/**
 * True when the permanent right chat column should not exist.
 * Always true for the new layout — chrome lives under the board when needed.
 */
export function isFullWidthBoardLayout(): boolean {
  return true;
}

/**
 * Modes that own a durable conversational episode (Q→A bubbles).
 * Preserved across Story Hook narration/await so prior history does not unmount.
 */
export function isConversationalEpisodeMode(
  mode: InlineBoardChatMode
): boolean {
  return (
    mode === "zone0_answer" ||
    mode === "pedagogy_recall" ||
    mode === "pedagogy_curiosity" ||
    mode === "waiting_for_question" ||
    mode === "clarity_teachback"
  );
}

/**
 * Hard full-board / panel stages — hide history and clear sticky episode.
 * Story Hook is intentionally NOT included: prior Zone0/pedagogy bubbles must
 * stay mounted while the Story Hook card owns the board stage chrome.
 */
export function isInlineChatHardExcludedStage(
  ui: SessionUiState,
  opts?: InlineBoardChatVisibilityOpts
): boolean {
  if (opts?.conceptQuestionsActive) return true;
  if (opts?.clusterQuizActive) return true;
  if (opts?.clusterTeachbackActive) return true;

  const flow = ui.flowState;
  if (flow === "concept_visual_teaching") return true;
  if (flow === "concept_vtse_opening") return true;
  if (
    flow === "pedagogy_session_intro" ||
    flow === "pedagogy_cluster_intro"
  ) {
    return true;
  }
  if (flow === "concept_questions" || flow === "cluster_quiz") return true;
  if (
    flow === "zone_2_entry" ||
    flow === "zone_3_entry" ||
    flow === "zone_4_entry"
  ) {
    return true;
  }
  if (flow === "completed") return true;
  return false;
}

/** Alias for hard-excluded stages (sticky clear / history hide). */
export function isInlineChatExcludedStage(
  ui: SessionUiState,
  opts?: InlineBoardChatVisibilityOpts
): boolean {
  return isInlineChatHardExcludedStage(ui, opts);
}

function isTransientTutorHoldFlow(flow: SessionUiState["flowState"]): boolean {
  return (
    flow === "explaining" ||
    flow === "idle" ||
    flow === "checking_understanding" ||
    flow === "pedagogy_session_recall_feedback" ||
    flow === "pedagogy_cluster_curiosity_feedback"
  );
}

/**
 * Live awaiting-input mode (exact flow). Used for composer-adjacent hints;
 * history visibility uses resolveInlineBoardChatHistoryMode instead.
 */
export function resolveInlineBoardChatMode(
  ui: SessionUiState,
  opts?: { isTeachbackMode?: boolean }
): InlineBoardChatMode {
  const flow = ui.flowState;
  const meta = ui.sessionMeta;

  if (opts?.isTeachbackMode) {
    return "clarity_teachback";
  }

  if (flow === "waiting_for_question") {
    return "waiting_for_question";
  }

  if (
    flow === "quizzing" ||
    (ui.activeQuiz != null &&
      meta?.concept_questions_active !== true &&
      meta?.cluster_quiz_active !== true &&
      meta?.cluster_teachback_active !== true)
  ) {
    // Legacy QuizBox path — still reachable for non-panel quizzes.
    if (
      flow !== "zone0_anchor" &&
      flow !== "zone0_prereq" &&
      flow !== "zone0_curiosity" &&
      flow !== "zone0_mirror"
    ) {
      return "legacy_quiz";
    }
  }

  if (flow === "concept_story_hook" && meta?.story_hook_awaiting === true) {
    return "story_hook_await";
  }

  if (flow === "pedagogy_session_recall") {
    return "pedagogy_recall";
  }
  if (flow === "pedagogy_cluster_curiosity") {
    return "pedagogy_curiosity";
  }

  if (
    flow === "zone0_anchor" ||
    flow === "zone0_prereq" ||
    flow === "zone0_curiosity"
  ) {
    return "zone0_answer";
  }

  return null;
}

/**
 * Filter mode for the mounted conversation thread — stable across an episode.
 * Includes feedback / mirror / Zone0 holds so history does not unmount while
 * the tutor reply is in flight or flow briefly leaves an awaiting_* state.
 *
 * Story Hook: keep sticky conversational episode (e.g. zone0_answer) so prior
 * bubbles stay mounted; Story Hook card remains durable board chrome.
 */
export function resolveInlineBoardChatHistoryMode(
  ui: SessionUiState,
  opts?: InlineBoardChatVisibilityOpts
): InlineBoardChatMode {
  if (isInlineChatHardExcludedStage(ui, opts)) {
    return null;
  }

  if (opts?.isTeachbackMode) {
    return "clarity_teachback";
  }

  const flow = ui.flowState;
  const sticky = opts?.stickyMode;

  // Feedback / mirror are still the same conversational episode.
  if (flow === "pedagogy_session_recall_feedback") {
    return "pedagogy_recall";
  }
  if (flow === "pedagogy_cluster_curiosity_feedback") {
    return "pedagogy_curiosity";
  }
  if (flow === "zone0_mirror") {
    return "zone0_answer";
  }

  // Entire Zone 0 learning episode shares one thread (Q→A→feedback→next Q).
  if (
    ui.currentZone === 0 &&
    (flow.startsWith("zone0_") || isTransientTutorHoldFlow(flow))
  ) {
    return "zone0_answer";
  }

  // Story Hook board stage: never tear down a prior conversational episode.
  // Prefer sticky zone0/pedagogy filter so tutor+student bubbles stay omitted
  // from boardItems (no snap-back to lined-paper prose).
  if (flow === "concept_story_hook") {
    if (sticky != null && isConversationalEpisodeMode(sticky)) {
      return sticky;
    }
    if (ui.sessionMeta?.story_hook_awaiting === true) {
      return "story_hook_await";
    }
    return null;
  }

  const live = resolveInlineBoardChatMode(ui, {
    isTeachbackMode: opts?.isTeachbackMode,
  });
  // Do not let story_hook_await replace an active episode sticky via live path
  // (live is null here for story_hook — handled above).
  if (live != null && live !== "legacy_quiz" && live !== "story_hook_await") {
    return live;
  }
  if (live === "story_hook_await") {
    if (sticky != null && isConversationalEpisodeMode(sticky)) {
      return sticky;
    }
    return "story_hook_await";
  }

  // Hold last episode mode while loading or in a brief tutor-response flow
  // (e.g. syncLessonProgress flipping flow mid-request).
  if (
    sticky != null &&
    sticky !== "legacy_quiz" &&
    (opts?.loading === true || isTransientTutorHoldFlow(flow))
  ) {
    return sticky;
  }

  return null;
}

/** Show conversation HISTORY (independent of composer / loading). */
export function shouldShowInlineBoardChatHistory(
  ui: SessionUiState,
  opts?: InlineBoardChatVisibilityOpts
): boolean {
  const mode = resolveInlineBoardChatHistoryMode(ui, opts);
  return mode != null && mode !== "legacy_quiz";
}

/** Alias for history visibility (not input-enabled). */
export function shouldShowInlineBoardChat(
  ui: SessionUiState,
  opts?: InlineBoardChatVisibilityOpts
): boolean {
  return shouldShowInlineBoardChatHistory(ui, opts);
}

/** Composer under the board — same gate as mainInputEnabled, excluding panel modes. */
export function shouldShowBoardComposer(
  ui: SessionUiState,
  opts?: {
    isTeachbackMode?: boolean;
    conceptQuestionsActive?: boolean;
    clusterQuizActive?: boolean;
    clusterTeachbackActive?: boolean;
  }
): boolean {
  if (
    opts?.conceptQuestionsActive ||
    opts?.clusterQuizActive ||
    opts?.clusterTeachbackActive
  ) {
    return false;
  }
  if (opts?.isTeachbackMode) {
    // TeachbackInput is shown instead of InputBox.
    return false;
  }
  return mainInputEnabled(ui);
}

export function shouldShowBoardTeachbackInput(
  opts?: { isTeachbackMode?: boolean }
): boolean {
  return opts?.isTeachbackMode === true;
}

/** Legacy QuizBox under the board when still reachable. */
export function shouldShowBoardQuizBox(
  ui: SessionUiState,
  opts?: {
    conceptQuestionsActive?: boolean;
    clusterQuizActive?: boolean;
    clusterTeachbackActive?: boolean;
    zone0LearningUi?: boolean;
  }
): boolean {
  if (!ui.activeQuiz) return false;
  if (opts?.conceptQuestionsActive) return false;
  if (opts?.clusterQuizActive) return false;
  if (opts?.clusterTeachbackActive) return false;
  if (opts?.zone0LearningUi) return false;
  return true;
}

/**
 * Lesson ActionButtons under the board (Ready / I understand / etc.).
 * Same visibility rules as the former right-column buttons.
 */
export function shouldShowBoardActionButtons(
  ui: SessionUiState,
  opts?: { conceptQuestionsActive?: boolean }
): boolean {
  if (opts?.conceptQuestionsActive) return false;
  if (!ui.buttons.length) return false;
  const hasZone0Ready = ui.buttons.some((b) => b.id === "zone0_ready");
  if (hasZone0Ready && ui.flowState !== "zone0_curiosity") {
    return false;
  }
  return true;
}

function isSilentOrActionUserMessage(m: ChatItem): boolean {
  if (m.role !== "user") return false;
  if (m.conceptQuestionAction || m.clusterQuizAction) return true;
  const raw = (m.rawContent ?? m.content ?? "").trim();
  if (raw.toLowerCase().startsWith("__action:")) return true;
  return false;
}

/**
 * Stage cards / timelines that must stay as board chrome (not chat bubbles).
 * Story Hook card, Visual Teaching, VTSE timeline, pedagogy intro cards.
 */
export function isDurableBoardStageMessage(m: ChatItem): boolean {
  if (m.role !== "assistant" || m.kind !== "text") return false;
  if (m.instruction_timeline_v3 != null) return true;
  const visual = "visual" in m ? m.visual : null;
  const vType =
    visual && typeof visual === "object" && "type" in visual
      ? String((visual as { type?: unknown }).type || "")
      : "";
  if (
    vType === "concept_story_hook" ||
    vType === "concept_visual_teaching" ||
    vType === "pedagogy_intro"
  ) {
    return true;
  }
  return false;
}

/** Modes where tutor conversational prose belongs in the bubble thread. */
function modeIncludesTutorConversationalProse(mode: InlineBoardChatMode): boolean {
  return (
    mode === "zone0_answer" ||
    mode === "pedagogy_recall" ||
    mode === "pedagogy_curiosity" ||
    mode === "waiting_for_question"
  );
}

function modeIncludesFeedbackBubbles(mode: InlineBoardChatMode): boolean {
  return (
    mode === "zone0_answer" ||
    mode === "pedagogy_recall" ||
    mode === "pedagogy_curiosity" ||
    mode === "clarity_teachback" ||
    mode === "waiting_for_question"
  );
}

/**
 * One chronologically ordered conversational thread.
 * Filter only — never regroup by role.
 */
export function filterInlineBoardChatMessages(
  messages: ChatItem[],
  mode: InlineBoardChatMode
): ChatItem[] {
  if (!mode || mode === "legacy_quiz") return [];

  const includeTutorProse = modeIncludesTutorConversationalProse(mode);
  const includeFeedback = modeIncludesFeedbackBubbles(mode);

  // Preserve original array order; `.filter` does not reorder.
  return messages.filter((m) => {
    if (m.role === "user") {
      if (isSilentOrActionUserMessage(m)) return false;
      if (m.conceptQuestion || m.clusterQuiz || m.clusterTeachback) return false;
      return true;
    }

    if (m.role !== "assistant") return false;

    if (m.kind === "teachback_prompt" || m.kind === "teachback_exit") {
      return mode === "clarity_teachback" || mode === "waiting_for_question";
    }

    if (m.kind === "feedback") {
      return includeFeedback;
    }

    if (m.kind === "quiz_prompt") {
      return false;
    }

    if (m.kind === "text") {
      if (m.clusterTeachbackTutor) return false;
      // Story Hook / VT / VTSE cards stay on the board surface.
      if (isDurableBoardStageMessage(m)) return false;
      // Story Hook awaiting: question lives on ConceptStoryHookCard — answers only.
      if (mode === "story_hook_await") return false;
      if (mode === "clarity_teachback") return false;
      return includeTutorProse;
    }

    return false;
  });
}

/**
 * Assistant text message ids that are shown as inline bubbles — omit from
 * boardItems to avoid tutor-board-lines + student-bubbles grouping.
 */
export function inlineConversationBoardOmitIds(
  messages: ChatItem[],
  mode: InlineBoardChatMode
): Set<string> {
  const thread = filterInlineBoardChatMessages(messages, mode);
  const ids = new Set<string>();
  for (const m of thread) {
    if (m.role === "assistant" && m.kind === "text") {
      ids.add(m.id);
    }
  }
  return ids;
}

/**
 * Split board chrome around the inline bubble episode by message chronology.
 *
 * Example: [session intro][cluster intro] | Zone0 bubbles | [Story Hook]
 * — intros stay above chat; Story Hook appends below. No wholesale before/after.
 */
export function splitBoardItemsAroundInlineThread<T extends { id: string }>(
  messages: ChatItem[],
  inlineThread: ChatItem[],
  boardItems: T[]
): { before: T[]; after: T[] } {
  if (boardItems.length === 0) {
    return { before: [], after: [] };
  }
  if (inlineThread.length === 0) {
    return { before: [...boardItems], after: [] };
  }

  const indexById = new Map<string, number>();
  for (let i = 0; i < messages.length; i++) {
    indexById.set(messages[i]!.id, i);
  }

  const inlineIndices: number[] = [];
  for (const m of inlineThread) {
    const idx = indexById.get(m.id);
    if (idx != null) inlineIndices.push(idx);
  }
  if (inlineIndices.length === 0) {
    return { before: [...boardItems], after: [] };
  }

  const firstInline = Math.min(...inlineIndices);

  const before: T[] = [];
  const after: T[] = [];
  for (const item of boardItems) {
    const idx = indexById.get(item.id);
    if (idx == null) {
      // Not in live messages (rare restore/synthetic): treat as later stage.
      after.push(item);
      continue;
    }
    if (idx < firstInline) {
      before.push(item);
    } else {
      after.push(item);
    }
  }
  return { before, after };
}

/** True when this assistant text should stay on the board (not demoted to bubble). */
export function shouldKeepAssistantTextOnBoard(
  m: ChatItem,
  omitIds: Set<string>
): boolean {
  if (m.role !== "assistant" || m.kind !== "text") return false;
  if (omitIds.has(m.id)) return false;
  return true;
}

/**
 * Latest assistant text that still owns WordSyncedStreaming / TTS completion.
 * Includes board-surface items and conversational bubbles omitted from the board.
 */
export function resolveLatestStreamableAssistantId(
  messages: ChatItem[],
  boardItemIds: Iterable<string>,
  inlineOmitIds: Set<string>
): string | null {
  const onBoard =
    boardItemIds instanceof Set ? boardItemIds : new Set(boardItemIds);
  for (let i = messages.length - 1; i >= 0; i--) {
    const m = messages[i];
    if (m!.role !== "assistant" || m!.kind !== "text") continue;
    if (onBoard.has(m!.id) || inlineOmitIds.has(m!.id)) {
      return m!.id;
    }
  }
  return null;
}
