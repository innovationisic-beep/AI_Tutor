"use client";

import { useEffect, useRef } from "react";
import { CheckCircle2, ClipboardList, Minimize2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { InputBox } from "@/components/chat/InputBox";
import { ActionButtons } from "@/components/chat/ActionButtons";
import type { ClusterThreadItem } from "@/lib/learning/clusterQuizPanel";
import type { TutorActionButton } from "@/lib/types";
import { CHAT_META_TEXT_CLASS, CHAT_TEXT_CLASS } from "@/lib/teachingTypography";
import { cn, whiteboardFloatIconPosition } from "@/lib/utils";

type Props = {
  expanded: boolean;
  onExpandedChange: (open: boolean) => void;
  thread: ClusterThreadItem[];
  questionIndex: number;
  questionsTotal?: number;
  active?: boolean;
  awaitingAnswer: boolean;
  inputEnabled: boolean;
  inputDisabled: boolean;
  buttonsDisabled?: boolean;
  inputPlaceholder?: string;
  inputDisabledHint?: string | null;
  buttons: TutorActionButton[];
  onSend: (text: string) => void;
  onAction: (id: string) => void;
  whiteboardStreaming: boolean;
  iconSlot?: number;
  questionType?: "mcq" | "descriptive" | null;
  questionOptions?: string[];
  clarifying?: boolean;
};

export function ClusterQuizPanel({
  expanded,
  onExpandedChange,
  thread,
  questionIndex,
  questionsTotal = 3,
  active = true,
  awaitingAnswer,
  inputEnabled,
  inputDisabled,
  buttonsDisabled,
  inputPlaceholder,
  inputDisabledHint,
  buttons,
  onSend,
  onAction,
  whiteboardStreaming,
  iconSlot = 1,
  questionType = null,
  questionOptions = [],
  clarifying = false,
}: Props) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const badge = questionIndex + 1;
  const completed = !active && thread.length > 0;
  const idle = !active && thread.length === 0;
  const showMcqOptions =
    active &&
    inputEnabled &&
    !clarifying &&
    questionType === "mcq" &&
    questionOptions.length >= 2;

  useEffect(() => {
    if (expanded && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [
    expanded,
    thread.length,
    showMcqOptions,
    questionOptions.length,
    buttons.length,
    inputEnabled,
  ]);

  return (
    <>
      {!expanded ? (
        <button
          type="button"
          onClick={() => onExpandedChange(true)}
          className={cn(
            "absolute z-30 flex h-11 w-11 items-center justify-center rounded-full",
            whiteboardFloatIconPosition(iconSlot),
            "border-2 border-amber-500/80 bg-gradient-to-br from-amber-100 via-orange-50 to-yellow-100 shadow-lg transition hover:scale-105",
            "dark:border-amber-400/70 dark:from-amber-950 dark:via-orange-950 dark:to-yellow-950",
            active &&
              awaitingAnswer &&
              !whiteboardStreaming &&
              "animate-pulse ring-2 ring-amber-400/60",
            idle && "opacity-80"
          )}
          aria-label={completed ? "Review cluster quiz" : "Open cluster quiz"}
          data-testid="cluster-quiz-icon"
        >
          {completed ? (
            <CheckCircle2 className="h-5 w-5 text-amber-800 dark:text-amber-200" />
          ) : (
            <ClipboardList className="h-5 w-5 text-amber-800 dark:text-amber-200" />
          )}
          {!completed && !idle ? (
            <span
              className={cn(
                "absolute -right-1 -top-1 flex h-5 min-w-5 items-center justify-center rounded-full",
                "bg-amber-600 px-1 text-[10px] font-bold text-white dark:bg-orange-600"
              )}
            >
              {badge}
            </span>
          ) : null}
        </button>
      ) : null}

      {expanded ? (
        <div
          className="absolute inset-0 z-40 flex items-start justify-end p-3 md:p-4"
          role="dialog"
          aria-label="Cluster quiz"
          data-testid="cluster-quiz-popup"
        >
          <div
            className={cn(
              "relative z-10 flex h-[min(85%,520px)] max-h-[min(85%,520px)] w-full max-w-md flex-col overflow-hidden rounded-xl",
              "border-2 border-amber-500/45 bg-white/98 shadow-2xl backdrop-blur",
              "dark:border-amber-400/35 dark:bg-slate-950/98"
            )}
          >
            <header className="flex shrink-0 items-center justify-between gap-2 border-b border-amber-200/80 bg-gradient-to-r from-amber-50 via-orange-50/90 to-yellow-50 px-4 py-3 dark:border-amber-900/50 dark:from-amber-950/70 dark:via-orange-950/60 dark:to-yellow-950/70">
              <div>
                <p
                  className={`font-semibold uppercase tracking-wide text-amber-900 dark:text-amber-100 ${CHAT_META_TEXT_CLASS}`}
                >
                  Cluster quiz
                </p>
                <p className={`text-slate-600 dark:text-slate-400 ${CHAT_META_TEXT_CLASS}`}>
                  {completed
                    ? `Complete — ${questionsTotal} of ${questionsTotal}`
                    : `Question ${badge} of ${questionsTotal}`}
                </p>
              </div>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="shrink-0 text-slate-600"
                aria-label="Minimize"
                onClick={() => onExpandedChange(false)}
              >
                <Minimize2 className="h-4 w-4" />
              </Button>
            </header>

            <div
              ref={scrollRef}
              className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 py-3"
            >
              <div className="space-y-3">
                {thread.length === 0 ? (
                  <p className={`text-slate-500 ${CHAT_META_TEXT_CLASS}`}>
                    Questions and your answers appear here.
                  </p>
                ) : (
                  thread.map((item, i) => (
                    <ThreadBubble key={`${i}-${item.kind}-${item.id}`} item={item} />
                  ))
                )}

                {showMcqOptions ? (
                  <div className="flex flex-col gap-2">
                    {questionOptions.map((option, optionIndex) => (
                      <Button
                        key={`${optionIndex}-${option}`}
                        type="button"
                        variant="outline"
                        disabled={inputDisabled}
                        className={cn(
                          "h-auto min-h-10 justify-start whitespace-normal px-3 py-2 text-left",
                          CHAT_TEXT_CLASS
                        )}
                        onClick={() => onSend(option)}
                      >
                        {option}
                      </Button>
                    ))}
                  </div>
                ) : null}

                {active && buttons.length > 0 ? (
                  <div className="border-t border-slate-200 pt-2 dark:border-slate-800">
                    <ActionButtons
                      buttons={buttons}
                      disabled={buttonsDisabled ?? inputDisabled}
                      onAction={onAction}
                      conceptQuestionIndex={questionIndex}
                    />
                  </div>
                ) : null}

                {active && inputEnabled && !showMcqOptions ? (
                  <div className="border-t border-slate-200 pt-2 dark:border-slate-800">
                    <InputBox
                      onSend={onSend}
                      disabled={inputDisabled}
                      placeholder={
                        clarifying
                          ? "What are you confused about? Type or speak…"
                          : (inputPlaceholder ?? "Type or speak your answer…")
                      }
                      disabledHint={inputDisabledHint}
                    />
                  </div>
                ) : null}
              </div>
            </div>
          </div>

          <button
            type="button"
            className="absolute inset-0 -z-10 bg-black/20"
            aria-label="Close"
            onClick={() => onExpandedChange(false)}
          />
        </div>
      ) : null}
    </>
  );
}

function ThreadBubble({ item }: { item: ClusterThreadItem }) {
  if (item.kind === "section") {
    return (
      <div className="border-b border-amber-200/80 pb-1 pt-2 first:pt-0 dark:border-amber-800/60">
        <p
          className={`font-semibold uppercase tracking-wide text-amber-700 dark:text-amber-300 ${CHAT_META_TEXT_CLASS}`}
        >
          {item.heading}
        </p>
      </div>
    );
  }
  if (item.kind === "question") {
    return (
      <div className="rounded-lg border border-amber-200 bg-gradient-to-br from-amber-50/95 to-orange-50/80 px-3 py-2 dark:border-amber-800 dark:from-amber-950/50 dark:to-orange-950/40">
        <p className={`uppercase text-amber-800 dark:text-amber-200 ${CHAT_META_TEXT_CLASS}`}>
          Question {item.index + 1}
        </p>
        <p className={`mt-1 text-slate-800 dark:text-slate-100 ${CHAT_TEXT_CLASS}`}>
          {item.text}
        </p>
      </div>
    );
  }
  if (item.kind === "answer") {
    return (
      <div className="ml-6 rounded-lg bg-slate-100 px-3 py-2 dark:bg-slate-800">
        <p className={`uppercase text-slate-500 ${CHAT_META_TEXT_CLASS}`}>You</p>
        <p className={`mt-0.5 text-slate-800 dark:text-slate-100 ${CHAT_TEXT_CLASS}`}>
          {item.text}
        </p>
      </div>
    );
  }
  return (
    <div
      className={cn(
        "mr-4 rounded-lg px-3 py-2",
        item.correct === false
          ? "bg-rose-50 dark:bg-rose-950/30"
          : "bg-emerald-50 dark:bg-emerald-950/30"
      )}
    >
      <p className={`uppercase text-slate-500 ${CHAT_META_TEXT_CLASS}`}>Tutor</p>
      <p className={`mt-0.5 text-slate-800 dark:text-slate-100 ${CHAT_TEXT_CLASS}`}>
        {item.text}
      </p>
    </div>
  );
}
