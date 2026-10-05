"use client";

import { cn } from "@/lib/utils";
import { CHAT_TEXT_CLASS } from "@/lib/teachingTypography";

type Props = {
  role: "user" | "assistant";
  children: React.ReactNode;
  className?: string;
};

export function MessageBubble({ role, children, className }: Props) {
  const isUser = role === "user";
  return (
    <div
      className={cn(
        "flex w-full",
        isUser ? "justify-end" : "justify-start"
      )}
      data-testid={isUser ? "bubble-student" : "bubble-tutor"}
      data-align={isUser ? "right" : "left"}
    >
      <div
        className={cn(
          "max-w-[min(100%,42rem)] rounded-2xl px-4 py-3 shadow-sm",
          CHAT_TEXT_CLASS,
          isUser
            ? "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900"
            : "border border-slate-200/80 bg-white text-slate-800 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-100",
          className
        )}
      >
        {children}
      </div>
    </div>
  );
}
