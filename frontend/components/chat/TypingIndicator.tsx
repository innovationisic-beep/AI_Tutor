"use client";

import { CHAT_META_TEXT_CLASS } from "@/lib/teachingTypography";

export function TypingIndicator() {
  return (
    <div className={`flex items-center gap-1 text-slate-500 dark:text-slate-400 ${CHAT_META_TEXT_CLASS}`}>
      <span className="inline-flex gap-1">
        <span className="animate-bounce [animation-delay:-0.3s]">•</span>
        <span className="animate-bounce [animation-delay:-0.15s]">•</span>
        <span className="animate-bounce">•</span>
      </span>
      <span className="ml-1">Thinking…</span>
    </div>
  );
}
