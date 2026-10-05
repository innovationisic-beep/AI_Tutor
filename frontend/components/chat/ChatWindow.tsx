"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { MessageBubble } from "./MessageBubble";
import { FeedbackCard } from "./FeedbackCard";
import { TypingIndicator } from "./TypingIndicator";
import {
  RecommendedTopics,
  RootTopicStudyFirstCard,
} from "@/components/learning/RecommendedTopics";
import type { ChatItem } from "@/hooks/useChat";
import type { RecommendedTopicPayload } from "@/lib/types";
import { cn } from "@/lib/utils";
import { CHAT_META_TEXT_CLASS, CHAT_TEXT_CLASS } from "@/lib/teachingTypography";

const NEAR_BOTTOM_PX = 140;

function assistantHasChatChrome(m: ChatItem): boolean {
  if (m.role !== "assistant") return false;
  // kind === "text" messages are rendered on the whiteboard, not in chat.
  // Counting them as "chrome" would incorrectly suppress the chat empty-state
  // hint when no interactive messages (quiz, feedback, teachback) have arrived yet.
  if (m.kind === "text") return false;
  return true;
}

type Props = {
  messages: ChatItem[];
  loading: boolean;
  locked?: boolean;
  /** Prefer Start Learning hint when chat is still empty (teacher idle). */
  showStartLearningEmptyHint?: boolean;
  /** Shown after the last message when the session completes with suggestions. */
  recommendedTopics?: RecommendedTopicPayload[] | null;
  /** Appended to `/learn/:id` when starting a recommended topic (e.g. `?subjectId=`). */
  learnUrlSuffix?: string;
  /**
   * When true, fill parent flex height instead of a fixed viewport-based height
   * (dual-panel learn layout).
   */
  embedded?: boolean;
  /**
   * When true, the latest quiz_prompt card is held invisible (not rendered) until
   * the whiteboard finishes streaming the preceding explanation.  Once the parent
   * sets this to false the existing 400 ms reveal animation takes over.
   */
  quizHeld?: boolean;
};

export function ChatWindow({
  messages,
  loading,
  locked,
  showStartLearningEmptyHint,
  recommendedTopics = null,
  learnUrlSuffix = "",
  embedded = false,
  quizHeld = false,
}: Props) {
  const viewportRef = useRef<HTMLDivElement>(null);
  const stickToBottomRef = useRef(true);
  const bottomRef = useRef<HTMLDivElement>(null);

  // ── Quiz reveal delay ────────────────────────────────────────────────────────
  // When a quiz_prompt arrives as the latest message we hold it invisible for
  // 400 ms so there is a perceptible pause between the explanation ending and
  // the question card appearing.  Already-rendered quizzes (from history) are
  // made visible immediately so they do not flicker on load.
  const [visibleQuizIds, setVisibleQuizIds] = useState<Set<string>>(() => {
    // Pre-populate with any quiz IDs already in the initial message list so
    // history renders fully visible without waiting for the timeout.
    const initial = new Set<string>();
    messages.forEach((m) => {
      if (m.role === "assistant" && m.kind === "quiz_prompt") initial.add(m.id);
    });
    return initial;
  });

  useEffect(() => {
    const latestQuiz = [...messages]
      .reverse()
      .find((m) => m.role === "assistant" && m.kind === "quiz_prompt");
    if (!latestQuiz || visibleQuizIds.has(latestQuiz.id)) return;
    // Hold the quiz while the whiteboard is still streaming the explanation.
    // When quizHeld flips to false this effect re-runs and starts the timer.
    if (quizHeld) return;
    const timer = setTimeout(() => {
      setVisibleQuizIds((prev) => new Set([...prev, latestQuiz.id]));
    }, 400);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [messages, quizHeld]);

  const userMessages = useMemo(
    () => messages.filter((m) => m.role === "user"),
    [messages]
  );

  const hasAssistantChrome = useMemo(
    () => messages.some(assistantHasChatChrome),
    [messages]
  );

  /** Plain assistant explanations live on the whiteboard; suppress misleading chat empty state. */
  const hasAssistantTextOnBoard = useMemo(
    () =>
      messages.some(
        (m) =>
          m.role === "assistant" &&
          m.kind === "text" &&
          !("rootTopicId" in m && m.rootTopicId?.trim())
      ),
    [messages]
  );

  function updateStickFlag() {
    const el = viewportRef.current;
    if (!el) return;
    const dist = el.scrollHeight - el.scrollTop - el.clientHeight;
    stickToBottomRef.current = dist < NEAR_BOTTOM_PX;
  }

  useEffect(() => {
    const el = viewportRef.current;
    if (!el) return;
    el.addEventListener("scroll", updateStickFlag, { passive: true });
    return () => el.removeEventListener("scroll", updateStickFlag);
  }, []);

  useEffect(() => {
    if (!stickToBottomRef.current) return;
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading, recommendedTopics]);

  const scrollAreaClass = embedded
    ? "h-full min-h-0 max-h-full overflow-y-auto overflow-x-hidden scroll-smooth rounded-xl border border-slate-300/70 bg-slate-100 shadow-[inset_0_1px_0_rgba(255,255,255,0.6)] dark:border-slate-600 dark:bg-slate-900/95 dark:shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]"
    : "h-[calc(100vh-8rem)] overflow-y-auto overflow-x-hidden scroll-smooth md:h-[calc(100vh-7rem)]";

  const showEmptyHint =
    userMessages.length === 0 &&
    !loading &&
    !hasAssistantChrome &&
    !hasAssistantTextOnBoard &&
    !recommendedTopics?.length;

  return (
    <div ref={viewportRef} className={scrollAreaClass}>
      <div
        className={
          embedded
            ? "mx-auto flex min-h-full max-w-3xl flex-col gap-4 px-4 py-6"
            : "mx-auto flex max-w-3xl flex-col gap-4 px-4 py-6"
        }
      >
        {showEmptyHint && (
          <div
            className={
              embedded
                ? "flex flex-1 flex-col items-center justify-center px-4 py-10 text-center"
                : "flex min-h-[40vh] flex-col items-center justify-center px-4 text-center"
            }
          >
            <p className={`max-w-sm text-slate-600 dark:text-slate-300 ${CHAT_TEXT_CLASS}`}>
              {showStartLearningEmptyHint
                ? "Click “Start Learning” to begin."
                : "Ask a question or say hello to start learning."}
            </p>
          </div>
        )}
        {messages.map((m, index) => {
          if (m.role === "user") {
            return (
              <MessageBubble key={m.id} role="user">
                <p className="whitespace-pre-wrap">{m.content}</p>
              </MessageBubble>
            );
          }
          if (m.kind === "text") {
            const rootId =
              "rootTopicId" in m && m.rootTopicId?.trim()
                ? m.rootTopicId.trim()
                : "";
            if (rootId) {
              return (
                <div key={m.id} className="flex w-full flex-col gap-2">
                  <RootTopicStudyFirstCard
                    topicId={rootId}
                    learnUrlSuffix={learnUrlSuffix}
                  />
                </div>
              );
            }
            // Plain explanation text always lives on the whiteboard — never render
            // it here so there is no duplication between the two panels.
            return null;
          }
          if (m.kind === "quiz_prompt") {
            // While the whiteboard is still streaming the explanation, suppress
            // the quiz card entirely so it cannot appear before streaming ends.
            if (quizHeld && !visibleQuizIds.has(m.id)) return null;

            // ── Transition divider ──────────────────────────────────────────
            // Look backwards for the nearest earlier assistant message.  If it
            // was an explanation (kind === "text"), insert a visual separator
            // so the two steps feel distinct rather than merged.
            const prevAssistant = messages
              .slice(0, index)
              .reverse()
              .find((msg) => msg.role === "assistant");
            const isAfterExplanation = prevAssistant?.kind === "text";

            const isVisible = visibleQuizIds.has(m.id);

            return (
              <div key={m.id} className="flex w-full flex-col gap-3">
                {isAfterExplanation && (
                  <div className="flex items-center gap-3 px-1">
                    <div className="h-px flex-1 bg-slate-200 dark:bg-slate-700" />
                    <span className={`shrink-0 text-slate-500 dark:text-slate-400 ${CHAT_META_TEXT_CLASS}`}>
                      Let&apos;s test your understanding 👇
                    </span>
                    <div className="h-px flex-1 bg-slate-200 dark:bg-slate-700" />
                  </div>
                )}
                <div
                  className={cn(
                    "max-w-[min(100%,42rem)] rounded-2xl border border-amber-200/80 bg-amber-50/60 px-4 py-3.5 text-amber-950 shadow-sm dark:border-amber-900/50 dark:bg-amber-950/25 dark:text-amber-50",
                    CHAT_TEXT_CLASS,
                    "transition-all duration-300",
                    isVisible ? "translate-y-0 opacity-100" : "translate-y-2 opacity-0"
                  )}
                >
                  <p className={`uppercase tracking-wide text-amber-800/90 dark:text-amber-200/90 ${CHAT_META_TEXT_CLASS}`}>
                    Question
                  </p>
                  <p className={`mt-1.5 whitespace-pre-wrap ${CHAT_TEXT_CLASS}`}>
                    {m.question}
                  </p>
                  <p className={`mt-2 text-amber-900/70 dark:text-amber-200/70 ${CHAT_META_TEXT_CLASS}`}>
                    Answer in the panel below.
                  </p>
                </div>
              </div>
            );
          }
          if (m.kind === "teachback_prompt") {
            return (
              <div key={m.id} className="flex w-full flex-col gap-2">
                <div
                  className={`max-w-[min(100%,42rem)] rounded-2xl border border-indigo-200/80 bg-indigo-50/60 px-4 py-3.5 text-indigo-950 shadow-sm dark:border-indigo-900/50 dark:bg-indigo-950/25 dark:text-indigo-50 ${CHAT_TEXT_CLASS}`}
                >
                  <p className={`uppercase tracking-wide text-indigo-700/90 dark:text-indigo-300/90 ${CHAT_META_TEXT_CLASS}`}>
                    Teachback
                  </p>
                  <p className={`mt-1.5 whitespace-pre-wrap ${CHAT_TEXT_CLASS}`}>
                    {m.message}
                  </p>
                  <p className={`mt-2 text-indigo-800/70 dark:text-indigo-300/70 ${CHAT_META_TEXT_CLASS}`}>
                    Explain in your own words below.
                  </p>
                </div>
              </div>
            );
          }
          if (m.kind === "teachback_exit") {
            return (
              <div key={m.id} className="flex w-full flex-col gap-2">
                <div
                  className={`max-w-[min(100%,42rem)] rounded-2xl border border-amber-200/80 bg-amber-50/60 px-4 py-3.5 text-amber-950 shadow-sm dark:border-amber-900/50 dark:bg-amber-950/25 dark:text-amber-50 ${CHAT_TEXT_CLASS}`}
                >
                  <p className={`mt-1.5 whitespace-pre-wrap ${CHAT_TEXT_CLASS}`}>
                    {m.message}
                  </p>
                </div>
              </div>
            );
          }
          if (m.kind === "feedback") {
            if (!String(m.message || "").trim()) return null;
            return (
              <FeedbackCard
                key={m.id}
                message={m.message}
                correct={m.correct}
              />
            );
          }
          return null;
        })}
        {recommendedTopics && recommendedTopics.length > 0 ? (
          <RecommendedTopics
            topics={recommendedTopics}
            learnUrlSuffix={learnUrlSuffix}
          />
        ) : null}
        {loading && (
          <div className="flex justify-start">
            <div className="rounded-2xl border border-slate-200/80 bg-white px-4 py-3 shadow-sm dark:border-slate-800 dark:bg-slate-900">
              <TypingIndicator />
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
