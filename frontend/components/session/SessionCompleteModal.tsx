"use client";

import Link from "next/link";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import type { EndSessionResult } from "@/lib/types";

type Props = {
  open: boolean;
  result: EndSessionResult | null;
  onClose: () => void;
};

function ListSection({
  title,
  items,
  tone,
}: {
  title: string;
  items: string[];
  tone: "default" | "success" | "warning";
}) {
  if (!items.length) return null;
  const ulCls =
    tone === "success"
      ? "text-emerald-800 dark:text-emerald-200"
      : tone === "warning"
        ? "text-amber-900 dark:text-amber-200"
        : "text-slate-800 dark:text-slate-200";
  return (
    <div>
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
        {title}
      </h3>
      <ul className={`list-inside list-disc space-y-1 text-sm ${ulCls}`}>
        {items.map((x, i) => (
          <li key={i}>{x}</li>
        ))}
      </ul>
    </div>
  );
}

export function SessionCompleteModal({ open, result, onClose }: Props) {
  if (!open || !result) return null;

  const { summary, assignment, detailed_note } = result;

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-black/45 p-4 backdrop-blur-[2px]"
      role="presentation"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="session-complete-title"
        className="max-h-[min(90vh,40rem)] w-full max-w-lg overflow-y-auto rounded-2xl border border-slate-200 bg-white p-6 shadow-xl dark:border-slate-700 dark:bg-slate-950"
        onClick={(e) => e.stopPropagation()}
      >
        <h2
          id="session-complete-title"
          className="text-lg font-semibold text-slate-900 dark:text-slate-50"
        >
          Session complete
        </h2>
        <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
          You finished this topic. Your progress was saved, and when
          applicable we generated your session summary, notes, and practice
          suggestions.
        </p>

        <div className="mt-4 space-y-4">
          {summary ? (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-base">Session summary</CardTitle>
                <CardDescription>From your tutor session</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <p className="whitespace-pre-wrap text-sm leading-relaxed text-slate-800 dark:text-slate-200">
                  {summary.summary_text}
                </p>
                <ListSection
                  title="Key points"
                  items={summary.key_points_learned}
                  tone="default"
                />
                <ListSection
                  title="Strengths"
                  items={summary.strengths_identified}
                  tone="success"
                />
                <ListSection
                  title="Areas to improve"
                  items={summary.mistakes_identified}
                  tone="warning"
                />
              </CardContent>
            </Card>
          ) : (
            <p className="text-sm text-slate-500">
              No summary text was returned (generation may have been skipped).
            </p>
          )}

          {assignment ? (
            <Card className="border-violet-200/80 bg-violet-50/40 dark:border-violet-900/50 dark:bg-violet-950/20">
              <CardHeader className="pb-2">
                <CardTitle className="text-base">Practice assignment</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-sm text-slate-800 dark:text-slate-200">
                  {assignment.question_count} question
                  {assignment.question_count === 1 ? "" : "s"} · difficulty:{" "}
                  <span className="font-medium capitalize">
                    {assignment.difficulty_level}
                  </span>{" "}
                  · status: {assignment.status}
                </p>
                {assignment.focus_concepts.length > 0 ? (
                  <p className="mt-2 text-xs text-slate-600 dark:text-slate-400">
                    Focus: {assignment.focus_concepts.join(", ")}
                  </p>
                ) : null}
                <div className="mt-3 flex flex-wrap gap-2">
                  <Button asChild variant="default" size="sm">
                    <Link href={`/assignments/${encodeURIComponent(assignment.id)}`}>
                      Open assignment
                    </Link>
                  </Button>
                  <Button asChild variant="secondary" size="sm">
                    <Link href="/assignments">All assignments</Link>
                  </Button>
                </div>
              </CardContent>
            </Card>
          ) : (
            <p className="text-sm text-slate-500">
              No practice assignment was generated (often when mastery is high
              and there were no recorded mistakes).
            </p>
          )}

          {detailed_note ? (
            <Card className="border-sky-200/80 bg-sky-50/40 dark:border-sky-900/50 dark:bg-sky-950/20">
              <CardHeader className="pb-2">
                <CardTitle className="text-base">Detailed notes</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-sm text-slate-800 dark:text-slate-200">
                  Reusable AI study notes are available for this topic.
                </p>
                <div className="mt-3 flex flex-wrap gap-2">
                  <Button asChild variant="default" size="sm">
                    <Link
                      href={`/detailed-notes/${encodeURIComponent(
                        detailed_note.id
                      )}`}
                    >
                      Open notes
                    </Link>
                  </Button>
                  <Button asChild variant="secondary" size="sm">
                    <Link href="/detailed-notes">All detailed notes</Link>
                  </Button>
                </div>
              </CardContent>
            </Card>
          ) : (
            <p className="text-sm text-slate-500">
              No AI detailed notes for this topic yet (they are created when the
              tutor saves approved notes for the topic).
            </p>
          )}
        </div>

        <div className="mt-6 flex flex-wrap gap-2">
          <Button type="button" onClick={onClose}>
            Back to subjects
          </Button>
          <Button type="button" variant="outline" asChild>
            <Link href="/dashboard">Dashboard</Link>
          </Button>
        </div>
      </div>
    </div>
  );
}
