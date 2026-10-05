"use client";

import { useCallback, useEffect, useRef, useState, type MutableRefObject } from "react";
import {
  getActiveSession,
  getSessionRestore,
  parseSessionMeta,
  sendMessage as apiSend,
} from "@/lib/api";
import {
  mapHistoryRowToChatItem,
  syntheticTutorResponseFromHistoryRow,
} from "@/lib/chatHistory";
import {
  buildRestoredChatItems,
  persistedBoardTurnsFromRestore,
  type SessionBoardTurnSnapshot,
} from "@/lib/sessionRestore";
import type {
  ActiveSession,
  ChatHistoryMessage,
  EndSessionResult,
  PlanProgressionView,
  RecommendedTopicPayload,
  TutorSessionMeta,
  TutorVisual,
} from "@/lib/types";
import {
  applyRestoredSessionMeta,
  deriveSessionUi,
  flowStateFromBackend,
  formatUserBubbleContent,
  INITIAL_UI,
  mainInputEnabled,
  type SessionUiState,
} from "@/lib/tutorFlow";
import {
  classifyBoardLoadingKind,
  type BoardLoadingKind,
} from "@/lib/learning/boardThinking";
import type { TutorResponse } from "@/lib/types";

type AssistantPayload =
  | {
      role: "assistant";
      kind: "text";
      content: string;
      rootTopicId?: string;
      visual?: TutorVisual | null;
      /** Timeline V3 board payload forwarded from backend. */
      instruction_timeline_v3?: Record<string, unknown> | null;
      planner_source?: string | null;
      timeline_metadata?: Record<string, unknown> | null;
      clusterTeachbackTutor?: boolean;
      /** Cluster teachback passed — client should auto-send __action:ready. */
      teachbackPassed?: boolean;
      /** Zone 0 dual-channel: notes mode uses displayText for ink. */
      writingMode?: "legacy" | "notes";
      displayText?: string;
      /** Sentence-anchored board writes (preferred over displayText for reveal). */
      boardWrites?: Array<{ sentenceIndex: number; text: string }>;
    }
  | { role: "assistant"; kind: "quiz_prompt"; intro: string; question: string }
  | { role: "assistant"; kind: "feedback"; message: string; correct: boolean; clusterTeachback?: boolean }
  | { role: "assistant"; kind: "teachback_prompt"; message: string }
  | { role: "assistant"; kind: "teachback_exit"; message: string };

export type ChatItem =
  | {
      id: string;
      role: "user";
      kind: "text";
      content: string;
      /** Raw text sent to the API (e.g. __action:concept_q_next). */
      rawContent?: string;
      conceptQuestion?: boolean;
      /** True for __action: clicks during concept check (not a typed answer). */
      conceptQuestionAction?: boolean;
      /** True for confusion follow-up typed during concept check. */
      conceptQuestionClarification?: boolean;
      clusterQuiz?: boolean;
      clusterQuizAction?: boolean;
      clusterQuizClarification?: boolean;
      clusterTeachback?: boolean;
    }
  | ({
      id: string;
      conceptQuestion?: boolean;
      clusterQuiz?: boolean;
      clusterTeachback?: boolean;
      clusterTeachbackTutor?: boolean;
      teachbackPassed?: boolean;
      /** Planned session slice finished — do not auto-send __action:ready on old session. */
      sessionPlanComplete?: boolean;
    } & AssistantPayload);

export type { SessionUiState };

function uid() {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

function lessonProgressFromSession(
  s: ActiveSession
): SessionUiState["lessonProgress"] {
  const total = s.total_concepts;
  if (total == null || total <= 0) return null;
  const idx = s.current_concept_index;
  return {
    currentIndex: typeof idx === "number" ? idx : 0,
    total,
  };
}

/**
 * Maps a single backend TutorResponse to one or more AssistantPayload items.
 *
 * For quiz responses the backend bundles explanation text together with the
 * question.  We split them into two separate chat items so the explanation
 * can travel to the whiteboard (kind: "text") while the quiz card stays in
 * the chat panel (kind: "quiz_prompt").  The quiz card is held invisible by
 * ChatWindow until the whiteboard finishes streaming the explanation.
 */
function clusterTeachbackTutorTag(
  res: TutorResponse
): { clusterTeachbackTutor: true } | Record<string, never> {
  if (
    res.meta?.cluster_teachback_active === true ||
    res.meta?.cluster_teachback_board === true
  ) {
    return { clusterTeachbackTutor: true };
  }
  return {};
}

function mapResponse(res: TutorResponse): AssistantPayload[] {
  // Timeline V3 fields — forwarded to every "text" board item.
  const itv3 = res.instruction_timeline_v3 ?? null;
  const ps = res.planner_source ?? null;
  const tm = res.timeline_metadata ?? null;
  const itv3Fields =
    itv3 != null || tm != null
      ? {
          ...(itv3 != null ? { instruction_timeline_v3: itv3, planner_source: ps } : {}),
          ...(tm != null ? { timeline_metadata: tm } : {}),
        }
      : {};
  // eslint-disable-next-line no-console
  console.info("[VTSE] useChat itv3_present=", itv3 != null, "planner_source=", ps);

  // Backend guard echo — swallow silently, add nothing to the chat.
  if (res.type === "noop") return [];
  if (res.type === "visual_teaching_sentence_ack") return [];
  if (res.type === "visual_teaching_advance_ack") return [];
  if (res.type === "vtse_opening_ack") return [];
  if (res.type === "flow_checkpoint_continue_ack") return [];
  if (res.type === "flow_checkpoint_clarification") return [];
  if (res.type === "concept_notes") return [];
  if (res.type === "concept_question") return [];
  if (res.type === "quiz") {
    const clusterBatch =
      Array.isArray(res.questions) && res.questions.length >= 2;
    if (clusterBatch) {
      const intro =
        (res.message ?? "").trim() || "Let's put these ideas together.";
      return [
        {
          role: "assistant",
          kind: "quiz_prompt",
          intro,
          question: res.question,
        },
      ];
    }
    const explanation = (res.message ?? "").trim();
    const quizItem: AssistantPayload = {
      role: "assistant",
      kind: "quiz_prompt",
      intro: "",
      question: res.question,
    };
    if (explanation) {
      return [
        { role: "assistant", kind: "text", content: explanation, visual: res.visual ?? null, ...itv3Fields },
        quizItem,
      ];
    }
    return [quizItem];
  }
  if (res.type === "feedback") {
    return [
      {
        role: "assistant",
        kind: "feedback",
        message: res.message,
        correct: res.correct,
      },
    ];
  }
  if (res.type === "root_cause") {
    return [
      {
        role: "assistant",
        kind: "text",
        content: res.message,
        rootTopicId: res.topic_id.trim() ? res.topic_id : undefined,
        visual: res.visual ?? null,
      },
    ];
  }
  if (res.type === "teachback" || res.type === "teachback_retry") {
    // Weak-score intro: score + empathy stay in the teachback panel first.
    if (res.meta?.cluster_teachback_panel) {
      return [
        {
          role: "assistant",
          kind: "feedback",
          message: res.message,
          correct: false,
          clusterTeachback: true,
        },
      ];
    }
    // Other cluster teachback tutor replies belong on the whiteboard (with TTS).
    if (res.meta?.cluster_teachback_active || res.meta?.cluster_teachback_board) {
      return [
        {
          role: "assistant",
          kind: "text",
          content: res.message,
          clusterTeachbackTutor: true,
        },
      ];
    }
    return [
      {
        role: "assistant",
        kind: "teachback_prompt",
        message: res.message,
      },
    ];
  }
  if (res.type === "teachback_passed") {
    return [
      {
        role: "assistant",
        kind: "text",
        content: res.message,
        teachbackPassed: true,
        ...clusterTeachbackTutorTag(res),
      },
    ];
  }
  if (res.type === "teachback_exit") {
    return [
      {
        role: "assistant",
        kind: "teachback_exit",
        message: res.message,
      },
    ];
  }
  if (res.type === "completed") {
    return [
      {
        role: "assistant",
        kind: "text",
        content: res.message,
        teachbackPassed: true,
        sessionPlanComplete: true,
        ...clusterTeachbackTutorTag(res),
      },
    ];
  }
  // Zone 0 — all tutor prose on the whiteboard; answers via main chat input.
  if (
    res.type === "zone0_anchor" ||
    res.type === "zone0_curiosity" ||
    res.type === "zone0_mirror" ||
    res.type === "zone0_prereq" ||
    res.type === "session_intro_card" ||
    res.type === "cluster_intro_card" ||
    res.type === "concept_story_hook" ||
    res.type === "concept_visual_teaching" ||
    res.type === "session_recall_prompt" ||
    res.type === "session_recall_feedback" ||
    res.type === "cluster_curiosity_prompt" ||
    res.type === "cluster_curiosity_feedback"
  ) {
    const pedagogyVisual =
      res.type === "session_intro_card" || res.type === "cluster_intro_card"
        ? res.visual ??
          (res.pedagogy_card
            ? { type: "pedagogy_intro", card: res.pedagogy_card }
            : null)
        : res.type === "concept_story_hook"
          ? res.visual ??
            (res.story_hook_card
              ? { type: "concept_story_hook", card: res.story_hook_card }
              : null)
          : res.visual ?? null;
    const notesCapable =
      res.type === "zone0_anchor" ||
      res.type === "zone0_curiosity" ||
      res.type === "zone0_mirror" ||
      res.type === "zone0_prereq" ||
      res.type === "cluster_curiosity_feedback";
    const writingMode =
      notesCapable && "writing_mode" in res && res.writing_mode
        ? res.writing_mode
        : undefined;
    const displayText =
      notesCapable && writingMode === "notes" && "display_text" in res
        ? (res.display_text ?? "")
        : undefined;
    const boardWrites =
      notesCapable && writingMode === "notes" && "writes" in res && Array.isArray(res.writes)
        ? res.writes
            .map((w) => {
              if (!w || typeof w !== "object") return null;
              const idx = Number(
                (w as { sentence_index?: unknown }).sentence_index
              );
              const text =
                typeof (w as { text?: unknown }).text === "string"
                  ? String((w as { text: string }).text).trim()
                  : "";
              if (!Number.isFinite(idx) || idx < 0 || !text) return null;
              return { sentenceIndex: Math.floor(idx), text };
            })
            .filter(
              (w): w is { sentenceIndex: number; text: string } => w != null
            )
        : undefined;
    return [
      {
        role: "assistant",
        kind: "text",
        content: res.message,
        visual: pedagogyVisual,
        ...(writingMode != null ? { writingMode } : {}),
        ...(displayText !== undefined ? { displayText } : {}),
        ...(boardWrites && boardWrites.length
          ? { boardWrites }
          : {}),
      },
    ];
  }
  const clusterTbTutor = clusterTeachbackTutorTag(res);
  return [
    {
      role: "assistant",
      kind: "text",
      content: res.message,
      visual: res.visual ?? null,
      ...itv3Fields,
      ...clusterTbTutor,
    },
  ];
}

export type UseChatOptions = {
  onTopicCompleted?: (
    result: EndSessionResult,
    progression?: PlanProgressionView | null
  ) => void;
  onProgressionUpdate?: (progression: PlanProgressionView | null) => void;
  /** When true on sessionId change, keep chat/board/progression (plan session handoff). */
  preserveChatOnSessionChangeRef?: MutableRefObject<boolean>;
};

export function useChat(
  token: string | null,
  sessionId: string | null,
  topicId: string | null,
  options?: UseChatOptions
) {
  const historyRequestRef = useRef(0);
  const [messages, setMessages] = useState<ChatItem[]>([]);
  const [isRestoredSession, setIsRestoredSession] = useState(false);
  const [restoredMessageCount, setRestoredMessageCount] = useState(0);
  const [persistedBoardTurns, setPersistedBoardTurns] = useState<
    SessionBoardTurnSnapshot[]
  >([]);
  const [restoreStaticBeatIndex, setRestoreStaticBeatIndex] = useState<
    number | null
  >(null);
  const [restoredHistoryMessages, setRestoredHistoryMessages] = useState<
    ChatHistoryMessage[]
  >([]);
  const [studentScratchpadNotes, setStudentScratchpadNotes] = useState("");
  const [loading, setLoading] = useState(false);
  const [loadingKind, setLoadingKind] = useState<BoardLoadingKind>("none");
  const [error, setError] = useState<string | null>(null);
  const [sessionUi, setSessionUi] = useState<SessionUiState>(INITIAL_UI);
  const [recommendedTopics, setRecommendedTopics] = useState<
    RecommendedTopicPayload[] | null
  >(null);
  const [planProgression, setPlanProgression] = useState<PlanProgressionView | null>(
    null
  );
  const onTopicCompleted = options?.onTopicCompleted;
  const onProgressionUpdate = options?.onProgressionUpdate;
  const onTopicCompletedRef = useRef(onTopicCompleted);
  const onProgressionUpdateRef = useRef(onProgressionUpdate);
  onTopicCompletedRef.current = onTopicCompleted;
  onProgressionUpdateRef.current = onProgressionUpdate;
  const sessionUiRef = useRef(sessionUi);
  sessionUiRef.current = sessionUi;
  /** uiMutating lane. Bumped when a foreground send starts and again when its UI applies. metaSync skips runtime meta if this moved during the fetch. persistenceOnly (background) does not bump it. */
  const uiEpochRef = useRef(0);

  const syncLessonProgress = useCallback(async () => {
    if (!token || !sessionId || !topicId) return;
    try {
      const s = await getActiveSession(token, topicId);
      if (!s || s.id !== sessionId) return;
      const epochAtStart = uiEpochRef.current;
      const lp = lessonProgressFromSession(s);
      const fromApi = s.current_concept?.trim();
      const zoneFromApi =
        typeof s.current_zone === "number" && s.current_zone >= 0
          ? s.current_zone
          : undefined;
      const metaFromApi =
        s && "meta" in s ? (s as { meta?: TutorSessionMeta }).meta : undefined;
      const backendFlow = flowStateFromBackend(
        s.flow_state ?? metaFromApi?.flow_state,
        metaFromApi ?? null
      );
      setSessionUi((prev) => {
        if (uiEpochRef.current !== epochAtStart) {
          return {
            ...prev,
            lessonProgress: lp,
            currentConcept: fromApi || prev.currentConcept,
            ...(zoneFromApi !== undefined ? { currentZone: zoneFromApi } : {}),
          };
        }
        return applyRestoredSessionMeta(
          {
            ...prev,
            lessonProgress: lp,
            currentConcept: fromApi || prev.currentConcept,
            ...(zoneFromApi !== undefined ? { currentZone: zoneFromApi } : {}),
            sessionMeta: metaFromApi
              ? prev.sessionMeta
                ? { ...prev.sessionMeta, ...metaFromApi }
                : metaFromApi
              : prev.sessionMeta,
          },
          metaFromApi,
          backendFlow
        );
      });
    } catch {
      /* ignore */
    }
  }, [token, sessionId, topicId]);

  useEffect(() => {
    void syncLessonProgress();
  }, [syncLessonProgress, loading]);

  useEffect(() => {
    const preserveRef = options?.preserveChatOnSessionChangeRef;
    if (preserveRef?.current) {
      preserveRef.current = false;
      return;
    }
    historyRequestRef.current += 1;
    setMessages([]);
    setRecommendedTopics(null);
    setPlanProgression(null);
    setIsRestoredSession(false);
    setRestoredMessageCount(0);
    setPersistedBoardTurns([]);
    setRestoreStaticBeatIndex(null);
    setRestoredHistoryMessages([]);
    setStudentScratchpadNotes("");
  }, [sessionId]);

  const loadHistoryForSession = useCallback(
    async (sessionIdArg: string) => {
      if (!token) return 0;
      setMessages([]);
      const rid = ++historyRequestRef.current;
      setError(null);
      let restore: Awaited<ReturnType<typeof getSessionRestore>>;
      try {
        restore = await getSessionRestore(token, sessionIdArg);
      } catch (e) {
        if (rid !== historyRequestRef.current) return 0;
        const msg =
          e instanceof Error ? e.message : "Could not load session restore.";
        setError(msg);
        throw e;
      }
      if (rid !== historyRequestRef.current) return restore.messages.length;
      const rows = restore.messages;
      const items = buildRestoredChatItems(
        rows,
        restore.board_turns ?? [],
        restore.pending_board ?? null
      );
      setMessages(items);
      const hasResumeContent =
        rows.length > 0 || (restore.board_turns?.length ?? 0) > 0;
      setIsRestoredSession(hasResumeContent);
      setRestoredMessageCount(items.length);
      setRestoreStaticBeatIndex(
        typeof restore.restore_static_beat_index === "number"
          ? restore.restore_static_beat_index
          : null
      );
      setRestoredHistoryMessages(rows);
      setStudentScratchpadNotes(restore.student_scratchpad_notes ?? "");
      if (restore.progression) {
        setPlanProgression(restore.progression);
        onProgressionUpdateRef.current?.(restore.progression);
      }
      setPersistedBoardTurns(
        persistedBoardTurnsFromRestore(
          restore.board_turns ?? [],
          restore.pending_board ?? null
        ).map((t, i, arr) => {
          if (
            typeof restore.restore_static_beat_index !== "number" ||
            i !== arr.length - 1
          ) {
            return t;
          }
          return {
            ...t,
            timeline_metadata: {
              ...(t.timeline_metadata ?? {}),
              restore_static_through_beat_index: restore.restore_static_beat_index,
            },
          };
        })
      );

      const metaFromRestore = parseSessionMeta(restore.meta);
      const lastAssistantRow = [...rows]
        .reverse()
        .find((r) => r.role === "assistant");
      let synth = lastAssistantRow
        ? syntheticTutorResponseFromHistoryRow(lastAssistantRow)
        : null;
      if (
        !synth &&
        lastAssistantRow?.role === "assistant" &&
        (metaFromRestore?.zone ?? -1) !== 0
      ) {
        const lastQuizBubble = [...items]
          .reverse()
          .find(
            (m): m is ChatItem & { kind: "quiz_prompt" } =>
              m.role === "assistant" && m.kind === "quiz_prompt"
          );
        if (lastQuizBubble) {
          synth = {
            type: "quiz",
            message: lastQuizBubble.intro,
            question: lastQuizBubble.question,
          };
        }
      }
      const backendFlow = flowStateFromBackend(
        restore.flow_state,
        metaFromRestore ?? null
      );
      setSessionUi((prev) => {
        const lp =
          typeof restore.total_concepts === "number" &&
          restore.total_concepts > 0
            ? {
                currentIndex:
                  typeof restore.current_concept_index === "number"
                    ? restore.current_concept_index
                    : 0,
                total: restore.total_concepts,
              }
            : prev.lessonProgress;
        const base: SessionUiState = {
          ...INITIAL_UI,
          lessonProgress: lp,
          currentConcept:
            restore.current_concept?.trim() || prev.currentConcept,
          currentZone:
            typeof restore.current_zone === "number" && restore.current_zone >= 0
              ? restore.current_zone
              : prev.currentZone,
          sessionMeta: metaFromRestore ?? prev.sessionMeta,
        };
        if (!synth) {
          const seeded = applyRestoredSessionMeta(base, metaFromRestore, backendFlow);
          return seeded;
        }
        const derived = deriveSessionUi(synth, base);
        return applyRestoredSessionMeta(derived, metaFromRestore, backendFlow);
      });
      void syncLessonProgress();
      return Math.max(rows.length, restore.board_turns?.length ?? 0);
    },
    [token, syncLessonProgress]
  );

  const sendMessage = useCallback(
    async (
      sessionIdArg: string,
      text: string,
      options?: {
        silent?: boolean;
        background?: boolean;
        /** Popup owns UI — do not append turns to the board timeline. */
        omitFromMessages?: boolean;
      }
    ) => {
      const trimmed = text.trim();
      if (!trimmed || !token) return;
      setError(null);
      const isBackground = Boolean(options?.background);
      const omitFromMessages = Boolean(options?.omitFromMessages);
      let myUiSeq = uiEpochRef.current;
      if (!isBackground) {
        uiEpochRef.current += 1;
        myUiSeq = uiEpochRef.current;
      }
      const kind = classifyBoardLoadingKind(trimmed, {
        silent: options?.silent,
        background: options?.background,
        omitFromMessages,
      });
      const inConceptQ = Boolean(
        sessionUiRef.current.sessionMeta?.concept_questions_active
      );
      const inClusterQ = Boolean(
        sessionUiRef.current.sessionMeta?.cluster_quiz_active
      );
      const inClusterTb = Boolean(
        sessionUiRef.current.sessionMeta?.cluster_teachback_active
      );
      const isClarifying = Boolean(
        sessionUiRef.current.sessionMeta?.concept_question_clarifying
      );
      const isClusterClarifying = Boolean(
        sessionUiRef.current.sessionMeta?.cluster_quiz_clarifying
      );
      if (!options?.silent && !omitFromMessages) {
        const isConceptAction = trimmed.startsWith("__action:");
        const userMsg: ChatItem = {
          id: uid(),
          role: "user",
          kind: "text",
          rawContent: trimmed,
          content: formatUserBubbleContent(trimmed, {
            questionIndex: inClusterQ
              ? sessionUiRef.current.sessionMeta?.cluster_quiz_index
              : sessionUiRef.current.sessionMeta?.concept_question_index,
          }),
          ...(inConceptQ
            ? {
                conceptQuestion: true,
                ...(isConceptAction ? { conceptQuestionAction: true } : {}),
                ...(isClarifying && !isConceptAction
                  ? { conceptQuestionClarification: true }
                  : {}),
              }
            : {}),
          ...(inClusterQ
            ? {
                clusterQuiz: true,
                ...(isConceptAction ? { clusterQuizAction: true } : {}),
                ...(isClusterClarifying && !isConceptAction
                  ? { clusterQuizClarification: true }
                  : {}),
              }
            : {}),
          ...(inClusterTb ? { clusterTeachback: true } : {}),
        };
        setMessages((prev) => [...prev, userMsg]);
      }
      // Background / ack-only / popup-owned: no board thinking.
      // Visible stage advances and conversational replies set loading + kind.
      if (!isBackground && kind !== "none") {
        setLoadingKind(kind);
        setLoading(true);
      } else if (!isBackground && kind === "none" && !omitFromMessages) {
        // Input lock only (checkpoint pause/continue, etc.) — no thinking row.
        setLoadingKind("none");
        setLoading(true);
      }
      try {
        const { tutor: res, sessionCompletion, recommendedTopics: recRaw, progression } =
          await apiSend(token, sessionIdArg, trimmed);
        setIsRestoredSession(false);
        const staleUi = !isBackground && myUiSeq !== uiEpochRef.current;
        const assistants: ChatItem[] = mapResponse(res).map((p) => ({
          id: uid(),
          ...p,
        }));
        if (!omitFromMessages && !staleUi) {
          setMessages((prev) => [...prev, ...assistants]);
        }
        const appliesSessionUi =
          !staleUi &&
          !isBackground &&
          res.type !== "visual_teaching_sentence_ack" &&
          res.type !== "visual_teaching_advance_ack" &&
          res.type !== "flow_checkpoint_clarification";
        if (appliesSessionUi) {
          uiEpochRef.current += 1;
        }
        if (staleUi || (isBackground && res.type === "visual_teaching_sentence_ack")) {
          // Stale uiMutating response, or persistence-only sentence ack.
        } else if (res.type === "visual_teaching_sentence_ack") {
          // State-sync only — do not run flow derivation / board UI mutation.
        } else if (res.type === "visual_teaching_advance_ack") {
          // Authoritative cursor ack — no board item / no pedagogical flow change.
        } else if (res.type === "vtse_opening_ack") {
          // Duplicate/stale VTSE open — keep flow from ack meta, never append timeline.
          setSessionUi((prev) => deriveSessionUi(res, prev));
        } else if (res.type === "noop") {
          setSessionUi((prev) => {
            const derived = deriveSessionUi(res, prev);
            if (prev.flowState === "zone0_anchor" && prev.buttons.length > 0) {
              return { ...derived, buttons: [] };
            }
            return derived;
          });
        } else if (res.type === "flow_checkpoint_clarification") {
          // Flow checkpoint overlay owns clarification UI — do not mutate chat flow.
        } else if (res.type === "flow_checkpoint_continue_ack") {
          // Pending cleared — merge meta; protect armed Concept Check from wipe.
          setSessionUi((prev) => deriveSessionUi(res, prev));
        } else if (res.type === "concept_question") {
          // Panel-only — meta/stem update, no board bubble (mapResponse empty).
          setSessionUi((prev) => deriveSessionUi(res, prev));
        } else if (res.type === "feedback") {
          requestAnimationFrame(() => {
            setSessionUi((prev) => deriveSessionUi(res, prev));
          });
        } else {
          setSessionUi((prev) => deriveSessionUi(res, prev));
        }
        if (res.type === "teachback_passed" || res.type === "completed") {
          void syncLessonProgress();
        }
        const mergedRec =
          (Array.isArray(recRaw) && recRaw.length > 0
            ? recRaw
            : null) ??
          (sessionCompletion?.recommended_topics &&
          sessionCompletion.recommended_topics.length > 0
            ? sessionCompletion.recommended_topics
            : null);
        setRecommendedTopics(mergedRec);
        if (progression) {
          setPlanProgression(progression);
          onProgressionUpdateRef.current?.(progression);
        }
        if (sessionCompletion && onTopicCompletedRef.current) {
          onTopicCompletedRef.current(sessionCompletion, progression ?? null);
        }
        if (!isBackground) {
          void syncLessonProgress();
        }
        return {
          tutor: res,
          sessionCompletion,
          recommendedTopics: mergedRec,
          progression,
        };
      } catch (e) {
        const errText = e instanceof Error ? e.message : "Failed to send";
        setError(errText);
        if (
          options?.silent &&
          /session is not in progress/i.test(errText)
        ) {
          return;
        }
        if (isBackground || omitFromMessages) {
          // Background / popup-owned fails quietly — never inject board items.
          return;
        }
        const errMsg: ChatItem = {
          id: uid(),
          role: "assistant",
          kind: "text",
          content:
            e instanceof Error
              ? `Something went wrong: ${e.message}`
              : "Something went wrong.",
        };
        setMessages((prev) => [...prev, errMsg]);
      } finally {
        if (!isBackground) {
          setLoading(false);
          setLoadingKind("none");
        }
      }
    },
    [token, syncLessonProgress]
  );

  const bootstrapSession = useCallback(
    async (sessionIdArg: string) => {
      await sendMessage(sessionIdArg, ".", { silent: true });
    },
    [sendMessage]
  );

  const clearMessages = useCallback(() => {
    historyRequestRef.current += 1;
    setMessages([]);
    setError(null);
    setSessionUi(INITIAL_UI);
    setRecommendedTopics(null);
    setPlanProgression(null);
    setIsRestoredSession(false);
    setRestoredMessageCount(0);
    setPersistedBoardTurns([]);
    setRestoreStaticBeatIndex(null);
    setRestoredHistoryMessages([]);
    setStudentScratchpadNotes("");
  }, []);

  const inputEnabled = mainInputEnabled(sessionUi) && !loading;
  const actionButtonsDisabled = loading;

  return {
    messages,
    loading,
    loadingKind,
    error,
    sendMessage,
    bootstrapSession,
    loadHistoryForSession,
    clearMessages,
    sessionUi,
    inputEnabled,
    actionButtonsDisabled,
    recommendedTopics,
    planProgression,
    isRestoredSession,
    restoredMessageCount,
    persistedBoardTurns,
    restoreStaticBeatIndex,
    restoredHistoryMessages,
    studentScratchpadNotes,
    setStudentScratchpadNotes,
    refreshSessionMeta: syncLessonProgress,
  };
}
