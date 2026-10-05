"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { BookDown, ChevronDown, Loader2, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  getTeacherCurriculumPreview,
  importTeacherCurriculum,
} from "@/lib/api";
import type {
  TeacherCurriculumPreview,
  TeacherCurriculumPreviewSampleQuestion,
} from "@/lib/types";
import { cn } from "@/lib/utils";

type CurriculumImportModalProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  token: string | null;
  classId: string;
  subjectId: string;
  onImported: () => void;
  onToast: (message: string, variant?: "ok" | "err") => void;
};

function QuestionPreviewBlock({
  q,
}: {
  q: TeacherCurriculumPreviewSampleQuestion;
}) {
  const opts = q.options ?? [];
  const correct = (q.correct_answer ?? "").trim();
  const hasMcq = opts.length >= 2 && correct;

  if (hasMcq) {
    return (
      <div className="rounded-lg border border-slate-200 bg-slate-50/80 p-3 dark:border-slate-600 dark:bg-slate-800/40">
        <p className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
          Question
        </p>
        <p className="mt-1 text-sm text-slate-900 dark:text-slate-100">
          {q.question_text}
        </p>
        <ul className="mt-2 space-y-1.5">
          {opts.map((opt) => {
            const isCorrect = opt === correct;
            return (
              <li
                key={`${q.question_text}-${opt}`}
                className={cn(
                  "flex gap-2 text-sm",
                  isCorrect
                    ? "font-medium text-emerald-800 dark:text-emerald-200"
                    : "text-slate-600 dark:text-slate-400"
                )}
              >
                <span className="shrink-0" aria-hidden>
                  {isCorrect ? "✔" : "•"}
                </span>
                <span>{opt}</span>
              </li>
            );
          })}
        </ul>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50/80 p-3 dark:border-slate-600 dark:bg-slate-800/40">
      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
        Question
      </p>
      <p className="mt-1 text-sm text-slate-900 dark:text-slate-100">
        <span className="font-medium text-slate-600 dark:text-slate-400">Q: </span>
        {q.question_text}
      </p>
      {correct ? (
        <p className="mt-2 text-sm font-medium text-emerald-800 dark:text-emerald-200">
          ✔ {correct}
        </p>
      ) : null}
      {opts.length > 0 && !hasMcq ? (
        <ul className="mt-2 space-y-1 text-sm text-slate-600 dark:text-slate-400">
          {opts.map((opt) => (
            <li key={opt} className="flex gap-2">
              <span aria-hidden>•</span>
              <span>{opt}</span>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

export function CurriculumImportModal({
  open,
  onOpenChange,
  token,
  classId,
  subjectId,
  onImported,
  onToast,
}: CurriculumImportModalProps) {
  const [loading, setLoading] = useState(false);
  const [importing, setImporting] = useState(false);
  const [preview, setPreview] = useState<TeacherCurriculumPreview | null>(null);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [expandedTopics, setExpandedTopics] = useState<Set<number>>(new Set());

  useEffect(() => {
    if (!open || !token || !classId || !subjectId) {
      if (!open) {
        setPreview(null);
        setFetchError(null);
        setLoading(false);
        setExpandedTopics(new Set());
      }
      return;
    }
    let cancelled = false;
    setLoading(true);
    setPreview(null);
    setFetchError(null);
    setExpandedTopics(new Set());
    void getTeacherCurriculumPreview(token, classId, subjectId)
      .then((p) => {
        if (!cancelled) setPreview(p);
      })
      .catch((e) => {
        if (!cancelled) {
          setFetchError(
            e instanceof Error ? e.message : "Failed to load preview"
          );
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, token, classId, subjectId]);

  function toggleTopic(index: number) {
    setExpandedTopics((prev) => {
      const next = new Set(prev);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });
  }

  async function handleImport() {
    if (!token) return;
    setImporting(true);
    try {
      await importTeacherCurriculum(token, classId, subjectId);
      onToast("Curriculum imported successfully");
      onImported();
      onOpenChange(false);
    } catch (e) {
      onToast(e instanceof Error ? e.message : "Import failed", "err");
    } finally {
      setImporting(false);
    }
  }

  if (!open) return null;

  const workspaceHref = `/teacher/workspace?${new URLSearchParams({ classId, subjectId }).toString()}`;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      role="presentation"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onOpenChange(false);
      }}
    >
      <div
        className="absolute inset-0 bg-slate-900/40 backdrop-blur-[1px]"
        aria-hidden
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="curriculum-import-title"
        className={cn(
          "relative z-10 flex max-h-[min(92vh,44rem)] w-full max-w-2xl flex-col overflow-hidden rounded-xl border border-slate-200 bg-white shadow-xl",
          "dark:border-slate-700 dark:bg-slate-900"
        )}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="flex shrink-0 items-start justify-between gap-2 border-b border-slate-200 px-5 py-4 dark:border-slate-800">
          <div className="flex items-center gap-2">
            <span className="flex size-9 items-center justify-center rounded-lg bg-violet-100 text-violet-700 dark:bg-violet-950/60 dark:text-violet-300">
              <BookDown className="size-5" />
            </span>
            <div>
              <h2
                id="curriculum-import-title"
                className="text-lg font-semibold text-slate-900 dark:text-slate-50"
              >
                Import curriculum
              </h2>
              <p className="text-xs text-slate-500 dark:text-slate-400">
                Preview only — your workspace lists teacher topics after import
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={() => onOpenChange(false)}
            disabled={importing}
            className="rounded-lg p-1 text-slate-500 hover:bg-slate-100 hover:text-slate-900 disabled:opacity-50 dark:hover:bg-slate-800 dark:hover:text-slate-100"
            aria-label="Close"
          >
            <X className="size-5" />
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          {loading ? (
            <div className="flex flex-col items-center justify-center gap-3 py-16 text-sm text-slate-600 dark:text-slate-400">
              <Loader2 className="size-9 animate-spin text-violet-600 dark:text-violet-400" />
              <span>Loading curriculum preview…</span>
            </div>
          ) : fetchError ? (
            <Card className="border-amber-200 bg-amber-50/50 dark:border-amber-900/40 dark:bg-amber-950/20">
              <CardHeader className="pb-2">
                <CardTitle className="text-base">Could not load preview</CardTitle>
                <CardDescription>{fetchError}</CardDescription>
              </CardHeader>
              <CardContent>
                <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
                  Close
                </Button>
              </CardContent>
            </Card>
          ) : preview && !preview.found ? (
            <Card className="border-slate-200 dark:border-slate-700">
              <CardHeader className="pb-2">
                <CardTitle className="text-base">No curriculum found</CardTitle>
                <CardDescription>
                  No admin curriculum available for this subject and grade
                </CardDescription>
              </CardHeader>
              <CardContent className="flex flex-wrap gap-2">
                <Button type="button" variant="secondary" asChild>
                  <Link href={workspaceHref}>Open workspace</Link>
                </Button>
                <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
                  Cancel
                </Button>
              </CardContent>
            </Card>
          ) : preview?.found && preview.subject ? (
            <div className="space-y-4">
              <div>
                <h3 className="text-base font-semibold text-slate-900 dark:text-slate-50">
                  Admin curriculum found
                </h3>
                <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
                  Subject:{" "}
                  <span className="font-medium text-slate-900 dark:text-slate-100">
                    {preview.subject.name}
                  </span>{" "}
                  <span className="text-slate-500 dark:text-slate-500">
                    ({preview.subject.grade})
                  </span>
                </p>
              </div>

              <div className="space-y-3">
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
                  Topics
                </p>
                <div className="max-h-[min(52vh,28rem)] space-y-3 overflow-y-auto pr-1">
                  {preview.topics.map((t, i) => {
                    const expanded = expandedTopics.has(i);
                    return (
                      <Card
                        key={`${t.name}-${i}`}
                        className="overflow-hidden border-slate-200 shadow-sm dark:border-slate-700"
                      >
                        <button
                          type="button"
                          onClick={() => toggleTopic(i)}
                          className="flex w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-slate-50/80 dark:hover:bg-slate-800/50"
                          aria-expanded={expanded}
                          aria-label={`${expanded ? "Collapse" : "Expand"} ${t.name}`}
                        >
                          <div className="min-w-0 flex-1">
                            <span className="font-semibold text-slate-900 dark:text-slate-50">
                              {t.name}
                            </span>
                          </div>
                          <span className="shrink-0 rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-medium text-slate-700 dark:bg-slate-800 dark:text-slate-200">
                            structured
                          </span>
                          <span className="flex shrink-0 items-center gap-1 text-xs font-medium text-slate-500 dark:text-slate-400">
                            <span>{expanded ? "Hide" : "Expand"}</span>
                            <ChevronDown
                              className={cn(
                                "size-4 transition-transform duration-200",
                                expanded && "rotate-180"
                              )}
                              aria-hidden
                            />
                          </span>
                        </button>
                        <div
                          className={cn(
                            "overflow-hidden border-t border-slate-100 transition-[max-height] duration-300 ease-in-out dark:border-slate-800",
                            expanded ? "max-h-[min(70vh,2000px)]" : "max-h-0 border-t-0"
                          )}
                        >
                          <div className="space-y-4 px-4 py-4">
                            <p className="text-sm text-slate-600 dark:text-slate-400">
                              Imported topics use structured curriculum. Open each topic in the
                              workspace after import to review zones and session plans.
                            </p>
                          </div>
                        </div>
                      </Card>
                    );
                  })}
                </div>
              </div>
            </div>
          ) : null}
        </div>

        {preview?.found && preview.subject ? (
          <div className="shrink-0 border-t border-slate-200 bg-white/95 px-5 py-4 backdrop-blur-sm dark:border-slate-800 dark:bg-slate-900/95">
            <Button
              type="button"
              className="w-full sm:w-auto"
              disabled={importing || !token}
              onClick={() => void handleImport()}
            >
              {importing ? (
                <>
                  <Loader2 className="mr-2 size-4 animate-spin" />
                  Importing…
                </>
              ) : (
                "Import curriculum"
              )}
            </Button>
          </div>
        ) : null}
      </div>
    </div>
  );
}
