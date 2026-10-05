"use client";

import { MessageBubble } from "@/components/chat/MessageBubble";
import { FeedbackCard } from "@/components/chat/FeedbackCard";
import { WordSyncedStreaming } from "@/components/ai/WordSyncedStreaming";
import type { ChatItem } from "@/hooks/useChat";
import { cn } from "@/lib/utils";
import { WHITEBOARD_TEXT_CLASS } from "@/lib/teachingTypography";

type Props = {
  messages: ChatItem[];
  /** Ephemeral thinking row only — never persisted into messages. */
  loading?: boolean;
  /**
   * Assistant text id that should live word-stream + TTS.
   * All other tutor text bubbles render in staticMode (full text, no TTS).
   */
  activeStreamMessageId?: string | null;
  /** Same completion contract as AIWhiteboard onLastItemComplete. */
  onStreamComplete?: () => void;
  className?: string;
};

/** Tutor: content-sized, ~85–90% mobile / ~65–75% desktop of thread width. */
const TUTOR_BUBBLE_CLASS =
  "w-fit max-w-[90%] rounded-2xl border-zinc-300/70 bg-white/80 px-3.5 py-2 text-sm shadow-sm backdrop-blur-[1px] md:max-w-[72%] dark:border-zinc-600 dark:bg-zinc-800/80";

/** Student: somewhat narrower, right-aligned. */
const STUDENT_BUBBLE_CLASS =
  "w-fit max-w-[82%] rounded-2xl px-3.5 py-2 text-sm shadow-sm md:max-w-[58%]";

const TUTOR_FEEDBACK_WRAP_CLASS = "w-fit max-w-[90%] md:max-w-[72%]";

/** Ephemeral thinking row — never persisted into messages. */
export function TutorThinkingBubble({
  testId = "inline-tutor-thinking",
}: {
  testId?: string;
}) {
  return (
    <div
      className="flex w-full justify-start"
      data-testid={testId}
      data-align="left"
      aria-live="polite"
    >
      <div
        className={cn(
          TUTOR_BUBBLE_CLASS,
          "border-dashed text-slate-500 dark:text-slate-400"
        )}
      >
        Tutor is thinking…
      </div>
    </div>
  );
}

function bubbleText(m: ChatItem): string {
  if (m.role === "user") return m.content;
  if (m.kind === "teachback_prompt" || m.kind === "teachback_exit") {
    return m.message;
  }
  if (m.kind === "feedback") return m.message;
  if (m.kind === "text") return m.content;
  if (m.kind === "quiz_prompt") {
    return [m.intro, m.question].filter(Boolean).join("\n\n");
  }
  return "";
}

function TutorTextBubble({
  message,
  activeStreamMessageId,
  onStreamComplete,
}: {
  message: Extract<ChatItem, { role: "assistant"; kind: "text" }>;
  activeStreamMessageId?: string | null;
  onStreamComplete?: () => void;
}) {
  const isActive = message.id === activeStreamMessageId;
  const notesMode = message.writingMode === "notes";
  const hasWrites = Boolean(
    notesMode && message.boardWrites && message.boardWrites.length
  );
  // Empty displayText = speak-only on board; in a bubble still reveal spoken words.
  const displayText =
    notesMode && message.displayText !== undefined && message.displayText !== ""
      ? message.displayText
      : undefined;
  const spoken = message.content.trim() ? message.content : "\u00a0";

  return (
    <MessageBubble role="assistant" className={TUTOR_BUBBLE_CLASS}>
      <WordSyncedStreaming
        text={spoken}
        displayText={displayText}
        boardWrites={hasWrites ? message.boardWrites : undefined}
        className="!font-inherit text-inherit"
        staticMode={!isActive}
        onComplete={isActive ? onStreamComplete : undefined}
      />
    </MessageBubble>
  );
}

/**
 * WhatsApp-style conversation rendered *inside* the whiteboard scroll surface.
 * Tutor prose uses WordSyncedStreaming (same TTS / word-sync as the board).
 */
export function InlineBoardChat({
  messages,
  loading,
  activeStreamMessageId,
  onStreamComplete,
  className,
}: Props) {
  // Board-level auto-scroll owns the scroll container (AIWhiteboard).
  // Do not force scrollIntoView here — that ignores user scroll-up intent.
  if (messages.length === 0 && !loading) {
    return null;
  }

  return (
    <div
      key="inline-board-conversation"
      className={cn("w-full", WHITEBOARD_TEXT_CLASS, className)}
      aria-label="Conversation"
      data-testid="inline-board-chat"
      data-conversation-key="inline-board-conversation"
    >
      <div className="flex flex-col gap-2.5 md:gap-3">
        {messages.map((m) => {
          if (m.role === "user") {
            return (
              <MessageBubble
                key={m.id}
                role="user"
                className={STUDENT_BUBBLE_CLASS}
              >
                {bubbleText(m)}
              </MessageBubble>
            );
          }
          if (m.kind === "feedback") {
            if (!String(m.message || "").trim()) return null;
            return (
              <div
                key={m.id}
                className="flex w-full justify-start"
                data-testid="bubble-tutor"
                data-align="left"
              >
                <div className={TUTOR_FEEDBACK_WRAP_CLASS}>
                  <FeedbackCard message={m.message} correct={m.correct} />
                </div>
              </div>
            );
          }
          if (m.kind === "text") {
            return (
              <TutorTextBubble
                key={m.id}
                message={m}
                activeStreamMessageId={activeStreamMessageId}
                onStreamComplete={onStreamComplete}
              />
            );
          }
          if (m.kind === "teachback_prompt" || m.kind === "teachback_exit") {
            const isActive = m.id === activeStreamMessageId;
            return (
              <MessageBubble
                key={m.id}
                role="assistant"
                className={TUTOR_BUBBLE_CLASS}
              >
                <WordSyncedStreaming
                  text={m.message.trim() ? m.message : "\u00a0"}
                  className="!font-inherit text-inherit"
                  staticMode={!isActive}
                  onComplete={isActive ? onStreamComplete : undefined}
                />
              </MessageBubble>
            );
          }
          return null;
        })}
        {loading ? <TutorThinkingBubble /> : null}
      </div>
    </div>
  );
}
