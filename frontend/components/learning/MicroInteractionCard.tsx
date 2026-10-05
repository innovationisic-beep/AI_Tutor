"use client";

import { MessageCircleQuestion } from "lucide-react";

type MicroInteractionCardProps = {
  prompt: string;
  /** Latest tutor reply after the student answered (shown in-chat; board may also update). */
  tutorReply?: string;
};

export function MicroInteractionCard({ prompt, tutorReply }: MicroInteractionCardProps) {
  const text = prompt.trim();
  const reply = tutorReply?.trim() ?? "";
  if (!text) return null;

  return (
    <section
      className="mx-1 mb-2 shrink-0 rounded-xl border border-indigo-200/80 bg-indigo-50/90 px-4 py-3 shadow-sm dark:border-indigo-500/35 dark:bg-indigo-950/50"
      aria-live="polite"
      aria-label="Reflection question"
      data-testid="micro-interaction-card"
    >
      <div className="flex items-center gap-2 text-indigo-800 dark:text-indigo-200">
        <MessageCircleQuestion className="h-5 w-5 shrink-0" aria-hidden />
        <h2 className="text-sm font-semibold uppercase tracking-wide">
          Think about this
        </h2>
      </div>
      <p className="mt-2 text-base font-medium leading-snug text-slate-900 dark:text-slate-100">
        {text}
      </p>
      {reply ? (
        <TutorReplyBlock reply={reply} />
      ) : (
        <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">
          Type your thoughts in the chat on the right — the lesson is waiting for your
          response.
        </p>
      )}
    </section>
  );
}

function TutorReplyBlock({ reply }: { reply: string }) {
  return (
    <div className="mt-3 rounded-lg border border-slate-200/80 bg-white/90 px-3 py-2 dark:border-slate-600 dark:bg-slate-900/60">
      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
        Your tutor
      </p>
      <p className="mt-1 whitespace-pre-wrap text-sm leading-relaxed text-slate-800 dark:text-slate-100">
        {reply}
      </p>
    </div>
  );
}
