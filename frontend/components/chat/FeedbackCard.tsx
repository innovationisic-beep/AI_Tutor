"use client";

import { cn } from "@/lib/utils";
import { CHAT_TEXT_CLASS } from "@/lib/teachingTypography";
import { Card, CardContent } from "@/components/ui/card";
import { CheckCircle2, XCircle } from "lucide-react";

type Props = {
  message: string;
  correct: boolean;
};

export function FeedbackCard({ message, correct }: Props) {
  return (
    <Card
      className={cn(
        "max-w-[min(100%,42rem)] rounded-2xl border-2 shadow-sm",
        correct
          ? "border-emerald-200 bg-emerald-50/80 dark:border-emerald-900 dark:bg-emerald-950/30"
          : "border-red-200 bg-red-50/80 dark:border-red-900 dark:bg-red-950/30"
      )}
    >
      <CardContent className="flex gap-3 px-4 pb-5 pt-5">
        {correct ? (
          <CheckCircle2 className="size-6 shrink-0 text-emerald-600 dark:text-emerald-400" />
        ) : (
          <XCircle className="size-6 shrink-0 text-red-600 dark:text-red-400" />
        )}
        <div className="min-w-0 flex-1">
          <p className={`text-slate-900 dark:text-slate-100 ${CHAT_TEXT_CLASS}`}>
            {correct ? "Nice work" : "Keep going"}
          </p>
          {message.trim() ? (
            <p className={`mt-1 whitespace-pre-wrap text-slate-700 dark:text-slate-300 ${CHAT_TEXT_CLASS}`}>
              {message}
            </p>
          ) : null}
        </div>
      </CardContent>
    </Card>
  );
}
