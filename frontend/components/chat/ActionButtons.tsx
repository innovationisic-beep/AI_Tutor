"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { labelForActionId, relabelConceptNextButton } from "@/lib/tutorFlow";
import type { TutorActionButton } from "@/lib/types";
import { cn } from "@/lib/utils";
import { CHAT_META_TEXT_CLASS } from "@/lib/teachingTypography";

type Props = {
  buttons: TutorActionButton[];
  disabled?: boolean;
  onAction: (actionId: string) => void;
  /** When on the last concept question, relabel concept_q_next to "I understand". */
  conceptQuestionIndex?: number;
  /** Tighter chrome when mounted under the whiteboard. */
  compact?: boolean;
};

/**
 * Teacher-flow actions: sends `__action:<id>` via onAction.
 * Labels are UI-only; ids are unchanged for the API.
 */
export function ActionButtons({
  buttons,
  disabled,
  onAction,
  conceptQuestionIndex,
  compact = false,
}: Props) {
  const [clickedLock, setClickedLock] = useState(false);

  useEffect(() => {
    if (!disabled) setClickedLock(false);
  }, [disabled]);

  const displayButtons = relabelConceptNextButton(buttons, conceptQuestionIndex);

  if (!displayButtons.length) return null;

  const effectivelyDisabled = Boolean(disabled || clickedLock);

  return (
    <div
      className={cn(
        compact
          ? "border-0 bg-transparent px-3 py-2.5 md:px-4"
          : "border-t border-slate-200/80 bg-slate-50/90 px-4 py-4 dark:border-slate-800 dark:bg-slate-900/50"
      )}
      data-testid="board-action-buttons"
    >
      <div
        className={cn(
          "mx-auto grid max-w-3xl grid-cols-1 sm:grid-cols-2",
          compact ? "gap-2" : "gap-3"
        )}
      >
        {displayButtons.map((b) => (
          <Button
            key={b.id}
            type="button"
            variant="secondary"
            size="default"
            disabled={effectivelyDisabled}
            className={cn(
              "h-auto min-h-10 justify-center rounded-2xl px-4 py-2.5",
              CHAT_META_TEXT_CLASS,
              "transition-transform hover:scale-[1.01] active:scale-[0.99]",
              "shadow-sm hover:shadow"
            )}
            onClick={() => {
              if (effectivelyDisabled) return;
              setClickedLock(true);
              onAction(b.id);
            }}
          >
            {b.label ||
              labelForActionId(b.id, { questionIndex: conceptQuestionIndex })}
          </Button>
        ))}
      </div>
    </div>
  );
}
