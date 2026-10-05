"use client";

import {
  Suspense,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useAuth } from "@/hooks/useAuth";
import { useChat, type ChatItem } from "@/hooks/useChat";
import { getStudentProfile, startSession, type StartSessionScope } from "@/lib/api";
import { unlockAudioPlayback } from "@/lib/voice";
import { listStudentCatalogSessionPlans, type CatalogSessionPlanSummary } from "@/lib/api/catalogClassroom";
import type { EndSessionResult, PlanProgressionView, StartSessionResumePrompt } from "@/lib/types";
import {
  AIWhiteboard,
  type BoardItem,
} from "@/components/ai/AIWhiteboard";
import { InputBox } from "@/components/chat/InputBox";
import { TeachbackInput } from "@/components/chat/TeachbackInput";
import { ActionButtons } from "@/components/chat/ActionButtons";
import { QuizBox } from "@/components/chat/QuizBox";
import { InlineBoardChat, TutorThinkingBubble } from "@/components/learning/InlineBoardChat";
import { RecommendedTopics } from "@/components/learning/RecommendedTopics";
import { ConceptQuestionPanel } from "@/components/learning/ConceptQuestionPanel";
import { ClusterQuizPanel } from "@/components/learning/ClusterQuizPanel";
import { ClusterTeachbackPanel } from "@/components/learning/ClusterTeachbackPanel";
import { StudentScratchpadPanel } from "@/components/learning/StudentScratchpadPanel";
import {
  PostConceptNotesPanel,
  type ConceptNotesEntry,
} from "@/components/learning/PostConceptNotesPanel";
import {
  buildConceptThread,
  filterBoardMessages,
  resolveConceptQuestionType,
  type ConceptQuestionRecord,
  type ConceptThreadItem,
} from "@/lib/learning/conceptQuestionPanel";
import {
  resolveConceptCheckStem,
  shouldShowConceptCheckQuestion,
} from "@/lib/learning/conceptCheckOwnership";
import {
  buildClusterQuizThread,
  filterBoardMessagesForClusterQuiz,
  resolveClusterQuizType,
  type ClusterQuizRecord,
  type ClusterThreadItem,
} from "@/lib/learning/clusterQuizPanel";
import {
  buildClusterTeachbackThread,
  filterBoardMessagesForClusterTeachback,
  isClusterTeachbackTutorMessage,
  type ClusterTeachbackThreadItem,
  type ClusterTeachbackQuestionRecord,
} from "@/lib/learning/clusterTeachbackPanel";
import {
  activeSessionHeading,
  clusterSectionHeading,
  completedSessionHeading,
  flattenNotesSections,
  flattenThreadSections,
  withPrefixedIds,
  type NotesPanelSection,
  type PanelSection,
} from "@/lib/learning/panelSections";
import {
  boardTurnToChatItem,
  persistedBoardTurnsFromRestore,
  staticRestoreMapFromChatItems,
  staticRestoreMapFromTurns,
  supplementBoardTurnsFromHistoryMessages,
} from "@/lib/sessionRestore";
import { saveBoardCheckpoint, saveStudentScratchpad } from "@/lib/api";
import {
  logMicroInteraction,
  microInteractionPrompt,
  shouldShowMicroInteractionPrompt,
} from "@/lib/learning/microInteraction";
import {
  isZone0LearningUi,
} from "@/lib/learning/zone0Chat";
import {
  shouldShowBoardActionButtons,
  shouldShowBoardComposer,
  shouldShowBoardQuizBox,
  shouldShowBoardTeachbackInput,
} from "@/lib/learning/inlineBoardChat";
import {
  buildLearnBoardTimeline,
  conversationEpisodeShowsThinking,
  conversationOwnedAssistantTextIds,
  shouldCompleteVtseStageOnItem,
  conceptVtseStageDoneAction,
  lastVtseTimelineMessageId,
} from "@/lib/learning/learnBoardTimeline";
import { shouldShowStageTransitionThinking } from "@/lib/learning/boardThinking";
import { resolveLatestStreamableAssistantId } from "@/lib/learning/inlineBoardChat";
import { logHandleExplanationComplete } from "@/lib/learning/instructionLifecycle";
import { useFlowCheckpointController } from "@/lib/learning/useFlowCheckpointController";
import { isConceptVtseStageDoneAccepted } from "@/lib/learning/vtseStageDoneGuard";
import { useLearnSessionChrome } from "@/lib/learning/LearnSessionChrome";
import { resolveTopicTitle } from "@/lib/learning/resolveTopicTitle";
import { SessionCompleteModal } from "@/components/session/SessionCompleteModal";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
function LearnInner() {
  const params = useParams();
  const router = useRouter();
  const searchParams = useSearchParams();
  const topicId = params.topicId as string;
  const { token, isInstitution } = useAuth();
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [endResult, setEndResult] = useState<EndSessionResult | null>(null);
  const [resumePrompt, setResumePrompt] =
    useState<StartSessionResumePrompt | null>(null);
  const [resumeBusy, setResumeBusy] = useState(false);
  const planAutoTransitionRef = useRef(false);
  const lastAutoStartPlanRef = useRef<string | null>(null);
  const preserveChatOnSessionChangeRef = useRef(false);
  const panelHandoffArchiveRef = useRef(false);
  const planContinuationBootstrapRef = useRef(false);

  const handleTopicCompleted = useCallback(
    (result: EndSessionResult, progression?: PlanProgressionView | null) => {
      if (planAutoTransitionRef.current) {
        planAutoTransitionRef.current = false;
        return;
      }
      const nextPlanId =
        progression?.transition?.auto_start?.catalog_session_plan_id?.trim() ??
        null;
      const sessionPlanComplete =
        progression?.transition?.session_complete === true;
      if (nextPlanId && sessionPlanComplete) {
        planAutoTransitionRef.current = true;
        return;
      }
      setEndResult(result);
    },
    []
  );

  const {
    messages,
    loading,
    loadingKind,
    sendMessage,
    bootstrapSession,
    loadHistoryForSession,
    clearMessages,
    sessionUi,
    inputEnabled,
    actionButtonsDisabled,
    error,
    recommendedTopics,
    planProgression,
    isRestoredSession,
    restoredMessageCount,
    persistedBoardTurns,
    restoreStaticBeatIndex,
    restoredHistoryMessages,
    studentScratchpadNotes,
    setStudentScratchpadNotes,
    refreshSessionMeta,
  } = useChat(token, sessionId, topicId, {
    onTopicCompleted: handleTopicCompleted,
    preserveChatOnSessionChangeRef,
  });
  const loadHistoryRef = useRef(loadHistoryForSession);
  loadHistoryRef.current = loadHistoryForSession;
  const bootstrapSessionRef = useRef(bootstrapSession);
  bootstrapSessionRef.current = bootstrapSession;
  const sendMessageRef = useRef(sendMessage);
  sendMessageRef.current = sendMessage;
  const refreshSessionMetaRef = useRef(refreshSessionMeta);
  refreshSessionMetaRef.current = refreshSessionMeta;
  const restoreAutomationGatedRef = useRef(false);
  const resumeInteractionLockedRef = useRef(false);
  const lastSavedBeatRef = useRef<number | null>(null);
  const vtseTimelineIdRef = useRef<string | undefined>(undefined);
  const vtseMessageId = lastVtseTimelineMessageId(messages);
  const vtseMessage = vtseMessageId
    ? messages.find((m) => m.id === vtseMessageId)
    : undefined;
  const vtseTimeline =
    vtseMessage &&
    "instruction_timeline_v3" in vtseMessage &&
    vtseMessage.instruction_timeline_v3
      ? (vtseMessage.instruction_timeline_v3 as { timeline_id?: string })
      : null;
  vtseTimelineIdRef.current = vtseTimeline?.timeline_id || undefined;
  const flowCheckpoint = useFlowCheckpointController({
    sessionId,
    sendMessage,
    getTimelineId: () => vtseTimelineIdRef.current,
    onBeatCheckpoint: useCallback(
      (beatIndex: number) => {
        if (lastSavedBeatRef.current === beatIndex) return;
        lastSavedBeatRef.current = beatIndex;
        if (!token || !sessionId) return;
        void saveBoardCheckpoint(token, sessionId, beatIndex, {
          timelineId: vtseTimelineIdRef.current,
        }).catch(() => {
          /* ignore */
        });
      },
      [token, sessionId]
    ),
  });
  const learnChrome = useLearnSessionChrome();
  const topicNameFromUrl = searchParams.get("topicName")?.trim() || null;
  const [topicTitle, setTopicTitleLocal] = useState<string | null>(topicNameFromUrl);
  const [sessionError, setSessionError] = useState<string | null>(null);
  const [conceptPanelExpanded, setConceptPanelExpanded] = useState(false);
  const [clusterPanelExpanded, setClusterPanelExpanded] = useState(false);
  const [teachbackPanelExpanded, setTeachbackPanelExpanded] = useState(false);
  const [scratchpadExpanded, setScratchpadExpanded] = useState(false);
  const [scratchpadSaveStatus, setScratchpadSaveStatus] = useState<
    "idle" | "saving" | "saved" | "error"
  >("idle");
  const [notesPanelExpanded, setNotesPanelExpanded] = useState(false);
  const [notesHistory, setNotesHistory] = useState<ConceptNotesEntry[]>([]);
  const [sessionArchivedNotesSections, setSessionArchivedNotesSections] =
    useState<NotesPanelSection[]>([]);
  const [notesContinueBusy, setNotesContinueBusy] = useState(false);
  const [questionHistory, setQuestionHistory] = useState<ConceptQuestionRecord[]>(
    []
  );
  const [savedConceptThread, setSavedConceptThread] = useState<
    ConceptThreadItem[]
  >([]);
  const [sessionArchivedConceptSections, setSessionArchivedConceptSections] =
    useState<PanelSection<ConceptThreadItem>[]>([]);
  const [withinSessionConceptSections, setWithinSessionConceptSections] =
    useState<PanelSection<ConceptThreadItem>[]>([]);
  const conceptPanelMessageEpochRef = useRef(0);
  const [conceptPanelMessageTick, setConceptPanelMessageTick] = useState(0);
  const conceptQActivePrevRef = useRef(false);
  const prevConceptForArchiveRef = useRef<string | undefined>();
  const [clusterQuestionHistory, setClusterQuestionHistory] = useState<
    ClusterQuizRecord[]
  >([]);
  const [savedClusterThread, setSavedClusterThread] = useState<
    ClusterThreadItem[]
  >([]);
  const [sessionArchivedClusterSections, setSessionArchivedClusterSections] =
    useState<PanelSection<ClusterThreadItem>[]>([]);
  const [withinSessionClusterSections, setWithinSessionClusterSections] =
    useState<PanelSection<ClusterThreadItem>[]>([]);
  const clusterPanelMessageEpochRef = useRef(0);
  const [clusterPanelMessageTick, setClusterPanelMessageTick] = useState(0);
  const prevClusterIndexForArchiveRef = useRef<number | undefined>();
  const [savedTeachbackThread, setSavedTeachbackThread] = useState<
    ClusterTeachbackThreadItem[]
  >([]);
  const [sessionArchivedTeachbackSections, setSessionArchivedTeachbackSections] =
    useState<PanelSection<ClusterTeachbackThreadItem>[]>([]);
  const [withinSessionTeachbackSections, setWithinSessionTeachbackSections] =
    useState<PanelSection<ClusterTeachbackThreadItem>[]>([]);
  const teachbackPanelMessageEpochRef = useRef(0);
  const [teachbackPanelMessageTick, setTeachbackPanelMessageTick] = useState(0);
  const prevClusterIndexForTeachbackArchiveRef = useRef<number | undefined>();
  const [teachbackQuestionHistory, setTeachbackQuestionHistory] = useState<
    ClusterTeachbackQuestionRecord[]
  >([]);
  const clusterTbReteachTriggeredRef = useRef<string | null>(null);
  const clusterQActivePrevRef = useRef(false);
  const notesReadyHandledRef = useRef(false);
  const sessionIdPrevRef = useRef<string | null>(null);
  const planProgressionRef = useRef(planProgression);
  planProgressionRef.current = planProgression;
  const savedConceptThreadRef = useRef(savedConceptThread);
  savedConceptThreadRef.current = savedConceptThread;
  const savedClusterThreadRef = useRef(savedClusterThread);
  savedClusterThreadRef.current = savedClusterThread;
  const savedTeachbackThreadRef = useRef(savedTeachbackThread);
  savedTeachbackThreadRef.current = savedTeachbackThread;
  const withinSessionConceptSectionsRef = useRef(withinSessionConceptSections);
  withinSessionConceptSectionsRef.current = withinSessionConceptSections;
  const withinSessionClusterSectionsRef = useRef(withinSessionClusterSections);
  withinSessionClusterSectionsRef.current = withinSessionClusterSections;
  const withinSessionTeachbackSectionsRef = useRef(withinSessionTeachbackSections);
  withinSessionTeachbackSectionsRef.current = withinSessionTeachbackSections;
  const notesHistoryRef = useRef(notesHistory);
  notesHistoryRef.current = notesHistory;
  const [resolving, setResolving] = useState(true);
  const [catalogPlans, setCatalogPlans] = useState<CatalogSessionPlanSummary[]>([]);
  const [showCatalogPlanPicker, setShowCatalogPlanPicker] = useState(false);
  const bootstrappedSessionRef = useRef<string | null>(null);
  const buildLearnQuery = useCallback(
    (session: string | null, catalogPlanId?: string | null) => {
      const sp = new URLSearchParams();
      if (session) sp.set("sessionId", session);
      const sj = searchParams.get("subjectId");
      if (sj) sp.set("subjectId", sj);
      if (catalogPlanId) sp.set("catalogPlanId", catalogPlanId);
      const q = sp.toString();
      return q ? `?${q}` : "";
    },
    [searchParams]
  );

  /** Org subject id (URL query) + profile class id for TeacherTopic / session scoping. */
  const resolveInstitutionScope =
    useCallback(async (): Promise<StartSessionScope | undefined> => {
      if (!isInstitution || !token) return undefined;
      const orgSubjectId = searchParams.get("subjectId");
      if (!orgSubjectId?.trim()) return undefined;
      try {
        const p = await getStudentProfile(token);
        const cid = p.class_id?.trim();
        if (!cid) return undefined;
        return {
          curriculum_class_id: cid,
          curriculum_subject_id: orgSubjectId.trim(),
        };
      } catch {
        return undefined;
      }
    }, [isInstitution, token, searchParams]);

  useEffect(() => {
    clearMessages();
    bootstrappedSessionRef.current = null;
    setResumePrompt(null);
    setSessionArchivedConceptSections([]);
    setWithinSessionConceptSections([]);
    setSessionArchivedClusterSections([]);
    setWithinSessionClusterSections([]);
    setSessionArchivedTeachbackSections([]);
    setWithinSessionTeachbackSections([]);
    setSessionArchivedNotesSections([]);
    setSavedConceptThread([]);
    setSavedClusterThread([]);
    setSavedTeachbackThread([]);
    setNotesHistory([]);
    setQuestionHistory([]);
    setClusterQuestionHistory([]);
    setTeachbackQuestionHistory([]);
    conceptPanelMessageEpochRef.current = 0;
    clusterPanelMessageEpochRef.current = 0;
    teachbackPanelMessageEpochRef.current = 0;
    setConceptPanelMessageTick((t) => t + 1);
    setClusterPanelMessageTick((t) => t + 1);
    setTeachbackPanelMessageTick((t) => t + 1);
    prevConceptForArchiveRef.current = undefined;
    prevClusterIndexForArchiveRef.current = undefined;
    prevClusterIndexForTeachbackArchiveRef.current = undefined;
  }, [topicId, clearMessages]);

  // Unlock HTMLAudioElement playback on first user gesture (autoplay policy).
  useEffect(() => {
    const unlock = () => {
      unlockAudioPlayback();
      window.removeEventListener("pointerdown", unlock);
      window.removeEventListener("keydown", unlock);
    };
    window.addEventListener("pointerdown", unlock);
    window.addEventListener("keydown", unlock);
    return () => {
      window.removeEventListener("pointerdown", unlock);
      window.removeEventListener("keydown", unlock);
    };
  }, []);

  useEffect(() => {
    if (!learnChrome?.setClusterLabel) return;
    if (sessionUi.sessionMeta) {
      learnChrome.setClusterLabel(
        `Cluster ${sessionUi.sessionMeta.cluster_index + 1} of ${sessionUi.sessionMeta.total_clusters}`
      );
    }
  }, [learnChrome, sessionUi.sessionMeta]);

  useEffect(() => {
    learnChrome?.setConceptLabel(sessionUi.currentConcept?.trim() || null);
    return () => learnChrome?.setConceptLabel(null);
  }, [learnChrome, sessionUi.currentConcept]);

  useEffect(() => {
    learnChrome?.setPlanProgression(planProgression);
    return () => learnChrome?.setPlanProgression(null);
  }, [learnChrome, planProgression]);

  useEffect(() => {
    if (!token || !topicId) return;
    let cancelled = false;
    void (async () => {
      const name = await resolveTopicTitle(token, topicId, {
        subjectId: searchParams.get("subjectId"),
        isInstitution,
        urlTopicName: topicNameFromUrl,
      });
      if (cancelled) return;
      setTopicTitleLocal(name);
      learnChrome?.setTopicTitle(name);
    })();
    return () => {
      cancelled = true;
    };
  }, [token, topicId, searchParams, isInstitution, learnChrome, topicNameFromUrl]);

  useEffect(() => {
    let cancelled = false;
    async function bootstrap() {
      if (!token || !topicId) return;
      const fromQuery = searchParams.get("sessionId");
      if (fromQuery) {
        setSessionId(fromQuery);
        setResumePrompt(null);
        setSessionError(null);
        setResolving(false);
        return;
      }
      setResolving(true);
      setSessionError(null);
      setShowCatalogPlanPicker(false);
      try {
        const scope = await resolveInstitutionScope();
        const catalogPlanFromUrl = searchParams.get("catalogPlanId");
        if (!isInstitution && !fromQuery && !catalogPlanFromUrl) {
          const plans = await listStudentCatalogSessionPlans(token, topicId);
          if (cancelled) return;
          if (plans.length > 0) {
            setCatalogPlans(plans);
            setShowCatalogPlanPicker(true);
            setResolving(false);
            return;
          }
        }
        const mergedScope: StartSessionScope | undefined = scope
          ? {
              ...scope,
              catalog_session_plan_id: catalogPlanFromUrl ?? scope.catalog_session_plan_id,
            }
          : catalogPlanFromUrl
            ? { catalog_session_plan_id: catalogPlanFromUrl }
            : undefined;
        const out = await startSession(token, topicId, undefined, mergedScope);
        if (cancelled) return;
        if ("type" in out && out.type === "resume_prompt") {
          setResumePrompt(out);
          setSessionId(null);
          setResolving(false);
          return;
        }
        setResumePrompt(null);
        const newId = (out as { id: string }).id;
        setSessionId(newId);
        router.replace(
          `/learn/${topicId}${buildLearnQuery(newId, catalogPlanFromUrl)}`
        );
      } catch (e) {
        if (!cancelled) {
          setSessionError(
            e instanceof Error
              ? e.message
              : "Could not start or resume a session."
          );
        }
      } finally {
        if (!cancelled) setResolving(false);
      }
    }
    void bootstrap();
    return () => {
      cancelled = true;
    };
  }, [
    token,
    topicId,
    searchParams,
    router,
    resolveInstitutionScope,
    buildLearnQuery,
    isInstitution,
  ]);

  useEffect(() => {
    const nextPlanId =
      planProgression?.transition?.auto_start?.catalog_session_plan_id?.trim() ??
      null;
    const sessionPlanComplete =
      planProgression?.transition?.session_complete === true;
    if (!nextPlanId || !token || !topicId || !sessionPlanComplete) return;
    if (lastAutoStartPlanRef.current === nextPlanId) return;
    lastAutoStartPlanRef.current = nextPlanId;
    planAutoTransitionRef.current = true;
    let cancelled = false;
    const timer = window.setTimeout(() => {
      void (async () => {
        try {
          setEndResult(null);
          const scope = await resolveInstitutionScope();
          const mergedScope: StartSessionScope = {
            ...(scope ?? {}),
            catalog_session_plan_id: nextPlanId,
          };
          const out = await startSession(token, topicId, undefined, mergedScope);
          if (cancelled) return;
          if ("type" in out && out.type === "resume_prompt") {
            setResumePrompt(out);
            return;
          }
          const newId = (out as { id: string }).id;
          preserveChatOnSessionChangeRef.current = true;
          panelHandoffArchiveRef.current = true;
          bootstrappedSessionRef.current = newId;
          setSessionId(newId);
          router.replace(`/learn/${topicId}${buildLearnQuery(newId, nextPlanId)}`);
          try {
            await sendMessageRef.current(newId, "__action:ready", { silent: true });
            await refreshSessionMetaRef.current();
          } catch {
            bootstrappedSessionRef.current = null;
            planContinuationBootstrapRef.current = true;
          }
        } catch (e) {
          if (!cancelled) {
            setSessionError(
              e instanceof Error
                ? e.message
                : "Could not start the next planned session."
            );
          }
        }
      })();
    }, 2800);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [
    planProgression,
    token,
    topicId,
    resolveInstitutionScope,
    buildLearnQuery,
    router,
  ]);

  useEffect(() => {
    if (!sessionId || !token || endResult || resolving || sessionError) return;
    if (bootstrappedSessionRef.current === sessionId) return;
    if (planContinuationBootstrapRef.current) {
      planContinuationBootstrapRef.current = false;
      bootstrappedSessionRef.current = sessionId;
      let cancelled = false;
      void (async () => {
        try {
          await sendMessageRef.current(sessionId, "__action:ready", { silent: true });
          if (!cancelled) void refreshSessionMetaRef.current();
        } catch {
          bootstrappedSessionRef.current = null;
        }
      })();
      return () => {
        cancelled = true;
      };
    }
    bootstrappedSessionRef.current = sessionId;
    let cancelled = false;
    void (async () => {
      try {
        const n = await loadHistoryRef.current(sessionId);
        if (cancelled) return;
        if (n === 0) await bootstrapSessionRef.current(sessionId);
      } catch {
        bootstrappedSessionRef.current = null;
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [sessionId, token, topicId, endResult, resolving, sessionError]);

  const onSend = useCallback(
    (text: string) => {
      if (!sessionId || endResult) return;
      unlockAudioPlayback();
      resumeInteractionLockedRef.current = false;
      void sendMessage(sessionId, text);
    },
    [sessionId, sendMessage, endResult]
  );

  const handleScratchpadSave = useCallback(
    async (text: string) => {
      if (!token || !sessionId) return;
      setScratchpadSaveStatus("saving");
      try {
        await saveStudentScratchpad(token, sessionId, text);
        setScratchpadSaveStatus("saved");
      } catch {
        setScratchpadSaveStatus("error");
      }
    },
    [token, sessionId]
  );

  const handleContinueSession = useCallback(async () => {
    if (!token || !topicId || resumeBusy) return;
    unlockAudioPlayback();
    setResumeBusy(true);
    setSessionError(null);
    try {
      const scope = await resolveInstitutionScope();
      const out = await startSession(token, topicId, "continue", scope);
      setResumePrompt(null);
      const newId = (out as { id: string }).id;
      setSessionId(newId);
      router.replace(`/learn/${topicId}${buildLearnQuery(newId)}`);
    } catch (e) {
      setSessionError(
        e instanceof Error ? e.message : "Could not continue the session."
      );
    } finally {
      setResumeBusy(false);
    }
  }, [token, topicId, resumeBusy, router, resolveInstitutionScope, buildLearnQuery]);

  const handleRestartTopic = useCallback(async () => {
    if (!token || !topicId || resumeBusy) return;
    unlockAudioPlayback();
    setResumeBusy(true);
    setSessionError(null);
    try {
      clearMessages();
      const scope = await resolveInstitutionScope();
      const out = await startSession(token, topicId, "restart", scope);
      setResumePrompt(null);
      const newId = (out as { id: string }).id;
      setSessionId(newId);
      bootstrappedSessionRef.current = null;
      router.replace(`/learn/${topicId}${buildLearnQuery(newId)}`);
    } catch (e) {
      setSessionError(
        e instanceof Error ? e.message : "Could not restart the topic."
      );
    } finally {
      setResumeBusy(false);
    }
  }, [
    token,
    topicId,
    resumeBusy,
    router,
    clearMessages,
    resolveInstitutionScope,
    buildLearnQuery,
  ]);

  const chatLocked = Boolean(endResult);

  const closeCompleteModal = useCallback(() => {
    setEndResult(null);
    setSessionId(null);
    clearMessages();
    router.replace("/subjects");
  }, [router, clearMessages]);

  const inputDisabled = chatLocked || !inputEnabled || loading || flowCheckpoint.ui.isActive;

  const inputDisabledHint = (() => {
    if (chatLocked) return null;
    if (loading) return "Thinking…";
    if (sessionUi.activeQuiz || sessionUi.flowState === "quizzing") {
      return "Answer the question below";
    }
    if (sessionUi.flowState === "checking_understanding") {
      return "Use the buttons to continue";
    }
    if (sessionUi.flowState === "explaining" && sessionUi.buttons.length > 0) {
      return 'Use “I have a question” to type your own question';
    }
    if (sessionUi.flowState === "idle" && sessionUi.buttons.length > 0) {
      return "Click an option to continue";
    }
    if (!inputEnabled) {
      return "Follow the lesson steps to continue.";
    }
    return null;
  })();

  const showResumeCard = Boolean(resumePrompt) && !resolving && !sessionError;

  const isTeachbackMode = useMemo(() => {
    if (sessionUi.sessionMeta?.cluster_teachback_active) return false;
    const lastAssistant = [...messages]
      .reverse()
      .find((m) => m.role === "assistant");
    return lastAssistant?.kind === "teachback_prompt";
  }, [messages, sessionUi.sessionMeta?.cluster_teachback_active]);

  const conceptQuestionsActive =
    sessionUi.sessionMeta?.concept_questions_active === true;
  const clusterQuizActive =
    sessionUi.sessionMeta?.cluster_quiz_active === true;
  const clusterTeachbackActive =
    sessionUi.sessionMeta?.cluster_teachback_active === true;
  const clusterTeachbackQuestion =
    sessionUi.sessionMeta?.cluster_teachback_question?.trim() ||
    sessionUi.sessionMeta?.micro_interaction_prompt?.trim() ||
    "";

  const conceptNotesActive =
    sessionUi.sessionMeta?.concept_notes_active === true;

  useEffect(() => {
    const history = sessionUi.sessionMeta?.concept_notes_history;
    if (!history?.length) return;
    setNotesHistory(
      history.map((entry) => ({
        conceptName: entry.concept,
        markdown: entry.markdown,
      }))
    );
  }, [sessionUi.sessionMeta?.concept_notes_history]);

  useEffect(() => {
    if (conceptNotesActive) {
      setNotesPanelExpanded(true);
      notesReadyHandledRef.current = false;
    }
  }, [conceptNotesActive]);

  const handleNotesExpandedChange = useCallback((open: boolean) => {
    setNotesPanelExpanded(open);
  }, []);

  const handleNotesMarkAsRead = useCallback(async () => {
    if (!sessionId || endResult || notesContinueBusy) return;
    setNotesContinueBusy(true);
    setNotesPanelExpanded(false);
    try {
      const result = await sendMessage(
        sessionId,
        "__action:concept_notes_continue",
        { silent: true }
      );
      const tutor = result?.tutor;
      if (tutor?.type === "feedback" && tutor.correct === true) {
        notesReadyHandledRef.current = true;
        const atClusterEnd =
          (tutor as { meta?: { cluster_quiz_ready?: boolean } }).meta
            ?.cluster_quiz_ready === true;
        window.setTimeout(() => {
          void sendMessage(
            sessionId,
            atClusterEnd ? "__action:quiz" : "__action:ready",
            { silent: true }
          );
        }, 900);
      }
    } finally {
      setNotesContinueBusy(false);
    }
  }, [sessionId, endResult, notesContinueBusy, sendMessage]);

  const zone0LearningUi = isZone0LearningUi(
    sessionUi.currentZone,
    sessionUi.flowState
  );

  // Stage-anchored chronological timeline (board episodes + conversation episodes).
  // History is never flow-gated — VTSE/VT do not unmount prior bubbles.
  const learnTimeline = useMemo(
    () => buildLearnBoardTimeline(messages),
    [messages]
  );
  const boardOmitMessageIds = useMemo(
    () => conversationOwnedAssistantTextIds(learnTimeline),
    [learnTimeline]
  );

  const showBoardComposer = shouldShowBoardComposer(sessionUi, {
    isTeachbackMode,
    conceptQuestionsActive,
    clusterQuizActive,
    clusterTeachbackActive,
  });

  const showBoardTeachbackInput = shouldShowBoardTeachbackInput({
    isTeachbackMode,
  });

  const showBoardQuizBox = shouldShowBoardQuizBox(sessionUi, {
    conceptQuestionsActive,
    clusterQuizActive,
    clusterTeachbackActive,
    zone0LearningUi,
  });

  const showBoardActionButtons = shouldShowBoardActionButtons(sessionUi, {
    conceptQuestionsActive,
  });

  const effectiveRestoredBoardTurns = useMemo(() => {
    if (!isRestoredSession) return [];
    const base = persistedBoardTurnsFromRestore(persistedBoardTurns);
    if (base.length === 0) return [];
    return supplementBoardTurnsFromHistoryMessages(
      restoredHistoryMessages,
      base
    );
  }, [
    isRestoredSession,
    persistedBoardTurns,
    restoredHistoryMessages,
  ]);

  const staticRestoreByItemId = useMemo(() => {
    if (!isRestoredSession) return {};
    if (effectiveRestoredBoardTurns.length > 0) {
      return staticRestoreMapFromTurns(effectiveRestoredBoardTurns);
    }
    const textMessages = (
      conceptQuestionsActive
        ? filterBoardMessages(messages)
        : clusterQuizActive
          ? filterBoardMessagesForClusterQuiz(messages)
          : clusterTeachbackActive
            ? filterBoardMessagesForClusterTeachback(messages)
            : messages
    ).filter(
      (m): m is Extract<ChatItem, { role: "assistant"; kind: "text" }> =>
        m.role === "assistant" && m.kind === "text"
    );
    return staticRestoreMapFromChatItems(textMessages, restoreStaticBeatIndex);
  }, [
    isRestoredSession,
    effectiveRestoredBoardTurns,
    messages,
    conceptQuestionsActive,
    clusterQuizActive,
    clusterTeachbackActive,
    restoreStaticBeatIndex,
  ]);

  useLayoutEffect(() => {
    if (!isRestoredSession) {
      restoreAutomationGatedRef.current = false;
      resumeInteractionLockedRef.current = false;
      return;
    }
    restoreAutomationGatedRef.current = true;
    resumeInteractionLockedRef.current = true;
    if (typeof restoreStaticBeatIndex === "number") {
      lastSavedBeatRef.current = restoreStaticBeatIndex;
    }
    const unlock = window.setTimeout(() => {
      restoreAutomationGatedRef.current = false;
    }, 400);
    return () => window.clearTimeout(unlock);
  }, [isRestoredSession, restoreStaticBeatIndex, sessionId]);

  // Whiteboard shows only non–concept-question explanation text.
  const boardItems: BoardItem[] = useMemo(() => {
    const mapChatToBoard = (
      textMessages: Extract<ChatItem, { role: "assistant"; kind: "text" }>[]
    ): BoardItem[] =>
      textMessages.map((m): BoardItem => {
        const raw = m.content;
        const visual = "visual" in m ? (m.visual ?? null) : null;
        const itv3 =
          "instruction_timeline_v3" in m
            ? // eslint-disable-next-line @typescript-eslint/no-explicit-any
              (m.instruction_timeline_v3 as any ?? null)
            : null;
        const ps = "planner_source" in m ? (m.planner_source ?? null) : null;
        const tmeta =
          "timeline_metadata" in m
            ? (m.timeline_metadata as Record<string, unknown> | null)
            : null;
        const content =
          typeof raw === "string"
            ? raw
            : raw != null &&
                typeof raw === "object" &&
                "text" in raw &&
                typeof (raw as { text?: string }).text === "string"
              ? (raw as { text: string }).text
              : "";
        return {
          id: m.id,
          type: "text",
          content,
          visual,
          ...(itv3 != null ? { instruction_timeline_v3: itv3 } : {}),
          ...(ps != null ? { planner_source: ps } : {}),
          ...(tmeta != null ? { timeline_metadata: tmeta } : {}),
          ...("writingMode" in m && m.writingMode != null
            ? { writingMode: m.writingMode }
            : {}),
          ...("displayText" in m && m.displayText !== undefined
            ? { displayText: m.displayText }
            : {}),
          ...("boardWrites" in m &&
          Array.isArray(m.boardWrites) &&
          m.boardWrites.length
            ? { boardWrites: m.boardWrites }
            : {}),
        };
      });

    if (isRestoredSession && effectiveRestoredBoardTurns.length > 0) {
      const fromPersisted = mapChatToBoard(
        effectiveRestoredBoardTurns
          .map((t) => boardTurnToChatItem(t))
          .filter(
            (m): m is Extract<ChatItem, { role: "assistant"; kind: "text" }> =>
              m.role === "assistant" &&
              m.kind === "text" &&
              !boardOmitMessageIds.has(m.id)
          ) as Extract<ChatItem, { role: "assistant"; kind: "text" }>[]
      );
      const newChatBoard = mapChatToBoard(
        (conceptQuestionsActive ? filterBoardMessages(messages) : messages)
          .slice(restoredMessageCount)
          .filter(
            (m): m is Extract<ChatItem, { role: "assistant"; kind: "text" }> =>
              m.role === "assistant" &&
              m.kind === "text" &&
              !boardOmitMessageIds.has(m.id)
          )
      );
      return [...fromPersisted, ...newChatBoard];
    }

    const textMessages = (
      conceptQuestionsActive
        ? filterBoardMessages(messages)
        : clusterQuizActive
          ? filterBoardMessagesForClusterQuiz(messages)
          : clusterTeachbackActive
            ? filterBoardMessagesForClusterTeachback(messages)
            : messages.filter(
                (m): m is Extract<ChatItem, { role: "assistant"; kind: "text" }> =>
                  m.role === "assistant" &&
                  m.kind === "text" &&
                  (isClusterTeachbackTutorMessage(m) ||
                    !(m as { clusterTeachback?: boolean }).clusterTeachback)
              )
    ).filter((m) => !boardOmitMessageIds.has(m.id));
    return mapChatToBoard(textMessages);
  }, [
    messages,
    conceptQuestionsActive,
    clusterQuizActive,
    clusterTeachbackActive,
    isRestoredSession,
    effectiveRestoredBoardTurns,
    restoredMessageCount,
    boardOmitMessageIds,
  ]);
  // ── Explanation streaming gate ────────────────────────────────────────────
  // We need quizHeld to be TRUE in the very same render where the new board
  // item (explanation) arrives — before ChatWindow even paints once.  Using
  // useState + useEffect for this creates a one-render window where the quiz
  // reveal timer can start (quizHeld=false), then immediately get cancelled
  // on the next commit.  With concurrent React that window is real.
  //
  // Fix: track the ID of the last board item whose streaming has completed.
  // `explanationStreaming` is then a pure, synchronous derivation: the latest
  // board item is streaming whenever its ID ≠ the last completed ID.
  // Declared here (after boardItems) to avoid the temporal dead zone.
  const [completedBoardItemId, setCompletedBoardItemId] = useState<string | null>(null);

  // Prefer chronological latest streamable assistant text — includes conversational
  // bubbles omitted from boardItems (otherwise Zone0/pedagogy lose TTS completion).
  const latestBoardItemId = useMemo(
    () =>
      resolveLatestStreamableAssistantId(
        messages,
        boardItems.map((b) => b.id),
        boardOmitMessageIds
      ),
    [messages, boardItems, boardOmitMessageIds]
  );

  const latestStreamIsInlineBubble =
    latestBoardItemId != null && boardOmitMessageIds.has(latestBoardItemId);
  const latestStreamIsOnBoard =
    latestBoardItemId != null &&
    boardItems.some((b) => b.id === latestBoardItemId);
  const lastDurableBoardItemId =
    boardItems.length > 0 ? boardItems[boardItems.length - 1]!.id : null;
  const awaitVtseBoardCompletion =
    sessionUi.sessionMeta?.concept_teaching_await_vtse_done === 1 ||
    sessionUi.sessionMeta?.concept_teaching_await_vtse_done === true;

  useEffect(() => {
    if (!isRestoredSession || !latestBoardItemId) return;
    setCompletedBoardItemId(latestBoardItemId);
  }, [isRestoredSession, latestBoardItemId]);

  // Synchronously true from the moment a new board item arrives.
  const explanationStreaming =
    latestBoardItemId !== null && latestBoardItemId !== completedBoardItemId;

  const microPromptText = microInteractionPrompt(sessionUi.sessionMeta);
  const conceptCheckStem = resolveConceptCheckStem(sessionUi.sessionMeta);
  const showConceptCheckQuestion = shouldShowConceptCheckQuestion(
    sessionUi.sessionMeta
  );
  const showMicroQuestion = shouldShowMicroInteractionPrompt(
    sessionUi.sessionMeta?.micro_quiz_hold,
    explanationStreaming,
    microPromptText || conceptCheckStem,
  );
  // Concept Check stem visibility must not depend solely on micro_quiz_hold /
  // streaming. Interaction (input/MCQ) still respects hold + !streaming.
  const conceptCheckPromptForUi = conceptCheckStem || microPromptText;

  const conceptQuestionIndex =
    sessionUi.sessionMeta?.concept_question_index ?? 0;
  const clusterQuestionIndex =
    sessionUi.sessionMeta?.cluster_quiz_index ?? 0;

  const conceptPanelMessages = useMemo(
    () => messages.slice(conceptPanelMessageEpochRef.current),
    [messages, conceptPanelMessageTick]
  );
  const clusterPanelMessages = useMemo(
    () => messages.slice(clusterPanelMessageEpochRef.current),
    [messages, clusterPanelMessageTick]
  );
  const teachbackPanelMessages = useMemo(
    () => messages.slice(teachbackPanelMessageEpochRef.current),
    [messages, teachbackPanelMessageTick]
  );

  const conceptThread = useMemo(
    () =>
      buildConceptThread(conceptPanelMessages, questionHistory, {
        showPendingQuestion: showConceptCheckQuestion,
        pendingIndex: conceptQuestionIndex,
      }),
    [
      conceptPanelMessages,
      questionHistory,
      showConceptCheckQuestion,
      conceptQuestionIndex,
    ]
  );

  const clusterThread = useMemo(
    () =>
      buildClusterQuizThread(clusterPanelMessages, clusterQuestionHistory, {
        showPendingQuestion: clusterQuizActive && showMicroQuestion,
        pendingIndex: clusterQuestionIndex,
      }),
    [
      clusterPanelMessages,
      clusterQuestionHistory,
      clusterQuizActive,
      showMicroQuestion,
      clusterQuestionIndex,
    ]
  );

  const clusterTeachbackThread = useMemo(
    () =>
      buildClusterTeachbackThread(
        teachbackPanelMessages,
        teachbackQuestionHistory,
        {
          showPendingQuestion:
            clusterTeachbackActive &&
            !explanationStreaming &&
            !loading &&
            sessionUi.sessionMeta?.cluster_teachback_phase !== "reteach_pending" &&
            Boolean(clusterTeachbackQuestion.trim()),
        }
      ),
    [
      teachbackPanelMessages,
      teachbackQuestionHistory,
      clusterTeachbackActive,
      clusterTeachbackQuestion,
      explanationStreaming,
      loading,
      sessionUi.sessionMeta?.cluster_teachback_phase,
    ]
  );

  const displayTeachbackThread = useMemo(() => {
    const current = clusterTeachbackActive
      ? clusterTeachbackThread
      : savedTeachbackThread;
    return flattenThreadSections(
      sessionArchivedTeachbackSections,
      withinSessionTeachbackSections,
      activeSessionHeading(planProgression),
      current,
      (id, heading) => ({ id, kind: "section", heading })
    );
  }, [
    clusterTeachbackActive,
    clusterTeachbackThread,
    savedTeachbackThread,
    sessionArchivedTeachbackSections,
    withinSessionTeachbackSections,
    planProgression,
  ]);

  const conceptQuestionClarifying = Boolean(
    sessionUi.sessionMeta?.concept_question_clarifying
  );
  const conceptQuestionFollowup = Boolean(
    sessionUi.sessionMeta?.concept_question_followup
  );
  const displayConceptThread = useMemo(() => {
    const current = conceptQuestionsActive ? conceptThread : savedConceptThread;
    return flattenThreadSections(
      sessionArchivedConceptSections,
      withinSessionConceptSections,
      activeSessionHeading(planProgression),
      current,
      (id, heading) => ({ id, kind: "section", heading })
    );
  }, [
    conceptQuestionsActive,
    conceptThread,
    savedConceptThread,
    sessionArchivedConceptSections,
    withinSessionConceptSections,
    planProgression,
  ]);
  const displayClusterThread = useMemo(() => {
    const current = clusterQuizActive ? clusterThread : savedClusterThread;
    return flattenThreadSections(
      sessionArchivedClusterSections,
      withinSessionClusterSections,
      activeSessionHeading(planProgression),
      current,
      (id, heading) => ({ id, kind: "section", heading })
    );
  }, [
    clusterQuizActive,
    clusterThread,
    savedClusterThread,
    sessionArchivedClusterSections,
    withinSessionClusterSections,
    planProgression,
  ]);
  const displayNotesSections = useMemo(
    () =>
      flattenNotesSections(
        sessionArchivedNotesSections,
        activeSessionHeading(planProgression),
        notesHistory
      ),
    [sessionArchivedNotesSections, planProgression, notesHistory]
  );
  const clusterQuestionClarifying = Boolean(
    sessionUi.sessionMeta?.cluster_quiz_clarifying
  );
  const clusterQuestionFollowup = Boolean(
    sessionUi.sessionMeta?.cluster_quiz_followup
  );

  useLayoutEffect(() => {
    const prev = sessionIdPrevRef.current;
    sessionIdPrevRef.current = sessionId;
    if (!prev || !sessionId || prev === sessionId) return;
    if (!panelHandoffArchiveRef.current) return;
    panelHandoffArchiveRef.current = false;

    const heading = completedSessionHeading(planProgressionRef.current);
    const msgEpoch = messages.length;

    const collectConceptItems = (): ConceptThreadItem[] => {
      const items: ConceptThreadItem[] = [];
      for (const section of withinSessionConceptSectionsRef.current) {
        if (section.items.length === 0) continue;
        items.push({ id: section.id, kind: "section", heading: section.heading });
        items.push(...withPrefixedIds(section.items, section.id));
      }
      if (savedConceptThreadRef.current.length > 0) {
        items.push(
          ...withPrefixedIds(savedConceptThreadRef.current, "concept-final")
        );
      }
      return items;
    };
    const conceptItems = collectConceptItems();
    if (conceptItems.length > 0) {
      setSessionArchivedConceptSections((archived) => [
        ...archived,
        { id: `session-concept-${prev}`, heading, items: conceptItems },
      ]);
    }
    setWithinSessionConceptSections([]);
    setSavedConceptThread([]);
    setQuestionHistory([]);
    conceptPanelMessageEpochRef.current = msgEpoch;
    setConceptPanelMessageTick((t) => t + 1);

    const collectClusterItems = (): ClusterThreadItem[] => {
      const items: ClusterThreadItem[] = [];
      for (const section of withinSessionClusterSectionsRef.current) {
        if (section.items.length === 0) continue;
        items.push({ id: section.id, kind: "section", heading: section.heading });
        items.push(...withPrefixedIds(section.items, section.id));
      }
      if (savedClusterThreadRef.current.length > 0) {
        items.push(
          ...withPrefixedIds(savedClusterThreadRef.current, "cluster-final")
        );
      }
      return items;
    };
    const clusterItems = collectClusterItems();
    if (clusterItems.length > 0) {
      setSessionArchivedClusterSections((archived) => [
        ...archived,
        { id: `session-cluster-${prev}`, heading, items: clusterItems },
      ]);
    }
    setWithinSessionClusterSections([]);
    setSavedClusterThread([]);
    setClusterQuestionHistory([]);
    clusterPanelMessageEpochRef.current = msgEpoch;
    setClusterPanelMessageTick((t) => t + 1);

    const collectTeachbackItems = (): ClusterTeachbackThreadItem[] => {
      const items: ClusterTeachbackThreadItem[] = [];
      for (const section of withinSessionTeachbackSectionsRef.current) {
        if (section.items.length === 0) continue;
        items.push({ id: section.id, kind: "section", heading: section.heading });
        items.push(...withPrefixedIds(section.items, section.id));
      }
      if (savedTeachbackThreadRef.current.length > 0) {
        items.push(
          ...withPrefixedIds(savedTeachbackThreadRef.current, "teachback-final")
        );
      }
      return items;
    };
    const teachbackItems = collectTeachbackItems();
    if (teachbackItems.length > 0) {
      setSessionArchivedTeachbackSections((archived) => [
        ...archived,
        { id: `session-teachback-${prev}`, heading, items: teachbackItems },
      ]);
    }
    setWithinSessionTeachbackSections([]);
    setSavedTeachbackThread([]);
    setTeachbackQuestionHistory([]);
    teachbackPanelMessageEpochRef.current = msgEpoch;
    setTeachbackPanelMessageTick((t) => t + 1);

    if (notesHistoryRef.current.length > 0) {
      setSessionArchivedNotesSections((archived) => [
        ...archived,
        {
          id: `session-notes-${prev}`,
          heading,
          entries: notesHistoryRef.current,
        },
      ]);
    }
    setNotesHistory([]);
    prevConceptForArchiveRef.current = undefined;
    prevClusterIndexForArchiveRef.current = undefined;
    prevClusterIndexForTeachbackArchiveRef.current = undefined;
  }, [sessionId, messages.length]);

  useEffect(() => {
    const concept = sessionUi.currentConcept?.trim();
    if (!conceptQuestionsActive) {
      prevConceptForArchiveRef.current = concept;
      return;
    }
    const prevConcept = prevConceptForArchiveRef.current;
    if (prevConcept && concept && prevConcept !== concept) {
      const thread = savedConceptThreadRef.current;
      if (thread.length > 0) {
        setWithinSessionConceptSections((sections) => {
          if (sections.some((s) => s.id === `concept-${prevConcept}`)) {
            return sections;
          }
          return [
            ...sections,
            { id: `concept-${prevConcept}`, heading: prevConcept, items: thread },
          ];
        });
        setSavedConceptThread([]);
      }
      setQuestionHistory([]);
      conceptPanelMessageEpochRef.current = messages.length;
      setConceptPanelMessageTick((t) => t + 1);
    }
    prevConceptForArchiveRef.current = concept;
  }, [sessionUi.currentConcept, conceptQuestionsActive, messages.length]);

  useEffect(() => {
    const clusterIndex = sessionUi.sessionMeta?.cluster_index;
    if (!clusterQuizActive || clusterIndex == null) {
      prevClusterIndexForArchiveRef.current = clusterIndex;
      return;
    }
    const prevIndex = prevClusterIndexForArchiveRef.current;
    if (prevIndex != null && prevIndex !== clusterIndex) {
      const thread = savedClusterThreadRef.current;
      if (thread.length > 0) {
        const heading = clusterSectionHeading(prevIndex);
        setWithinSessionClusterSections((sections) => {
          if (sections.some((s) => s.id === `cluster-${prevIndex}`)) {
            return sections;
          }
          return [
            ...sections,
            { id: `cluster-${prevIndex}`, heading, items: thread },
          ];
        });
        setSavedClusterThread([]);
      }
      setClusterQuestionHistory([]);
      clusterPanelMessageEpochRef.current = messages.length;
      setClusterPanelMessageTick((t) => t + 1);
    }
    prevClusterIndexForArchiveRef.current = clusterIndex;
  }, [sessionUi.sessionMeta?.cluster_index, clusterQuizActive, messages.length]);

  useEffect(() => {
    const clusterIndex = sessionUi.sessionMeta?.cluster_index;
    if (!clusterTeachbackActive || clusterIndex == null) {
      prevClusterIndexForTeachbackArchiveRef.current = clusterIndex;
      return;
    }
    const prevIndex = prevClusterIndexForTeachbackArchiveRef.current;
    if (prevIndex != null && prevIndex !== clusterIndex) {
      const thread = savedTeachbackThreadRef.current;
      if (thread.length > 0) {
        const heading = clusterSectionHeading(prevIndex);
        setWithinSessionTeachbackSections((sections) => {
          if (sections.some((s) => s.id === `cluster-tb-${prevIndex}`)) {
            return sections;
          }
          return [
            ...sections,
            { id: `cluster-tb-${prevIndex}`, heading, items: thread },
          ];
        });
        setSavedTeachbackThread([]);
      }
      setTeachbackQuestionHistory([]);
      teachbackPanelMessageEpochRef.current = messages.length;
      setTeachbackPanelMessageTick((t) => t + 1);
      clusterTbReteachTriggeredRef.current = null;
    }
    prevClusterIndexForTeachbackArchiveRef.current = clusterIndex;
  }, [
    sessionUi.sessionMeta?.cluster_index,
    clusterTeachbackActive,
    messages.length,
  ]);

  useEffect(() => {
    if (!clusterTeachbackActive || !clusterTeachbackQuestion.trim()) return;
    const text = clusterTeachbackQuestion.trim();
    setTeachbackQuestionHistory((prev) => {
      if (prev.some((q) => q.text === text)) return prev;
      return [...prev, { id: `ctb-q-${prev.length}`, text }];
    });
  }, [clusterTeachbackActive, clusterTeachbackQuestion]);

  useEffect(() => {
    if (!sessionId || !clusterTeachbackActive || loading || explanationStreaming) {
      return;
    }
    if (sessionUi.sessionMeta?.cluster_teachback_phase !== "reteach_pending") {
      return;
    }
    const lastAssistant = [...messages]
      .reverse()
      .find(
        (m) =>
          m.role === "assistant" &&
          m.kind === "feedback" &&
          (m as { clusterTeachback?: boolean }).clusterTeachback
      );
    if (!lastAssistant) return;
    if (clusterTbReteachTriggeredRef.current === lastAssistant.id) return;
    clusterTbReteachTriggeredRef.current = lastAssistant.id;
    lastSavedBeatRef.current = null;
    vtseStageDoneGuardRef.current = null;
    const timer = window.setTimeout(() => {
      void sendMessage(sessionId, "__action:cluster_teachback_reteach", {
        silent: true,
      });
    }, 2200);
    return () => window.clearTimeout(timer);
  }, [
    messages,
    sessionId,
    loading,
    explanationStreaming,
    sendMessage,
    clusterTeachbackActive,
    sessionUi.sessionMeta?.cluster_teachback_phase,
  ]);

  const clusterTbActivePrevRef = useRef(false);
  useEffect(() => {
    const wasActive = clusterTbActivePrevRef.current;
    clusterTbActivePrevRef.current = clusterTeachbackActive;
    if (wasActive && !clusterTeachbackActive && clusterTeachbackThread.length > 0) {
      setSavedTeachbackThread(clusterTeachbackThread);
      setTeachbackPanelExpanded(false);
    }
  }, [clusterTeachbackActive, clusterTeachbackThread]);

  useEffect(() => {
    if (!clusterTeachbackActive) return;
    if (explanationStreaming) {
      setTeachbackPanelExpanded(false);
      return;
    }
    setTeachbackPanelExpanded(true);
  }, [clusterTeachbackActive, explanationStreaming]);

  useEffect(() => {
    const wasActive = conceptQActivePrevRef.current;
    conceptQActivePrevRef.current = conceptQuestionsActive;
    // Concept Check arm: clear VTSE/board streaming ownership so the panel can
    // render immediately (stage_done no longer appends a board bubble).
    if (!wasActive && conceptQuestionsActive && latestBoardItemId != null) {
      setCompletedBoardItemId(latestBoardItemId);
    }
    if (wasActive && !conceptQuestionsActive && conceptThread.length > 0) {
      setSavedConceptThread(conceptThread);
      setConceptPanelExpanded(false);
    }
  }, [conceptQuestionsActive, conceptThread, latestBoardItemId]);

  useEffect(() => {
    const wasActive = clusterQActivePrevRef.current;
    clusterQActivePrevRef.current = clusterQuizActive;
    if (wasActive && !clusterQuizActive && clusterThread.length > 0) {
      setSavedClusterThread(clusterThread);
      setClusterPanelExpanded(false);
    }
  }, [clusterQuizActive, clusterThread]);

  useEffect(() => {
    if (!clusterQuizActive || !microPromptText.trim() || !showMicroQuestion) return;
    setClusterQuestionHistory((prev) => {
      if (prev.some((q) => q.index === clusterQuestionIndex)) return prev;
      return [
        ...prev,
        { index: clusterQuestionIndex, text: microPromptText.trim() },
      ];
    });
  }, [clusterQuizActive, microPromptText, clusterQuestionIndex, showMicroQuestion]);

  useEffect(() => {
    if (!conceptQuestionsActive || !conceptCheckPromptForUi.trim()) return;
    if (!showConceptCheckQuestion) return;
    setQuestionHistory((prev) => {
      if (prev.some((q) => q.index === conceptQuestionIndex)) return prev;
      return [
        ...prev,
        { index: conceptQuestionIndex, text: conceptCheckPromptForUi.trim() },
      ];
    });
  }, [
    conceptQuestionsActive,
    conceptCheckPromptForUi,
    conceptQuestionIndex,
    showConceptCheckQuestion,
  ]);

  const openConceptPanel =
    showConceptCheckQuestion ||
    showMicroQuestion ||
    sessionUi.buttons.length > 0 ||
    conceptQuestionClarifying;

  useEffect(() => {
    if (!conceptQuestionsActive) return;
    // Concept Check is panel-owned — do not keep the panel collapsed for a
    // stale VTSE streaming gate once the stage is armed with a stem.
    if (explanationStreaming && !showConceptCheckQuestion) {
      setConceptPanelExpanded(false);
      return;
    }
    if (openConceptPanel) {
      setConceptPanelExpanded(true);
    }
  }, [
    conceptQuestionsActive,
    explanationStreaming,
    openConceptPanel,
    showConceptCheckQuestion,
  ]);

  const conceptQuestionTypeEffective = resolveConceptQuestionType(
    sessionUi.sessionMeta,
    conceptCheckPromptForUi
  );
  const conceptQuestionOptionsForUi =
    conceptQuestionTypeEffective === "mcq"
      ? (sessionUi.sessionMeta?.concept_question_options ?? [])
      : [];

  const conceptPanelClarifying =
    conceptQuestionsActive && conceptQuestionClarifying;

  const conceptPanelAwaitingAnswer =
    conceptQuestionsActive &&
    showConceptCheckQuestion &&
    !sessionUi.sessionMeta?.concept_question_followup &&
    !conceptPanelClarifying &&
    !sessionUi.activeQuiz &&
    !isTeachbackMode &&
    !loading &&
    !chatLocked;

  const conceptPanelMcqEnabled =
    conceptPanelAwaitingAnswer &&
    conceptQuestionTypeEffective === "mcq" &&
    conceptQuestionOptionsForUi.length >= 2;

  const conceptPanelTextInputEnabled =
    conceptPanelClarifying ||
    (conceptPanelAwaitingAnswer && conceptQuestionTypeEffective !== "mcq");

  const conceptPanelShowsAnswerUi =
    conceptPanelMcqEnabled || conceptPanelTextInputEnabled;

  const conceptPanelInputDisabled =
    chatLocked || loading || flowCheckpoint.ui.isActive;

  const conceptPanelButtonsDisabled =
    chatLocked || loading || actionButtonsDisabled || flowCheckpoint.ui.isActive;

  const conceptInputDisabledHint = (() => {
    if (chatLocked) return null;
    if (loading) return "Thinking…";
    if (conceptPanelClarifying) return null;
    if (sessionUi.sessionMeta?.concept_question_followup) {
      return "Use the buttons below";
    }
    if (!conceptPanelAwaitingAnswer && !conceptPanelClarifying) {
      return "Follow the lesson steps to continue.";
    }
    return null;
  })();

  const openClusterPanel =
    (clusterQuizActive && showMicroQuestion) ||
    (clusterQuizActive && sessionUi.buttons.length > 0) ||
    clusterQuestionClarifying;

  useEffect(() => {
    if (!clusterQuizActive) return;
    if (explanationStreaming) {
      setClusterPanelExpanded(false);
      return;
    }
    if (openClusterPanel) {
      setClusterPanelExpanded(true);
    }
  }, [clusterQuizActive, explanationStreaming, openClusterPanel]);

  const clusterQuestionTypeEffective = resolveClusterQuizType(
    sessionUi.sessionMeta,
    microPromptText
  );
  const clusterQuestionOptionsForUi =
    clusterQuestionTypeEffective === "mcq"
      ? (sessionUi.sessionMeta?.cluster_quiz_options ?? [])
      : [];

  const clusterPanelClarifying =
    clusterQuizActive && clusterQuestionClarifying;

  const clusterPanelAwaitingAnswer =
    clusterQuizActive &&
    showMicroQuestion &&
    !sessionUi.sessionMeta?.cluster_quiz_followup &&
    !clusterPanelClarifying &&
    !sessionUi.activeQuiz &&
    !isTeachbackMode &&
    !loading &&
    !chatLocked;

  const clusterPanelMcqEnabled =
    clusterPanelAwaitingAnswer &&
    clusterQuestionTypeEffective === "mcq" &&
    clusterQuestionOptionsForUi.length >= 2;

  const clusterPanelTextInputEnabled =
    clusterPanelClarifying ||
    (clusterPanelAwaitingAnswer && clusterQuestionTypeEffective !== "mcq");

  const clusterPanelShowsAnswerUi =
    clusterPanelMcqEnabled || clusterPanelTextInputEnabled;

  const clusterPanelInputDisabled =
    chatLocked || loading || flowCheckpoint.ui.isActive;

  const clusterPanelButtonsDisabled =
    chatLocked || loading || actionButtonsDisabled || flowCheckpoint.ui.isActive;

  const clusterInputDisabledHint = (() => {
    if (chatLocked) return null;
    if (loading) return "Thinking…";
    if (clusterPanelClarifying) return null;
    if (sessionUi.sessionMeta?.cluster_quiz_followup) {
      return "Use the buttons below";
    }
    if (!clusterPanelAwaitingAnswer && !clusterPanelClarifying) {
      return "Follow the lesson steps to continue.";
    }
    return null;
  })();

  const teachbackPanelAwaitingAnswer =
    clusterTeachbackActive &&
    sessionUi.sessionMeta?.cluster_teachback_phase !== "reteach_pending" &&
    !explanationStreaming &&
    !loading &&
    !chatLocked &&
    !sessionUi.activeQuiz;

  const teachbackPanelInputDisabled =
    chatLocked || loading || flowCheckpoint.ui.isActive;

  const teachbackInputDisabledHint = (() => {
    if (chatLocked) return null;
    if (loading) return "Thinking…";
    if (explanationStreaming) return "Listen to the feedback…";
    if (!clusterTeachbackActive) return "Follow the lesson steps to continue.";
    return null;
  })();

  // Track the board-item ID for which we already sent the quiz trigger so that
  // the callback never fires twice for the same item (guards against any edge-case
  // where onComplete fires more than once).
  const quizTriggeredForRef = useRef<string | null>(null);

  /**
   * VTSE stage-done guard — confirms only after backend accepts (or idempotent
   * already-completed). Clears on noop/failure so Concept Check can still arm.
   */
  const vtseStageDoneGuardRef = useRef<{
    id: string;
    inFlight: boolean;
    confirmed: boolean;
  } | null>(null);

  /**
   * Visual Teaching advancement guard — keyed by session + scene + beat.
   * Prevents concurrent duplicate next/done for the same beat, but clears on
   * failure/noop so at-least-once retry remains possible. Independent of
   * quizTriggeredForRef and of background sentence-checkpoint loading.
   */
  const vtAdvanceGuardRef = useRef<{
    key: string;
    inFlight: boolean;
    confirmed: boolean;
  } | null>(null);

  /** Coalesce sync VT sentence checkpoints (TTS-off storms) per scene:beat. */
  const vtSentenceCoalesceRef = useRef<
    Map<string, { scene: number; beat: number; sentence: number }>
  >(new Map());

  const logVtTransition = useCallback(
    (event: string, extra?: Record<string, unknown>) => {
      if (process.env.NODE_ENV !== "development") return;
      // eslint-disable-next-line no-console
      console.info("[VT]", event, {
        sessionId,
        flowState: sessionUi.flowState,
        ...extra,
      });
    },
    [sessionId, sessionUi.flowState]
  );

  // When a new VT beat arrives, advancement identity resets naturally.
  useEffect(() => {
    if (sessionUi.flowState !== "concept_visual_teaching") {
      vtAdvanceGuardRef.current = null;
      return;
    }
    const lastAssistant = [...messages]
      .reverse()
      .find((m) => m.role === "assistant" && m.kind === "text");
    const lastVisual =
      lastAssistant && "visual" in lastAssistant
        ? lastAssistant.visual
        : null;
    const vt =
      lastVisual && typeof lastVisual === "object"
        ? (lastVisual as { scene_index?: number; beat_index?: number })
        : null;
    if (!vt || !sessionId) return;
    const key = `${sessionId}:${Math.floor(Number(vt.scene_index) || 0)}:${Math.floor(Number(vt.beat_index) || 0)}`;
    const g = vtAdvanceGuardRef.current;
    if (g && g.key !== key) {
      logVtTransition("advance_guard_reset", {
        prevKey: g.key,
        key,
        scene_index: vt.scene_index,
        beat_index: vt.beat_index,
      });
      vtAdvanceGuardRef.current = null;
    }
  }, [messages, sessionId, sessionUi.flowState, logVtTransition]);

  // Called by AIWhiteboard / timeline when the last instructional item finishes.
  // Captures latestBoardItemId via closure so we always mark the correct item.
  // After marking completion, auto-request the quiz so the two steps are always
  // cleanly separated: explanation streams first, quiz arrives only after done.
  const handlePlaybackBeatCommitted = useCallback(
    (beatIndex: number) => {
      if (!token || !sessionId) return;
      if (lastSavedBeatRef.current === beatIndex) return;
      lastSavedBeatRef.current = beatIndex;
      void saveBoardCheckpoint(token, sessionId, beatIndex, {
        timelineId: vtseTimelineIdRef.current,
      }).catch(() => {
        /* ignore */
      });
    },
    [token, sessionId]
  );

  useEffect(() => {
    if (!token || !sessionId) return;
    const flush = () => {
      const beat = lastSavedBeatRef.current;
      if (beat == null) return;
      void saveBoardCheckpoint(token, sessionId, beat, {
        keepalive: true,
        timelineId: vtseTimelineIdRef.current,
      }).catch(
        () => {
          /* ignore */
        }
      );
    };
    const onHide = () => flush();
    window.addEventListener("pagehide", onHide);
    const onVis = () => {
      if (document.visibilityState === "hidden") flush();
    };
    document.addEventListener("visibilitychange", onVis);
    return () => {
      window.removeEventListener("pagehide", onHide);
      document.removeEventListener("visibilitychange", onVis);
    };
  }, [token, sessionId]);

  const handleExplanationComplete = useCallback((completedItemId?: string | null) => {
    if (restoreAutomationGatedRef.current || resumeInteractionLockedRef.current) {
      return;
    }
    const completedId =
      completedItemId != null && completedItemId !== ""
        ? completedItemId
        : latestBoardItemId;
    if (lastSavedBeatRef.current != null && token && sessionId) {
      void saveBoardCheckpoint(token, sessionId, lastSavedBeatRef.current, {
        timelineId: vtseTimelineIdRef.current,
      }).catch(
        () => {
          /* ignore */
        }
      );
    }
    setCompletedBoardItemId(completedId);
    if (
      sessionUi.sessionMeta?.micro_quiz_hold === 1 ||
      sessionUi.sessionMeta?.concept_questions_active === true
    ) {
      void refreshSessionMeta();
    }
    if (!sessionId || endResult || completedId === null) return;

    // ── Visual Teaching: independent of global loading + quizTriggered ─────
    // Sentence checkpoints use background send and must never suppress advance.
    if (sessionUi.flowState === "concept_visual_teaching") {
      const lastAssistant = [...messages]
        .reverse()
        .find((m) => m.role === "assistant" && m.kind === "text");
      const lastVisual =
        lastAssistant && "visual" in lastAssistant
          ? lastAssistant.visual
          : null;
      const vt =
        lastVisual && typeof lastVisual === "object"
          ? (lastVisual as {
              type?: string;
              scene_index?: number;
              beat_index?: number;
              scene_count?: number;
              beat_count?: number;
              beat_id?: string;
            })
          : null;
      const scene = Math.floor(Number(vt?.scene_index) || 0);
      const beat = Math.floor(Number(vt?.beat_index) || 0);
      const key = `${sessionId}:${scene}:${beat}`;
      const guard = vtAdvanceGuardRef.current;
      if (guard?.key === key && (guard.inFlight || guard.confirmed)) {
        logVtTransition("advance_duplicate_suppressed", {
          key,
          scene_index: scene,
          beat_index: beat,
          beat_id: vt?.beat_id,
          inFlight: guard.inFlight,
          confirmed: guard.confirmed,
        });
        return;
      }
      const isLast =
        vt?.type === "concept_visual_teaching" &&
        scene >= Math.max(1, Math.floor(Number(vt.scene_count) || 1)) - 1 &&
        beat >= Math.max(1, Math.floor(Number(vt.beat_count) || 1)) - 1;
      const action = isLast
        ? `__action:visual_teaching_done:${scene}:${beat}`
        : `__action:visual_teaching_next:${scene}:${beat}`;
      vtAdvanceGuardRef.current = { key, inFlight: true, confirmed: false };
      logVtTransition("tts_finish_advance", {
        action,
        scene_index: scene,
        beat_index: beat,
        beat_id: vt?.beat_id,
        isLast,
      });
      void (async () => {
        try {
          const result = await sendMessage(sessionId, action, { silent: true });
          const tutor =
            result && typeof result === "object" && "tutor" in result
              ? (result as { tutor?: { type?: string; outcome?: string } }).tutor
              : undefined;
          const tutorType = tutor?.type;
          const outcome =
            tutorType === "visual_teaching_advance_ack"
              ? String(tutor?.outcome || "")
              : "";
          const confirmed =
            (tutorType &&
              tutorType !== "noop" &&
              tutorType !== "visual_teaching_sentence_ack" &&
              tutorType !== "visual_teaching_advance_ack") ||
            outcome === "already_advanced" ||
            outcome === "accepted" ||
            outcome === "completed";
          if (confirmed) {
            vtAdvanceGuardRef.current = {
              key,
              inFlight: false,
              confirmed: true,
            };
            logVtTransition("advance_accepted", {
              action,
              tutorType,
              outcome: outcome || null,
              scene_index: scene,
              beat_index: beat,
            });
            return;
          }
          // stale / noop / unknown: allow retry (backend remains conditional).
          if (vtAdvanceGuardRef.current?.key === key) {
            vtAdvanceGuardRef.current = null;
          }
          logVtTransition("advance_noop_retryable", {
            action,
            tutorType: tutorType ?? null,
            outcome: outcome || null,
            scene_index: scene,
            beat_index: beat,
          });
        } catch (err) {
          if (vtAdvanceGuardRef.current?.key === key) {
            vtAdvanceGuardRef.current = null;
          }
          logVtTransition("advance_failed_retryable", {
            action,
            scene_index: scene,
            beat_index: beat,
            error: err instanceof Error ? err.message : String(err),
          });
        }
      })();
      return;
    }

    if (loading) return;
    if (quizTriggeredForRef.current === completedId) return;

    const lastAssistantForBoard = [...messages]
      .reverse()
      .find((m) => m.role === "assistant");
    const afterClusterTeachbackPass =
      lastAssistantForBoard?.role === "assistant" &&
      lastAssistantForBoard.kind === "text" &&
      (lastAssistantForBoard as ChatItem & { teachbackPassed?: boolean })
        .teachbackPassed === true;

    // After cluster teachback praise finishes on the board → next concept/cluster.
    if (afterClusterTeachbackPass) {
      quizTriggeredForRef.current = completedId;
      const sessionPlanDone =
        (lastAssistantForBoard as ChatItem & { sessionPlanComplete?: boolean })
          .sessionPlanComplete === true;
      if (!sessionPlanDone && !planAutoTransitionRef.current) {
        void sendMessage(sessionId, "__action:ready", { silent: true });
      }
      return;
    }

    // ── VTSE opening in flight: wait for the single timeline, never quiz ────
    if (sessionUi.flowState === "concept_vtse_opening") {
      return;
    }

    // ── Zone 0 interactive pauses: do NOT auto-advance after TTS ───────────
    // Anchor / prereq / curiosity wait for student chat (or Ready). Falling
    // through would trigger quiz advance incorrectly.
    if (
      sessionUi.flowState === "zone0_anchor" ||
      sessionUi.flowState === "zone0_prereq" ||
      sessionUi.flowState === "zone0_curiosity"
    ) {
      return;
    }

    // Zone 0 mirror (notes bridge): auto-advance to Q2 after TTS, like pedagogy feedback.
    if (sessionUi.flowState === "zone0_mirror") {
      quizTriggeredForRef.current = completedId;
      void sendMessage(sessionId, "__action:zone0_mirror_done", { silent: true });
      return;
    }

    // ── Pedagogy recall / curiosity: student answers in chat (no auto-quiz) ─
    if (
      sessionUi.flowState === "pedagogy_session_recall" ||
      sessionUi.flowState === "pedagogy_cluster_curiosity"
    ) {
      return;
    }

    // ── Post-VTSE stages: complete VTSE only when the VTSE board timeline ends.
    // A mid-VTSE student question → tutor answer is a conversational interrupt.
    // Completing that bubble must NOT send concept_vtse_stage_done (that skipped
    // remaining timeline beats and jumped to Concept Check).
    const awaitVtseDone =
      sessionUi.sessionMeta?.concept_teaching_await_vtse_done === 1 ||
      sessionUi.sessionMeta?.concept_teaching_await_vtse_done === true;
    if (awaitVtseDone) {
      // FlowCheckpoint is a temporary pause — never arm Concept Check from it.
      if (flowCheckpoint.ui.isActive || flowCheckpoint.ui.continuing) {
        return;
      }
      if (
        !shouldCompleteVtseStageOnItem(completedId, messages, true)
      ) {
        // Interrupt answer (or unrelated bubble) finished — keep VTSE pending.
        return;
      }
      if (quizTriggeredForRef.current === completedId) return;
      const stageGuard = vtseStageDoneGuardRef.current;
      if (
        stageGuard?.id === completedId &&
        (stageGuard.inFlight || stageGuard.confirmed)
      ) {
        return;
      }
      vtseStageDoneGuardRef.current = {
        id: completedId,
        inFlight: true,
        confirmed: false,
      };
      void (async () => {
        const tryStageDone = async () => {
          const beat = lastSavedBeatRef.current;
          const action = conceptVtseStageDoneAction({
            messages,
            completedItemId: completedId,
            conceptIndex: sessionUi.sessionMeta?.concept_index,
            conceptId: sessionUi.currentConcept,
          });
          const timelineId = (() => {
            try {
              const raw = action.split("|").slice(1).join("|");
              const parsed = JSON.parse(raw) as { timeline_id?: string };
              return parsed.timeline_id || undefined;
            } catch {
              return undefined;
            }
          })();
          if (beat != null && token) {
            await saveBoardCheckpoint(token, sessionId, beat, {
              timelineId,
            }).catch(() => {
              /* stage_done still reports identity; backend rejects if cursor lags */
            });
          }
          const result = await sendMessage(sessionId, action, { silent: true });
          const tutor = result?.tutor;
          const meta =
            tutor && "meta" in tutor
              ? (tutor as { meta?: typeof sessionUi.sessionMeta }).meta
              : undefined;
          return isConceptVtseStageDoneAccepted(tutor, meta ?? null);
        };
        try {
          let accepted = await tryStageDone();
          // Residual race: one immediate retry while still awaiting (no delay).
          if (!accepted) {
            accepted = await tryStageDone();
          }
          if (accepted) {
            quizTriggeredForRef.current = completedId;
            vtseStageDoneGuardRef.current = {
              id: completedId,
              inFlight: false,
              confirmed: true,
            };
            return;
          }
          if (vtseStageDoneGuardRef.current?.id === completedId) {
            vtseStageDoneGuardRef.current = null;
          }
        } catch {
          if (vtseStageDoneGuardRef.current?.id === completedId) {
            vtseStageDoneGuardRef.current = null;
          }
        }
      })();
      return;
    }

    // ── Pedagogy intro cards: advance after TTS ───────────────────────────
    if (sessionUi.flowState === "pedagogy_session_intro") {
      quizTriggeredForRef.current = completedId;
      void sendMessage(sessionId, "__action:session_intro_done", { silent: true });
      return;
    }
    if (sessionUi.flowState === "pedagogy_cluster_intro") {
      quizTriggeredForRef.current = completedId;
      void sendMessage(sessionId, "__action:cluster_intro_done", { silent: true });
      return;
    }
    if (sessionUi.flowState === "concept_story_hook") {
      // The Story Hook asked a question — wait for the student, never advance.
      if (sessionUi.sessionMeta?.story_hook_awaiting === true) return;
      quizTriggeredForRef.current = completedId;
      void sendMessage(sessionId, "__action:story_hook_done", { silent: true });
      return;
    }
    if (sessionUi.flowState === "pedagogy_session_recall_feedback") {
      quizTriggeredForRef.current = completedId;
      void sendMessage(sessionId, "__action:session_recall_done", { silent: true });
      return;
    }
    if (sessionUi.flowState === "pedagogy_cluster_curiosity_feedback") {
      quizTriggeredForRef.current = completedId;
      void sendMessage(sessionId, "__action:cluster_curiosity_done", { silent: true });
      return;
    }

    // ── Zone 1–4: standard quiz trigger ───────────────────────────────────
    // Do NOT auto-send __action:quiz while micro-teaching is waiting for typed
    // input (server sets meta.micro_quiz_hold=1). That caused a Pause-message loop.
    if (!isTeachbackMode && !sessionUi.activeQuiz) {
      if (flowCheckpoint.ui.isActive) {
        // Checkpoint owns the board — do not consume completion guard.
        return;
      }
      if (sessionUi.sessionMeta?.micro_quiz_hold === 1) {
        // Mark this board item handled so onComplete doesn't re-fire quiz
        // for the same content while micro input is expected.
        quizTriggeredForRef.current = completedId;
        logHandleExplanationComplete("micro_quiz_hold");
        return;
      }
      if (sessionUi.sessionMeta?.student_questions_active === true) {
        // Student-question loop is active: never auto-quiz from this board item.
        quizTriggeredForRef.current = completedId;
        return;
      }
      if (sessionUi.sessionMeta?.concept_questions_active === true) {
        quizTriggeredForRef.current = completedId;
        logHandleExplanationComplete("concept_questions_hold");
        return;
      }
      if (sessionUi.sessionMeta?.concept_notes_active === true) {
        quizTriggeredForRef.current = completedId;
        logHandleExplanationComplete("concept_notes_hold");
        return;
      }
      if (sessionUi.sessionMeta?.cluster_quiz_active === true) {
        quizTriggeredForRef.current = completedId;
        return;
      }
      if (sessionUi.sessionMeta?.cluster_teachback_active === true) {
        quizTriggeredForRef.current = completedId;
        return;
      }
      if (sessionUi.sessionMeta?.cluster_quiz_ready === false) {
        // Strict cluster boundary: never trigger quiz before cluster end.
        quizTriggeredForRef.current = completedId;
        return;
      }
      quizTriggeredForRef.current = completedId;
      void sendMessage(sessionId, "__action:quiz", { silent: true });
    }
  }, [
    latestBoardItemId,
    sessionId,
    endResult,
    loading,
    isTeachbackMode,
    sendMessage,
    sessionUi.activeQuiz,
    sessionUi.flowState,
    sessionUi.sessionMeta?.micro_quiz_hold,
    sessionUi.sessionMeta?.student_questions_active,
    sessionUi.sessionMeta?.cluster_quiz_ready,
    sessionUi.sessionMeta?.concept_notes_active,
    flowCheckpoint.ui.isActive,
    flowCheckpoint.ui.continuing,
    refreshSessionMeta,
    sessionUi.sessionMeta?.concept_questions_active,
    sessionUi.sessionMeta?.concept_teaching_await_vtse_done,
    sessionUi.sessionMeta?.story_hook_awaiting,
    sessionUi.sessionMeta?.cluster_quiz_active,
    sessionUi.sessionMeta?.cluster_teachback_active,
    messages,
    token,
    logVtTransition,
  ]);

  // Stage-anchored scroll entries: each conversation episode stays where it occurred.
  const whiteboardTimeline = useMemo(() => {
    const mapOne = (
      m: Extract<ChatItem, { role: "assistant"; kind: "text" }>
    ): BoardItem => {
      const raw = m.content;
      const visual = "visual" in m ? (m.visual ?? null) : null;
      const itv3 =
        "instruction_timeline_v3" in m
          ? // eslint-disable-next-line @typescript-eslint/no-explicit-any
            ((m.instruction_timeline_v3 as any) ?? null)
          : null;
      const ps = "planner_source" in m ? (m.planner_source ?? null) : null;
      const tmeta =
        "timeline_metadata" in m
          ? (m.timeline_metadata as Record<string, unknown> | null)
          : null;
      const content =
        typeof raw === "string"
          ? raw
          : raw != null &&
              typeof raw === "object" &&
              "text" in raw &&
              typeof (raw as { text?: string }).text === "string"
            ? (raw as { text: string }).text
            : "";
      return {
        id: m.id,
        type: "text",
        content,
        visual,
        ...(itv3 != null ? { instruction_timeline_v3: itv3 } : {}),
        ...(ps != null ? { planner_source: ps } : {}),
        ...(tmeta != null ? { timeline_metadata: tmeta } : {}),
        ...("writingMode" in m && m.writingMode != null
          ? { writingMode: m.writingMode }
          : {}),
        ...("displayText" in m && m.displayText !== undefined
          ? { displayText: m.displayText }
          : {}),
        ...("boardWrites" in m &&
        Array.isArray(m.boardWrites) &&
        m.boardWrites.length
          ? { boardWrites: m.boardWrites }
          : {}),
      };
    };

    let conversationThinkingActive = false;
    for (const seg of learnTimeline) {
      if (
        conversationEpisodeShowsThinking(seg, messages, loading, loadingKind)
      ) {
        conversationThinkingActive = true;
        break;
      }
    }

    const entries = learnTimeline.map((seg, i) => {
      if (seg.kind === "board") {
        return {
          kind: "board" as const,
          items: seg.messages.map(mapOne),
        };
      }
      const showThinking = conversationEpisodeShowsThinking(
        seg,
        messages,
        loading,
        loadingKind
      );
      const streamId =
        explanationStreaming &&
        latestStreamIsInlineBubble &&
        latestBoardItemId &&
        seg.messages.some((m) => m.id === latestBoardItemId)
          ? latestBoardItemId
          : null;
      return {
        kind: "conversation" as const,
        key: `convo-${seg.messages[0]?.id ?? i}${showThinking ? ":thinking" : ""}`,
        content: (
          <InlineBoardChat
            messages={seg.messages}
            loading={showThinking}
            activeStreamMessageId={streamId}
            onStreamComplete={
              streamId
                ? () => handleExplanationComplete(streamId)
                : undefined
            }
          />
        ),
      };
    });

    const showStageThinking = shouldShowStageTransitionThinking({
      loadingKind,
      conversationThinkingActive,
    });
    if (showStageThinking) {
      entries.push({
        kind: "conversation" as const,
        key: "stage-transition-thinking",
        content: (
          <div
            className="w-full"
            data-testid="stage-transition-thinking-slot"
            aria-label="Preparing next stage"
          >
            <TutorThinkingBubble testId="stage-transition-thinking" />
          </div>
        ),
      });
    }
    return entries;
  }, [
    learnTimeline,
    messages,
    explanationStreaming,
    latestStreamIsInlineBubble,
    latestBoardItemId,
    loading,
    loadingKind,
    handleExplanationComplete,
  ]);

  const boardScrollFollowPanelKey = useMemo(() => {
    if (conceptPanelExpanded && conceptQuestionsActive) return "concept-check";
    if (clusterPanelExpanded && clusterQuizActive) return "cluster-quiz";
    if (teachbackPanelExpanded && clusterTeachbackActive) {
      return "cluster-teachback";
    }
    if (notesPanelExpanded && conceptNotesActive) return "concept-notes";
    return null;
  }, [
    conceptPanelExpanded,
    conceptQuestionsActive,
    clusterPanelExpanded,
    clusterQuizActive,
    teachbackPanelExpanded,
    clusterTeachbackActive,
    notesPanelExpanded,
    conceptNotesActive,
  ]);

  useEffect(() => {
    if (!showMicroQuestion) return;
    logMicroInteraction({
      question_visible: true,
      question_length: microPromptText.length,
      flow_state: sessionUi.flowState,
      micro_quiz_hold: sessionUi.sessionMeta?.micro_quiz_hold,
    });
  }, [
    showMicroQuestion,
    microPromptText,
    sessionUi.flowState,
    sessionUi.sessionMeta?.micro_quiz_hold,
  ]);

  // After a correct cluster-quiz answer: show praise on board, then load next Q.
  const clusterQAdvancedRef = useRef<string | null>(null);
  useEffect(() => {
    if (restoreAutomationGatedRef.current || resumeInteractionLockedRef.current) {
      return;
    }
    if (!sessionId || endResult || loading) return;
    if (sessionUi.sessionMeta?.cluster_quiz_active !== true) return;
    if (sessionUi.sessionMeta?.cluster_quiz_pending_advance !== true) return;
    const lastAssistant = [...messages]
      .reverse()
      .find((m) => m.role === "assistant");
    if (!lastAssistant) return;
    if (clusterQAdvancedRef.current === lastAssistant.id) return;
    clusterQAdvancedRef.current = lastAssistant.id;
    const timer = setTimeout(() => {
      void sendMessage(sessionId, "__action:cluster_q_auto_advance", {
        silent: true,
      });
    }, 1800);
    return () => clearTimeout(timer);
  }, [
    messages,
    sessionId,
    endResult,
    loading,
    sendMessage,
    sessionUi.sessionMeta?.cluster_quiz_active,
    sessionUi.sessionMeta?.cluster_quiz_pending_advance,
  ]);

  // After a correct concept-question answer: show praise on board, then load next Q.
  const conceptQAdvancedRef = useRef<string | null>(null);
  useEffect(() => {
    if (restoreAutomationGatedRef.current || resumeInteractionLockedRef.current) {
      return;
    }
    if (!sessionId || endResult || loading) return;
    if (sessionUi.sessionMeta?.concept_questions_active !== true) return;
    if (sessionUi.sessionMeta?.concept_question_pending_advance !== true) return;
    const lastAssistant = [...messages]
      .reverse()
      .find((m) => m.role === "assistant");
    if (!lastAssistant) return;
    if (conceptQAdvancedRef.current === lastAssistant.id) return;
    conceptQAdvancedRef.current = lastAssistant.id;
    const timer = setTimeout(() => {
      void sendMessage(sessionId, "__action:concept_q_auto_advance", { silent: true });
    }, 1800);
    return () => clearTimeout(timer);
  }, [
    messages,
    sessionId,
    endResult,
    loading,
    sendMessage,
    sessionUi.sessionMeta?.concept_questions_active,
    sessionUi.sessionMeta?.concept_question_pending_advance,
  ]);

  // Auto-advance to the next concept after:
  //   • feedback with correct=true (legacy teachback / clarity gate)
  //   • teachback_exit (3 failed attempts, concept skipped)
  //   • teachback_passed (cluster teachback cleared — next concept/cluster)
  // All set flow_state="idle" on the backend so the next __action:ready
  // immediately explains the next concept without user input.
  const autoAdvancedMsgId = useRef<string | null>(null);
  const conceptQWasActiveRef = useRef(false);
  useEffect(() => {
    if (restoreAutomationGatedRef.current || resumeInteractionLockedRef.current) {
      return;
    }
    if (!sessionId || endResult || loading) return;
    if (planAutoTransitionRef.current) return;
    if (
      sessionUi.flowState === "zone_2_entry" ||
      sessionUi.flowState === "zone_3_entry" ||
      sessionUi.flowState === "zone_4_entry" ||
      sessionUi.flowState === "pedagogy_session_intro" ||
      sessionUi.flowState === "pedagogy_cluster_intro" ||
      sessionUi.flowState === "concept_story_hook" ||
      sessionUi.flowState === "concept_visual_teaching" ||
      sessionUi.flowState === "pedagogy_session_recall" ||
      sessionUi.flowState === "pedagogy_session_recall_feedback" ||
      sessionUi.flowState === "pedagogy_cluster_curiosity" ||
      sessionUi.flowState === "pedagogy_cluster_curiosity_feedback"
    ) {
      return;
    }
    if (sessionUi.sessionMeta?.concept_notes_active === true) return;
    if (notesReadyHandledRef.current) {
      notesReadyHandledRef.current = false;
      return;
    }
    const lastAssistant = [...messages]
      .reverse()
      .find((m) => m.role === "assistant");
    if (!lastAssistant) return;
    const conceptQActive =
      sessionUi.sessionMeta?.concept_questions_active === true;
    const justFinishedConceptQ =
      conceptQWasActiveRef.current && !conceptQActive;
    conceptQWasActiveRef.current = conceptQActive;
    const isTeachbackPassMsg =
      lastAssistant.kind === "text" &&
      (lastAssistant as ChatItem & { teachbackPassed?: boolean }).teachbackPassed ===
        true;
    const sessionPlanDone =
      (lastAssistant as ChatItem & { sessionPlanComplete?: boolean })
        .sessionPlanComplete === true;
    const gatePending =
      sessionUi.sessionMeta?.zone_transition_gate_pending === true ||
      (lastAssistant as ChatItem & { zoneTransitionGatePending?: boolean })
        .zoneTransitionGatePending === true;
    const shouldAdvance =
      !sessionPlanDone &&
      ((lastAssistant.kind === "feedback" && lastAssistant.correct === true) ||
        lastAssistant.kind === "teachback_exit" ||
        isTeachbackPassMsg) &&
      !conceptQActive;
    if (!shouldAdvance) return;
    const advanceKey = gatePending
      ? `gate-pending:${lastAssistant.id}`
      : isTeachbackPassMsg
        ? `tb-pass:${lastAssistant.id}`
        : lastAssistant.id;
    if (autoAdvancedMsgId.current === advanceKey) return;
    const delay =
      lastAssistant.kind === "teachback_exit"
        ? 2200
        : isTeachbackPassMsg
          ? gatePending
            ? 1800
            : 1200
          : justFinishedConceptQ
            ? 900
            : 1400;
    const timer = setTimeout(() => {
      autoAdvancedMsgId.current = advanceKey;
      if (gatePending) {
        void sendMessage(sessionId, "__action:begin_zone_transition_gate", {
          silent: true,
        });
        return;
      }
      void sendMessage(sessionId, "__action:ready", { silent: true });
    }, delay);
    return () => clearTimeout(timer);
  }, [
    messages,
    sessionId,
    endResult,
    loading,
    sendMessage,
    sessionUi.sessionMeta?.concept_questions_active,
    sessionUi.sessionMeta?.concept_notes_active,
    sessionUi.sessionMeta?.zone_transition_gate_pending,
  ]);

  return (
    <div className="flex h-full min-h-0 flex-1 flex-col overflow-hidden">
      <SessionCompleteModal
        open={Boolean(endResult)}
        result={endResult}
        onClose={closeCompleteModal}
      />

      {showCatalogPlanPicker && catalogPlans.length > 0 ? (
        <div className="flex flex-1 items-center justify-center p-4">
          <Card className="w-full max-w-lg">
            <CardHeader>
              <CardTitle>Choose a session</CardTitle>
              <CardDescription>
                This topic is split into planned sessions. Pick where to start or continue.
              </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-2">
              {catalogPlans.map((plan) => (
                <Button
                  key={plan.id}
                  type="button"
                  variant="outline"
                  className="h-auto flex-col items-start gap-1 px-4 py-3 text-left"
                  disabled={resumeBusy}
                  onClick={() => {
                    const q = new URLSearchParams(searchParams.toString());
                    q.set("catalogPlanId", plan.id);
                    q.delete("sessionId");
                    router.replace(`/learn/${topicId}?${q.toString()}`);
                    setShowCatalogPlanPicker(false);
                    setResolving(true);
                  }}
                >
                  <span className="font-medium">
                    Session {plan.sequence_number}: {plan.title}
                  </span>
                  {plan.description ? (
                    <span className="text-xs font-normal text-slate-500">{plan.description}</span>
                  ) : null}
                </Button>
              ))}
            </CardContent>
          </Card>
        </div>
      ) : null}

      {sessionError ? (
        <p className="shrink-0 px-4 py-2 text-sm text-red-600 dark:text-red-400">
          {sessionError}
        </p>
      ) : null}
      {error ? (
        <p className="shrink-0 px-4 py-2 text-sm text-red-600 dark:text-red-400">
          {error}
        </p>
      ) : null}

      {showResumeCard && resumePrompt ? (
        <div className="flex flex-1 items-center justify-center p-4">
          <Card className="w-full max-w-md">
            <CardHeader>
              <CardTitle>Continue where you left off?</CardTitle>
              <CardDescription>
                You have an ongoing session. What would you like to do?
              </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-2 sm:flex-row">
              <Button
                className="flex-1"
                type="button"
                disabled={resumeBusy}
                onClick={() => void handleContinueSession()}
              >
                {resumeBusy ? "Working…" : "Continue learning"}
              </Button>
              <Button
                className="flex-1"
                variant="secondary"
                type="button"
                disabled={resumeBusy}
                onClick={() => void handleRestartTopic()}
              >
                Restart topic
              </Button>
            </CardContent>
          </Card>
        </div>
      ) : resolving || !sessionId ? (
        <div className="flex flex-1 items-center justify-center">
          <p className="text-sm text-slate-500">
            {resolving ? "Preparing your session…" : "No session."}
          </p>
        </div>
      ) : (
        <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
          <div className="relative flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden p-2 md:p-3">
            <div className="relative min-h-0 flex-1 overflow-hidden">
              <AIWhiteboard
                items={boardItems}
                showVtseVisuals={!clusterTeachbackActive}
                timeline={whiteboardTimeline}
                topicTitle={topicTitle}
                zone={sessionUi.currentZone}
                scrollFollowPanelKey={boardScrollFollowPanelKey}
                onLastItemComplete={
                  latestStreamIsOnBoard || awaitVtseBoardCompletion
                    ? () =>
                        handleExplanationComplete(
                          lastDurableBoardItemId ?? latestBoardItemId
                        )
                    : undefined
                }
                flowCheckpointGate={flowCheckpoint.gate}
                flowCheckpointUi={flowCheckpoint.ui}
                staticRestoreByItemId={staticRestoreByItemId}
                onPlaybackBeatCommitted={handlePlaybackBeatCommitted}
                onVisualTeachingSentenceProgress={(progress) => {
                  if (!sessionId) return;
                  // Coalesce rapid synchronous progress: one HTTP checkpoint per
                  // scene:beat microtask with the highest sentence index.
                  const coalesceKey = `${progress.sceneIndex}:${progress.beatIndex}`;
                  const bag = vtSentenceCoalesceRef.current;
                  const prev = bag.get(coalesceKey);
                  if (prev && progress.sentenceIndex <= prev.sentence) return;
                  bag.set(coalesceKey, {
                    scene: progress.sceneIndex,
                    beat: progress.beatIndex,
                    sentence: progress.sentenceIndex,
                  });
                  queueMicrotask(() => {
                    const latest = bag.get(coalesceKey);
                    if (!latest) return;
                    bag.delete(coalesceKey);
                    void sendMessage(
                      sessionId,
                      `__action:visual_teaching_sentence:${latest.scene}:${latest.beat}:${latest.sentence}`,
                      { silent: true, background: true }
                    );
                  });
                }}
                boardFooter={
                  showBoardQuizBox ||
                  showBoardActionButtons ||
                  showBoardTeachbackInput ||
                  showBoardComposer ? (
                    <>
                      {showBoardQuizBox && sessionUi.activeQuiz ? (
                        <QuizBox
                          intro={sessionUi.activeQuiz.intro}
                          question={sessionUi.activeQuiz.question}
                          disabled={loading || chatLocked}
                          currentZone={sessionUi.currentZone}
                          onSubmit={onSend}
                        />
                      ) : null}
                      {showBoardActionButtons ? (
                        <ActionButtons
                          compact
                          buttons={sessionUi.buttons}
                          disabled={actionButtonsDisabled || chatLocked}
                          onAction={(id) => onSend(`__action:${id}`)}
                        />
                      ) : null}
                      {showBoardTeachbackInput ? (
                        <TeachbackInput
                          onSend={onSend}
                          disabled={inputDisabled}
                        />
                      ) : null}
                      {showBoardComposer ? (
                        <InputBox
                          compact
                          onSend={onSend}
                          disabled={inputDisabled}
                          disabledHint={inputDisabledHint}
                          placeholder={
                            sessionUi.flowState === "waiting_for_question"
                              ? "Type your question…"
                              : "Message your tutor…"
                          }
                        />
                      ) : null}
                    </>
                  ) : null
                }
              />
              <StudentScratchpadPanel
                expanded={scratchpadExpanded}
                onExpandedChange={setScratchpadExpanded}
                value={studentScratchpadNotes}
                onChange={setStudentScratchpadNotes}
                onSave={handleScratchpadSave}
                hasContent={studentScratchpadNotes.trim().length > 0}
                saveStatus={scratchpadSaveStatus}
                iconSlot={0}
              />
              <ConceptQuestionPanel
                expanded={conceptPanelExpanded}
                onExpandedChange={setConceptPanelExpanded}
                thread={displayConceptThread}
                questionIndex={conceptQuestionIndex}
                active={conceptQuestionsActive}
                awaitingAnswer={conceptPanelAwaitingAnswer || conceptPanelClarifying}
                inputEnabled={conceptPanelShowsAnswerUi}
                inputDisabled={conceptPanelInputDisabled}
                buttonsDisabled={conceptPanelButtonsDisabled}
                inputPlaceholder="Type or speak your answer…"
                inputDisabledHint={conceptInputDisabledHint}
                buttons={sessionUi.buttons}
                onSend={onSend}
                onAction={(id) => onSend(`__action:${id}`)}
                whiteboardStreaming={explanationStreaming}
                iconSlot={1}
                questionType={conceptQuestionTypeEffective}
                questionOptions={conceptQuestionOptionsForUi}
                clarifying={conceptPanelClarifying}
              />
              <ClusterQuizPanel
                expanded={clusterPanelExpanded}
                onExpandedChange={setClusterPanelExpanded}
                thread={displayClusterThread}
                questionIndex={clusterQuestionIndex}
                active={clusterQuizActive}
                awaitingAnswer={showMicroQuestion || clusterPanelClarifying}
                inputEnabled={clusterPanelShowsAnswerUi}
                inputDisabled={clusterPanelInputDisabled}
                buttonsDisabled={clusterPanelButtonsDisabled}
                inputPlaceholder="Type or speak your answer…"
                inputDisabledHint={clusterInputDisabledHint}
                buttons={sessionUi.buttons}
                onSend={onSend}
                onAction={(id) => onSend(`__action:${id}`)}
                whiteboardStreaming={explanationStreaming}
                iconSlot={2}
                questionType={clusterQuestionTypeEffective}
                questionOptions={clusterQuestionOptionsForUi}
                clarifying={clusterPanelClarifying}
              />
              <PostConceptNotesPanel
                expanded={notesPanelExpanded}
                onExpandedChange={handleNotesExpandedChange}
                sections={displayNotesSections}
                active={conceptNotesActive}
                iconSlot={3}
                onMarkAsRead={
                  conceptNotesActive ? () => void handleNotesMarkAsRead() : undefined
                }
                markAsReadDisabled={loading || notesContinueBusy}
              />
              <ClusterTeachbackPanel
                expanded={teachbackPanelExpanded}
                onExpandedChange={setTeachbackPanelExpanded}
                thread={displayTeachbackThread}
                question={clusterTeachbackQuestion}
                active={clusterTeachbackActive}
                inputEnabled={teachbackPanelAwaitingAnswer}
                inputDisabled={teachbackPanelInputDisabled}
                inputPlaceholder="Explain everything in your own words…"
                inputDisabledHint={teachbackInputDisabledHint}
                onSend={onSend}
                whiteboardStreaming={explanationStreaming}
                iconSlot={4}
              />
            </div>

            {recommendedTopics && recommendedTopics.length > 0 ? (
              <div className="shrink-0 border-t border-slate-200/80 px-3 py-3 dark:border-slate-800">
                <div className="mx-auto max-w-3xl">
                  <RecommendedTopics
                    topics={recommendedTopics}
                    learnUrlSuffix={buildLearnQuery(null)}
                  />
                </div>
              </div>
            ) : null}
          </div>
        </div>
      )}
    </div>
  );
}

export default function LearnPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-[50vh] items-center justify-center text-sm text-slate-500">
          Loading…
        </div>
      }
    >
      <LearnInner />
    </Suspense>
  );
}
