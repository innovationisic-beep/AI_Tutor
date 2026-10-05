"use client";

import { useEffect, useRef } from "react";
import { BookOpen, Minimize2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { CHAT_META_TEXT_CLASS, CHAT_TEXT_CLASS } from "@/lib/teachingTypography";
import { cn, whiteboardFloatIconPosition } from "@/lib/utils";
import type { NotesPanelSection } from "@/lib/learning/panelSections";

export type ConceptNotesEntry = {
  conceptName: string;
  markdown: string;
};

type Props = {
  expanded: boolean;
  onExpandedChange: (open: boolean) => void;
  sections: NotesPanelSection[];
  /** When true, student must mark as read to continue the lesson. */
  active?: boolean;
  /** Vertical stack slot: 2 when concept check visible, else 1. */
  iconSlot?: number;
  onMarkAsRead?: () => void;
  markAsReadDisabled?: boolean;
};

export function PostConceptNotesPanel({
  expanded,
  onExpandedChange,
  sections,
  active = false,
  iconSlot = 2,
  onMarkAsRead,
  markAsReadDisabled = false,
}: Props) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const entryCount = sections.reduce((n, s) => n + s.entries.length, 0);

  useEffect(() => {
    if (expanded && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [expanded, sections.length, entryCount]);

  const idle = entryCount === 0 && !active;

  return (
    <>
      {!expanded ? (
        <button
          type="button"
          onClick={() => onExpandedChange(true)}
          className={cn(
            "absolute z-30 flex h-11 w-11 items-center justify-center rounded-full",
            whiteboardFloatIconPosition(iconSlot),
            "border-2 border-teal-500/80 bg-gradient-to-br from-teal-100 via-emerald-50 to-cyan-100 shadow-lg transition hover:scale-105",
            "dark:border-teal-400/70 dark:from-teal-950 dark:via-emerald-950 dark:to-cyan-950",
            active && "animate-pulse ring-2 ring-teal-400/60",
            idle && "opacity-80"
          )}
          aria-label={active ? "Open concept notes" : "Review concept notes"}
          data-testid="concept-notes-icon"
        >
          <BookOpen className="h-5 w-5 text-teal-800 dark:text-teal-100" />
          {active ? (
            <span className="absolute -right-1 -top-1 flex h-2.5 w-2.5 rounded-full bg-teal-500 ring-2 ring-white dark:ring-slate-950" />
          ) : null}
        </button>
      ) : null}

      {expanded ? (
        <div
          className="absolute inset-0 z-40 flex items-start justify-end p-3 md:p-4"
          role="dialog"
          aria-label="Concept notes"
          data-testid="concept-notes-popup"
        >
          <div
            className={cn(
              "relative z-10 flex max-h-[min(85%,560px)] w-full max-w-md flex-col overflow-hidden rounded-xl",
              "border-2 border-teal-500/45 bg-white/98 shadow-2xl backdrop-blur",
              "dark:border-teal-400/35 dark:bg-slate-950/98"
            )}
          >
            <header className="flex shrink-0 items-center justify-between gap-2 border-b border-teal-200/80 bg-gradient-to-r from-teal-50 via-emerald-50/90 to-cyan-50 px-4 py-3 dark:border-teal-900/50 dark:from-teal-950/70 dark:via-emerald-950/60 dark:to-cyan-950/70">
              <div>
                <p
                  className={`font-semibold uppercase tracking-wide text-teal-900 dark:text-teal-100 ${CHAT_META_TEXT_CLASS}`}
                >
                  Concept notes
                </p>
                <p className={`text-slate-600 dark:text-slate-400 ${CHAT_META_TEXT_CLASS}`}>
                  {active
                    ? "Review these notes, then mark as read"
                    : `${entryCount} concept${entryCount === 1 ? "" : "s"} saved`}
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
              className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-3"
            >
              {entryCount === 0 ? (
                <p className={`text-slate-500 dark:text-slate-400 ${CHAT_TEXT_CLASS}`}>
                  Concept notes will appear here as you complete each concept.
                </p>
              ) : (
                sections.map((section) => (
                  <div key={section.id} className="space-y-3">
                    {section.heading ? (
                      <p
                        className={`border-b border-teal-200/80 pb-1 font-semibold uppercase tracking-wide text-teal-800 dark:border-teal-800/60 dark:text-teal-200 ${CHAT_META_TEXT_CLASS}`}
                      >
                        {section.heading}
                      </p>
                    ) : null}
                    {section.entries.map((entry, i) => {
                      const isLatest =
                        section.id === sections[sections.length - 1]?.id &&
                        i === section.entries.length - 1;
                      const showMarkAsRead = active && isLatest && onMarkAsRead;
                      return (
                        <section
                          key={`${section.id}-${entry.conceptName}-${i}`}
                          className="rounded-lg border border-teal-100 bg-teal-50/40 px-3 py-2 dark:border-teal-900/50 dark:bg-teal-950/20"
                        >
                          <NotesMarkdown
                            markdown={entry.markdown}
                            conceptName={entry.conceptName}
                          />
                          {showMarkAsRead ? (
                            <div className="mt-3 border-t border-teal-200/80 pt-3 dark:border-teal-800/60">
                              <Button
                                type="button"
                                className="w-full bg-teal-600 text-white hover:bg-teal-700 dark:bg-teal-600 dark:hover:bg-teal-500"
                                disabled={markAsReadDisabled}
                                onClick={onMarkAsRead}
                                data-testid="concept-notes-mark-read"
                              >
                                Mark as read
                              </Button>
                            </div>
                          ) : null}
                        </section>
                      );
                    })}
                  </div>
                ))
              )}
            </div>
          </div>

          <button
            type="button"
            className="absolute inset-0 -z-10 bg-black/20"
            aria-label="Minimize notes"
            onClick={() => onExpandedChange(false)}
          />
        </div>
      ) : null}
    </>
  );
}

function NotesMarkdown({
  markdown,
  conceptName,
}: {
  markdown: string;
  conceptName: string;
}) {
  const lines = (markdown || "").split("\n");
  if (lines.length === 0 || !markdown.trim()) {
    return (
      <p className={`text-slate-600 dark:text-slate-300 ${CHAT_TEXT_CLASS}`}>
        Notes for {conceptName}
      </p>
    );
  }

  return (
    <div className={`space-y-1 text-slate-800 dark:text-slate-100 ${CHAT_TEXT_CLASS}`}>
      {lines.map((line, i) => {
        const trimmed = line.trim();
        if (trimmed.startsWith("## ")) {
          return (
            <h3
              key={i}
              className="pt-0.5 text-base font-bold text-teal-900 dark:text-teal-100"
            >
              {trimmed.slice(3)}
            </h3>
          );
        }
        if (trimmed.startsWith("### ")) {
          return (
            <h4
              key={i}
              className="pt-1 text-sm font-semibold text-amber-800 dark:text-amber-200"
            >
              {trimmed.slice(4)}
            </h4>
          );
        }
        if (trimmed.startsWith("- ")) {
          return (
            <li key={i} className="ml-4 list-disc text-sm leading-relaxed">
              {trimmed.slice(2)}
            </li>
          );
        }
        if (!trimmed) {
          return <div key={i} className="h-1" />;
        }
        return (
          <p key={i} className="text-sm leading-relaxed">
            {trimmed}
          </p>
        );
      })}
    </div>
  );
}
