"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import type { Topic } from "@/lib/types";

type Props = {
  topic: Topic;
  onSelect: () => void;
  disabled?: boolean;
};

export function TopicCard({ topic, onSelect, disabled }: Props) {
  const score = topic.mastery_score ?? 0;
  const clamped = Math.min(100, Math.max(0, score));

  return (
    <button
      type="button"
      onClick={onSelect}
      disabled={disabled}
      className="w-full text-left transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 disabled:pointer-events-none disabled:opacity-60"
    >
      <Card className="h-full transition-shadow hover:shadow-md">
        <CardHeader className="pb-2">
          <CardTitle className="text-base font-semibold">{topic.topic_name}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          <p className="line-clamp-2 text-sm text-slate-600 dark:text-slate-400">
            {topic.topic_description}
          </p>
          <div className="flex items-center gap-3">
            <Progress value={clamped} className="h-2 flex-1" />
            <span className="w-14 shrink-0 text-right text-sm font-medium tabular-nums text-slate-900 dark:text-slate-100">
              {topic.mastery_score === null ? "—" : `${Math.round(clamped)}%`}
            </span>
          </div>
        </CardContent>
      </Card>
    </button>
  );
}
