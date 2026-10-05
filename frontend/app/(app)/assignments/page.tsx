"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useAuth } from "@/hooks/useAuth";
import { listAssignments } from "@/lib/api";
import type { StudentAssignment } from "@/lib/types";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";

export default function AssignmentsPage() {
  const { token } = useAuth();
  const [items, setItems] = useState<StudentAssignment[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!token) return;
    let c = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const list = await listAssignments(token);
        if (!c) setItems(list);
      } catch (e) {
        if (!c)
          setError(e instanceof Error ? e.message : "Failed to load assignments");
      } finally {
        if (!c) setLoading(false);
      }
    })();
    return () => {
      c = true;
    };
  }, [token]);

  return (
    <div className="w-full max-w-3xl space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Assignments</h1>
          <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
            Practice sets generated when you end a learning session (based on
            mastery and mistakes).
          </p>
        </div>
        <Button variant="outline" size="sm" asChild>
          <Link href="/subjects">Subjects</Link>
        </Button>
      </div>

      {error ? (
        <p className="text-sm text-red-600 dark:text-red-400">{error}</p>
      ) : null}
      {loading ? (
        <p className="text-sm text-slate-500">Loading…</p>
      ) : null}

      {!loading && items.length === 0 && !error ? (
        <p className="text-sm text-slate-500">
          No assignments yet. End a tutor session to generate one when practice
          is recommended.
        </p>
      ) : null}

      <ul className="space-y-3">
        {items.map((a, index) => {
          const n = Array.isArray(a.questions) ? a.questions.length : 0;
          return (
            <li key={`${a.id}-${index}`}>
              <Card className="transition hover:shadow-md">
                <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-2 pb-2">
                  <CardTitle className="text-base">
                    Topic{" "}
                    <span className="font-mono text-xs text-slate-500">
                      {a.topic_id.length > 8
                        ? `…${a.topic_id.slice(-6)}`
                        : a.topic_id}
                    </span>
                  </CardTitle>
                  <Button asChild size="sm" variant="secondary">
                    <Link href={`/assignments/${encodeURIComponent(a.id)}`}>
                      {a.status === "pending" ? "Open & solve" : "View results"}
                    </Link>
                  </Button>
                </CardHeader>
                <CardContent className="text-sm text-slate-600 dark:text-slate-400">
                  <p>
                    {n} question{n === 1 ? "" : "s"} ·{" "}
                    <span className="capitalize">{a.difficulty_level}</span> ·{" "}
                    <span className="font-medium text-slate-900 dark:text-slate-100">
                      {a.status}
                    </span>
                  </p>
                  {a.focus_concepts && a.focus_concepts.length > 0 ? (
                    <p className="mt-1 text-xs">
                      Focus: {a.focus_concepts.join(", ")}
                    </p>
                  ) : null}
                  {a.status === "completed" && a.score != null ? (
                    <p className="mt-1 text-xs">Score: {a.score}</p>
                  ) : null}
                </CardContent>
              </Card>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
