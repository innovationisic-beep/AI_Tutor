"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Minimize2, NotebookPen } from "lucide-react";
import { Button } from "@/components/ui/button";
import { CHAT_META_TEXT_CLASS } from "@/lib/teachingTypography";
import { cn, whiteboardFloatIconPosition } from "@/lib/utils";

type Props = {
  expanded: boolean;
  onExpandedChange: (open: boolean) => void;
  value: string;
  onChange: (text: string) => void;
  onSave: (text: string) => void | Promise<void>;
  /** Shown when notes exist but panel is collapsed. */
  hasContent?: boolean;
  saveStatus?: "idle" | "saving" | "saved" | "error";
  /** Vertical stack slot: 0 = top (My notes). */
  iconSlot?: number;
};

const DEBOUNCE_MS = 700;

export function StudentScratchpadPanel({
  expanded,
  onExpandedChange,
  value,
  onChange,
  onSave,
  hasContent = false,
  saveStatus = "idle",
  iconSlot = 0,
}: Props) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const saveTimerRef = useRef<number | null>(null);
  const lastFlushedRef = useRef(value);
  const [localStatus, setLocalStatus] = useState(saveStatus);

  useEffect(() => {
    setLocalStatus(saveStatus);
  }, [saveStatus]);

  const flushSave = useCallback(
    (text: string) => {
      if (text === lastFlushedRef.current) return;
      lastFlushedRef.current = text;
      setLocalStatus("saving");
      void Promise.resolve(onSave(text))
        .then(() => setLocalStatus("saved"))
        .catch(() => setLocalStatus("error"));
    },
    [onSave]
  );

  const scheduleSave = useCallback(
    (text: string) => {
      if (saveTimerRef.current != null) {
        window.clearTimeout(saveTimerRef.current);
      }
      saveTimerRef.current = window.setTimeout(() => {
        saveTimerRef.current = null;
        flushSave(text);
      }, DEBOUNCE_MS);
    },
    [flushSave]
  );

  const handleChange = (text: string) => {
    onChange(text);
    scheduleSave(text);
  };

  useEffect(() => {
    if (expanded && textareaRef.current) {
      textareaRef.current.focus();
    }
  }, [expanded]);

  useEffect(() => {
    return () => {
      if (saveTimerRef.current != null) {
        window.clearTimeout(saveTimerRef.current);
      }
    };
  }, []);

  useEffect(() => {
    const onHide = () => flushSave(value);
    window.addEventListener("pagehide", onHide);
    return () => window.removeEventListener("pagehide", onHide);
  }, [value, flushSave]);

  const statusLabel =
    localStatus === "saving"
      ? "Saving…"
      : localStatus === "saved"
        ? "Saved"
        : localStatus === "error"
          ? "Could not save"
          : null;

  return (
    <>
      {!expanded ? (
        <button
          type="button"
          onClick={() => onExpandedChange(true)}
          className={cn(
            "absolute z-30 flex h-11 w-11 items-center justify-center rounded-full",
            whiteboardFloatIconPosition(iconSlot),
            "border-2 border-amber-600/75 bg-gradient-to-br from-amber-50 via-orange-50 to-yellow-100 shadow-lg transition hover:scale-105",
            "dark:border-amber-500/60 dark:from-amber-950 dark:via-orange-950 dark:to-yellow-950"
          )}
          aria-label="Open my notes"
          title="My notes"
          data-testid="student-scratchpad-icon"
        >
          <NotebookPen className="h-5 w-5 text-amber-900 dark:text-amber-100" />
          {hasContent ? (
            <span
              className="absolute -right-0.5 -top-0.5 h-2.5 w-2.5 rounded-full bg-amber-500 ring-2 ring-white dark:ring-slate-950"
              aria-hidden
            />
          ) : null}
        </button>
      ) : null}

      {expanded ? (
        <div
          className="absolute inset-0 z-40 flex items-end justify-start p-3 md:items-start md:justify-end md:p-4"
          role="dialog"
          aria-label="My notes"
          data-testid="student-scratchpad-popup"
        >
          <button
            type="button"
            className="absolute inset-0 bg-black/25 dark:bg-black/45"
            aria-label="Close my notes"
            onClick={() => {
              flushSave(value);
              onExpandedChange(false);
            }}
          />
          <div
            className={cn(
              "relative z-10 flex max-h-[min(70%,480px)] w-full max-w-md flex-col overflow-hidden rounded-xl",
              "border-2 border-amber-400/70 shadow-2xl",
              "bg-[linear-gradient(180deg,#fffbeb_0%,#fef3c7_100%)]",
              "dark:border-amber-500/40 dark:bg-[linear-gradient(180deg,#422006_0%,#292524_100%)]",
              "md:max-h-[min(85%,560px)]"
            )}
          >
            <div className="flex items-center justify-between gap-2 border-b border-amber-300/50 bg-amber-100/60 px-4 py-3 dark:border-amber-700/40 dark:bg-amber-950/50">
              <div className="flex min-w-0 items-center gap-2">
                <NotebookPen className="h-4 w-4 shrink-0 text-amber-800 dark:text-amber-200" />
                <div className="min-w-0">
                  <p className="text-sm font-semibold text-amber-950 dark:text-amber-50">
                    My notes
                  </p>
                  <p className={cn(CHAT_META_TEXT_CLASS, "text-xs text-amber-800/80 dark:text-amber-200/70")}>
                    Saved for this session
                  </p>
                </div>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                {statusLabel ? (
                  <span
                    className={cn(
                      CHAT_META_TEXT_CLASS,
                      "text-xs",
                      localStatus === "error"
                        ? "text-red-600 dark:text-red-400"
                        : "text-amber-700 dark:text-amber-300"
                    )}
                  >
                    {statusLabel}
                  </span>
                ) : null}
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="h-8 w-8 shrink-0"
                  aria-label="Minimize my notes"
                  onClick={() => {
                    flushSave(value);
                    onExpandedChange(false);
                  }}
                >
                  <Minimize2 className="h-4 w-4" />
                </Button>
              </div>
            </div>
            <textarea
              ref={textareaRef}
              value={value}
              onChange={(e) => handleChange(e.target.value)}
              placeholder="Jot down anything important during the lesson…"
              className={cn(
                "min-h-[200px] flex-1 resize-none border-0 px-4 py-3 text-base leading-relaxed",
                "bg-[#fffef5] text-amber-950 placeholder:text-amber-700/45",
                "focus:outline-none focus:ring-0",
                "dark:bg-[#1c1917] dark:text-amber-50 dark:placeholder:text-amber-200/35",
                "font-[family-name:var(--font-patrick-hand),cursive]"
              )}
              spellCheck
            />
          </div>
        </div>
      ) : null}
    </>
  );
}
