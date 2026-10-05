"use client";

import { useEffect, useRef } from "react";
import { CheckCircle2, MessageSquareQuote, Minimize2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { InputBox } from "@/components/chat/InputBox";
import type { ClusterTeachbackThreadItem } from "@/lib/learning/clusterTeachbackPanel";
import { CHAT_META_TEXT_CLASS, CHAT_TEXT_CLASS } from "@/lib/teachingTypography";
import { cn, whiteboardFloatIconPosition } from "@/lib/utils";

type Props = {
  expanded: boolean;
  onExpandedChange: (open: boolean) => void;
  thread: ClusterTeachbackThreadItem[];
  question: string;
  active?: boolean;
  inputEnabled: boolean;
  inputDisabled: boolean;
  inputPlaceholder?: string;
  inputDisabledHint?: string | null;
  onSend: (text: string) => void;
  whiteboardStreaming: boolean;
  iconSlot?: number;
};

export function ClusterTeachbackPanel({
  expanded,
  onExpandedChange,
  thread,
  question,
  active = true,
  inputEnabled,
  inputDisabled,
  inputPlaceholder = "Explain in your own words…",
  inputDisabledHint,
  onSend,
  whiteboardStreaming,
  iconSlot = 4,
}: Props) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const completed = !active && thread.some((t) => t.kind === "answer");
  const idle = !active && thread.length === 0;

  useEffect(() => {
    if (expanded && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [expanded, thread.length]);

  const displayQuestion = question.trim() || "Explain what you learned in this cluster.";

  return (
    <>
      {!expanded ? (
        <button
          type="button"
          onClick={() => onExpandedChange(true)}
          className={cn(
            "absolute z-30 flex h-11 w-11 items-center justify-center rounded-full",
            whiteboardFloatIconPosition(iconSlot),
            "border-2 border-rose-500/80 bg-gradient-to-br from-rose-100 via-pink-50 to-fuchsia-100 shadow-lg transition hover:scale-105",
            "dark:border-rose-400/70 dark:from-rose-950 dark:via-pink-950 dark:to-fuchsia-950",
            active &&
              inputEnabled &&
              !whiteboardStreaming &&
              "animate-pulse ring-2 ring-rose-400/60",
            idle && "opacity-80"
          )}
          aria-label={completed ? "Review teachback" : "Open cluster teachback"}
          data-testid="cluster-teachback-icon"
        >
          {completed ? (
            <CheckCircle2 className="h-5 w-5 text-rose-800 dark:text-rose-200" />
          ) : (
            <MessageSquareQuote className="h-5 w-5 text-rose-800 dark:text-rose-200" />
          )}
        </button>
      ) : null}

      {expanded ? (
        <div
          className="absolute inset-0 z-40 flex items-start justify-end p-3 md:p-4"
          role="dialog"
          aria-label="Cluster teachback"
          data-testid="cluster-teachback-popup"
        >
          <div
            className={cn(
              "relative z-10 flex max-h-[min(88%,580px)] w-full max-w-md flex-col overflow-hidden rounded-xl",
              "border-2 border-rose-500/45 bg-white/98 shadow-2xl backdrop-blur",
              "dark:border-rose-400/35 dark:bg-slate-950/98"
            )}
          >
            <header className="flex shrink-0 items-center justify-between gap-2 border-b border-rose-200/80 bg-gradient-to-r from-rose-50 via-pink-50/90 to-fuchsia-50 px-4 py-3 dark:border-rose-900/50 dark:from-rose-950/70 dark:via-pink-950/60 dark:to-fuchsia-950/70">
              <div>
                <p
                  className={`font-semibold uppercase tracking-wide text-rose-900 dark:text-rose-100 ${CHAT_META_TEXT_CLASS}`}
                >
                  Cluster teachback
                </p>
                <p className={`text-slate-600 dark:text-slate-400 ${CHAT_META_TEXT_CLASS}`}>
                  {completed ? "Submitted" : "Explain everything you learned"}
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
              className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-3"
            >
              {thread.length === 0 ? (
                <section className="rounded-lg border border-rose-100 bg-rose-50/50 px-3 py-2 dark:border-rose-900/40 dark:bg-rose-950/20">
                  <p
                    className={`mb-1 font-semibold uppercase tracking-wide text-rose-800 dark:text-rose-200 ${CHAT_META_TEXT_CLASS}`}
                  >
                    Your task
                  </p>
                  <p className={`text-slate-800 dark:text-slate-100 ${CHAT_TEXT_CLASS}`}>
                    {displayQuestion}
                  </p>
                </section>
              ) : (
                thread.map((item) => {
                  if (item.kind === "section") {
                    return (
                      <div
                        key={item.id}
                        className="border-b border-rose-200/80 pb-1 pt-2 first:pt-0 dark:border-rose-800/60"
                      >
                        <p
                          className={`font-semibold uppercase tracking-wide text-rose-700 dark:text-rose-300 ${CHAT_META_TEXT_CLASS}`}
                        >
                          {item.heading}
                        </p>
                      </div>
                    );
                  }
                  if (item.kind === "question") {
                    return (
                      <section
                        key={item.id}
                        className="rounded-lg border border-rose-100 bg-rose-50/50 px-3 py-2 dark:border-rose-900/40 dark:bg-rose-950/20"
                      >
                        <p
                          className={`mb-1 font-semibold uppercase tracking-wide text-rose-800 dark:text-rose-200 ${CHAT_META_TEXT_CLASS}`}
                        >
                          Question
                        </p>
                        <p className={`text-slate-800 dark:text-slate-100 ${CHAT_TEXT_CLASS}`}>
                          {item.text}
                        </p>
                      </section>
                    );
                  }
                  if (item.kind === "answer") {
                    return (
                      <section
                        key={item.id}
                        className="rounded-lg border border-slate-200 bg-white px-3 py-2 dark:border-slate-700 dark:bg-slate-900/40"
                      >
                        <p
                          className={`mb-1 font-semibold text-slate-500 dark:text-slate-400 ${CHAT_META_TEXT_CLASS}`}
                        >
                          Your answer
                        </p>
                        <p className={`text-slate-800 dark:text-slate-100 ${CHAT_TEXT_CLASS}`}>
                          {item.text}
                        </p>
                      </section>
                    );
                  }
                  if (item.kind === "tutor") {
                    return (
                      <section
                        key={item.id}
                        className={cn(
                          "rounded-lg border px-3 py-2",
                          item.correct === true
                            ? "border-emerald-200 bg-emerald-50/60 dark:border-emerald-900/50 dark:bg-emerald-950/30"
                            : item.correct === false
                              ? "border-amber-200 bg-amber-50/60 dark:border-amber-900/50 dark:bg-amber-950/30"
                              : "border-slate-200 bg-slate-50 dark:border-slate-700 dark:bg-slate-900/40"
                        )}
                      >
                        <p
                          className={`mb-1 font-semibold text-slate-500 dark:text-slate-400 ${CHAT_META_TEXT_CLASS}`}
                        >
                          Feedback
                        </p>
                        <p className={`text-slate-800 dark:text-slate-100 ${CHAT_TEXT_CLASS}`}>
                          {item.text}
                        </p>
                      </section>
                    );
                  }
                  return null;
                })
              )}
            </div>

            {active && inputEnabled ? (
              <footer className="shrink-0 border-t border-rose-200/80 px-3 py-3 dark:border-rose-900/50">
                <InputBox
                  onSend={onSend}
                  disabled={inputDisabled}
                  disabledHint={inputDisabledHint}
                  placeholder={inputPlaceholder}
                />
              </footer>
            ) : inputDisabledHint ? (
              <footer className="shrink-0 border-t border-rose-200/80 px-4 py-3 dark:border-rose-900/50">
                <p className={`text-center text-slate-500 ${CHAT_META_TEXT_CLASS}`}>
                  {inputDisabledHint}
                </p>
              </footer>
            ) : null}
          </div>

          <button
            type="button"
            className="absolute inset-0 -z-10 bg-black/20"
            aria-label="Minimize teachback"
            onClick={() => onExpandedChange(false)}
          />
        </div>
      ) : null}
    </>
  );
}
