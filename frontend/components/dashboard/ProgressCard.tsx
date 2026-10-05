"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";

type Props = {
  title: string;
  value: number;
  subtitle?: string;
};

export function ProgressCard({ title, value, subtitle }: Props) {
  const clamped = Math.min(100, Math.max(0, value));
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base font-medium text-slate-600 dark:text-slate-400">
          {title}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="flex items-baseline gap-2">
          <span className="text-3xl font-semibold tabular-nums text-slate-900 dark:text-slate-50">
            {clamped.toFixed(1)}%
          </span>
        </div>
        <Progress value={clamped} className="mt-3 h-2" />
        {subtitle ? (
          <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">{subtitle}</p>
        ) : null}
      </CardContent>
    </Card>
  );
}
