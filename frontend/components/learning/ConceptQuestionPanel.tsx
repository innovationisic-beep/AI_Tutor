"use client";

import { useEffect, useRef } from "react";
import { CheckCircle2, HelpCircle, Minimize2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { InputBox } from "@/components/chat/InputBox";
import { ActionButtons } from "@/components/chat/ActionButtons";
import type { ConceptThreadItem } from "@/lib/learning/conceptQuestionPanel";
import type { TutorActionButton } from "@/lib/types";
import { CHAT_META_TEXT_CLASS, CHAT_TEXT_CLASS } from "@/lib/teachingTypography";
import { cn, whiteboardFloatIconPosition } from "@/lib/utils";

type Props = {
  expanded: boolean;
  onExpandedChange: (open: boolean) => void;
  thread: ConceptThreadItem[];
  questionIndex: number;
  questionsTotal?: number;
  /** When false, panel is read-only review (icon stays, no input/buttons). */
  active?: boolean;
  /** True when student should answer (board idle, question armed). */
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
  /** Vertical stack slot in top-right: 0 = top (My notes), 1 = concept check, 2 = concept notes. */
  iconSlot?: number;
  questionType?: "mcq" | "fill_in_blank" | null;
  questionOptions?: string[];
  /** Free-text confusion loop — never show MCQ options. */
  clarifying?: boolean;
};

export function ConceptQuestionPanel({
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
      {/* Minimized — top-right icon on whiteboard */}
      {!expanded ? (
        <button
          type="button"
          onClick={() => onExpandedChange(true)}
          className={cn(
            "absolute z-30 flex h-11 w-11 items-center justify-center rounded-full",
            whiteboardFloatIconPosition(iconSlot),
            "border-2 border-violet-500/80 bg-gradient-to-br from-violet-100 via-indigo-50 to-purple-100 shadow-lg transition hover:scale-105",
            "dark:border-violet-400/70 dark:from-violet-950 dark:via-indigo-950 dark:to-purple-950",
            active &&
              awaitingAnswer &&
              !whiteboardStreaming &&
              "animate-pulse ring-2 ring-violet-400/60",
            idle && "opacity-80"
          )}
          aria-label={completed ? "Review concept check" : "Open concept questions"}
          data-testid="concept-question-icon"
        >
          {completed ? (
            <CheckCircle2 className="h-5 w-5 text-violet-700 dark:text-violet-200" />
          ) : (
            <HelpCircle className="h-5 w-5 text-violet-700 dark:text-violet-200" />
          )}
          {!completed && !idle ? (
            <span
              className={cn(
                "absolute -right-1 -top-1 flex h-5 min-w-5 items-center justify-center rounded-full",
                "bg-violet-600 px-1 text-[10px] font-bold text-white dark:bg-indigo-500"
              )}
            >
              {badge}
            </span>
          ) : null}
        </button>
      ) : null}

      {/* Expanded popup */}
      {expanded ? (
        <div
          className="absolute inset-0 z-40 flex items-start justify-end p-3 md:p-4"
          role="dialog"
          aria-label="Concept questions"
          data-testid="concept-question-popup"
        >
          <div
            className={cn(
              "relative z-10 flex h-[min(85%,520px)] max-h-[min(85%,520px)] w-full max-w-md flex-col overflow-hidden rounded-xl",
              "border-2 border-violet-500/45 bg-white/98 shadow-2xl backdrop-blur",
              "dark:border-violet-400/35 dark:bg-slate-950/98"
            )}
          >
            <header className="flex shrink-0 items-center justify-between gap-2 border-b border-violet-200/80 bg-gradient-to-r from-violet-50 via-indigo-50/90 to-purple-50 px-4 py-3 dark:border-violet-900/50 dark:from-violet-950/70 dark:via-indigo-950/60 dark:to-purple-950/70">
              <div>
                <p
                  className={`font-semibold uppercase tracking-wide text-violet-900 dark:text-violet-100 ${CHAT_META_TEXT_CLASS}`}
                >
                  Concept check
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
                          : questionType === "fill_in_blank"
                            ? "Fill in the blank…"
                            : (inputPlaceholder ?? "Type or speak your answer…")
                      }
                      disabledHint={inputDisabledHint}
                    />
                  </div>
                ) : null}
              </div>
            </div>
          </div>

          {/* Click backdrop to minimize */}
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

function ThreadBubble({ item }: { item: ConceptThreadItem }) {
  if (item.kind === "section") {
    return (
      <div className="border-b border-violet-200/80 pb-1 pt-2 first:pt-0 dark:border-violet-800/60">
        <p
          className={`font-semibold uppercase tracking-wide text-violet-700 dark:text-violet-300 ${CHAT_META_TEXT_CLASS}`}
        >
          {item.heading}
        </p>
      </div>
    );
  }
  if (item.kind === "question") {
    return (
      <div className="rounded-lg border border-violet-200 bg-gradient-to-br from-violet-50/95 to-indigo-50/80 px-3 py-2 dark:border-violet-800 dark:from-violet-950/50 dark:to-indigo-950/40">
        <p className={`uppercase text-violet-800 dark:text-violet-200 ${CHAT_META_TEXT_CLASS}`}>
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
