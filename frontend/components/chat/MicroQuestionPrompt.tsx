"use client";

import { CHAT_META_TEXT_CLASS, CHAT_TEXT_CLASS } from "@/lib/teachingTypography";

type Props = {
  question: string;
  questionIndex?: number;
  questionsTotal?: number;
};

/**
 * Zone 1 concept question — shown in chat after the VTSE board finishes.
 */
export function MicroQuestionPrompt({
  question,
  questionIndex,
  questionsTotal = 3,
}: Props) {
  const label =
    questionIndex != null && questionsTotal > 0
      ? `Question ${questionIndex + 1} of ${questionsTotal}`
      : "Your turn";

  return (
    <div
      className="shrink-0 border-t border-slate-200 bg-amber-50/90 px-4 py-3 dark:border-slate-700 dark:bg-amber-950/40"
      role="region"
      aria-label="Concept question"
      data-testid="micro-question-prompt"
    >
      <p className={`uppercase tracking-wide text-amber-800 dark:text-amber-200 ${CHAT_META_TEXT_CLASS}`}>
        {label}
      </p>
      <p className={`mt-1 text-slate-800 dark:text-slate-100 ${CHAT_TEXT_CLASS}`}>
        {question}
      </p>
      <p className={`mt-2 text-slate-600 dark:text-slate-400 ${CHAT_META_TEXT_CLASS}`}>
        Type or speak your answer below.
      </p>
    </div>
  );
}
