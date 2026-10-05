"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useAuth } from "@/hooks/useAuth";
import {
  evaluateAssignment,
  getAssignmentDetail,
} from "@/lib/api";
import type { AssignmentDetail } from "@/lib/types";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { CheckCircle2, XCircle } from "lucide-react";

export default function AssignmentDetailPage() {
  const params = useParams();
  const router = useRouter();
  const assignmentId = params.assignmentId as string;
  const { token } = useAuth();
  const [detail, setDetail] = useState<AssignmentDetail | null>(null);
  const [answers, setAnswers] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!token || !assignmentId) return;
    setLoading(true);
    setError(null);
    try {
      const d = await getAssignmentDetail(token, assignmentId);
      setDetail(d);
      setAnswers(d.questions.map(() => ""));
    } catch (e) {
      setDetail(null);
      setError(e instanceof Error ? e.message : "Could not load assignment.");
    } finally {
      setLoading(false);
    }
  }, [token, assignmentId]);

  useEffect(() => {
    void load();
  }, [load]);

  const isPending = detail?.status === "pending";

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!token || !detail || !isPending) return;
    const trimmed = answers.map((a) => a.trim());
    if (trimmed.some((a) => !a)) {
      setError("Answer every question before submitting.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await evaluateAssignment(token, detail.id, trimmed);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Submit failed.");
    } finally {
      setSubmitting(false);
    }
  }

  if (loading && !detail) {
    return (
      <div className="mx-auto max-w-2xl px-4 py-8">
        <p className="text-sm text-slate-500">Loading assignment…</p>
      </div>
    );
  }

  if (error && !detail) {
    return (
      <div className="mx-auto max-w-2xl space-y-4 px-4 py-8">
        <p className="text-sm text-red-600 dark:text-red-400">{error}</p>
        <Button variant="outline" asChild>
          <Link href="/assignments">Back to assignments</Link>
        </Button>
      </div>
    );
  }

  if (!detail) return null;

  return (
    <div className="mx-auto max-w-2xl space-y-6 px-4 py-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Button variant="ghost" size="sm" asChild>
          <Link href="/assignments">← Assignments</Link>
        </Button>
      </div>

      <div>
        <h1 className="text-2xl font-semibold tracking-tight">
          {detail.topic_name ?? "Practice assignment"}
        </h1>
        <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
          <span className="capitalize">{detail.difficulty_level}</span>
          {" · "}
          <span className="font-medium">{detail.status}</span>
          {detail.score != null && detail.status === "completed" ? (
            <> · Score: {detail.score}%</>
          ) : null}
        </p>
        {detail.focus_concepts.length > 0 ? (
          <p className="mt-1 text-xs text-slate-500">
            Focus: {detail.focus_concepts.join(", ")}
          </p>
        ) : null}
      </div>

      {error ? (
        <p className="text-sm text-red-600 dark:text-red-400">{error}</p>
      ) : null}

      {isPending ? (
        <form onSubmit={handleSubmit} className="space-y-6">
          {detail.questions.map((q, idx) => (
            <Card key={idx}>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium text-slate-500">
                  Question {idx + 1}
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <p className="text-base leading-relaxed text-slate-900 dark:text-slate-100">
                  {q.question_text}
                </p>
                <Input
                  value={answers[idx] ?? ""}
                  onChange={(e) => {
                    const next = [...answers];
                    next[idx] = e.target.value;
                    setAnswers(next);
                  }}
                  placeholder="Your answer"
                  disabled={submitting}
                  autoComplete="off"
                />
              </CardContent>
            </Card>
          ))}
          <div className="flex gap-2">
            <Button type="submit" disabled={submitting}>
              {submitting ? "Submitting…" : "Submit all answers"}
            </Button>
            <Button
              type="button"
              variant="outline"
              disabled={submitting}
              onClick={() => router.push("/assignments")}
            >
              Cancel
            </Button>
          </div>
        </form>
      ) : (
        <div className="space-y-4">
          {detail.questions.map((q, idx) => {
            const ev = q.evaluation;
            return (
              <Card key={idx}>
                <CardHeader className="pb-2">
                  <div className="flex items-start gap-2">
                    {ev == null ? null : ev.is_correct ? (
                      <CheckCircle2 className="mt-0.5 size-5 shrink-0 text-emerald-600" />
                    ) : (
                      <XCircle className="mt-0.5 size-5 shrink-0 text-red-600" />
                    )}
                    <CardTitle className="text-base font-normal leading-snug">
                      {q.question_text}
                    </CardTitle>
                  </div>
                </CardHeader>
                <CardContent className="space-y-2 text-sm">
                  {ev ? (
                    <>
                      <p className="text-slate-600 dark:text-slate-400">
                        <span className="font-medium text-slate-800 dark:text-slate-200">
                          Your answer:{" "}
                        </span>
                        {ev.student_answer || "—"}
                      </p>
                      <p
                        className={
                          ev.is_correct
                            ? "text-emerald-800 dark:text-emerald-200"
                            : "text-slate-700 dark:text-slate-300"
                        }
                      >
                        {ev.feedback}
                      </p>
                    </>
                  ) : (
                    <p className="text-slate-500">No feedback stored.</p>
                  )}
                </CardContent>
              </Card>
            );
          })}
          <Button variant="outline" asChild>
            <Link href="/assignments">Back to assignments</Link>
          </Button>
        </div>
      )}
    </div>
  );
}
