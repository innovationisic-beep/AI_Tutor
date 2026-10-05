"use client";

import { useEffect } from "react";
import Link from "next/link";
import { useAuth } from "@/hooks/useAuth";
import { useProgress } from "@/hooks/useProgress";
import { ProgressCard } from "@/components/dashboard/ProgressCard";
import { TutorLanguageToggle } from "@/components/dashboard/TutorLanguageToggle";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { BookOpen } from "lucide-react";

export default function DashboardPage() {
  const { token, user, isInstitution } = useAuth();
  const { dashboard, fetchDashboard, loading, error } = useProgress(
    token,
    isInstitution
  );

  useEffect(() => {
    void fetchDashboard();
  }, [fetchDashboard]);

  const first = user?.email?.split("@")[0] ?? "there";

  return (
    <div className="w-full max-w-5xl space-y-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900 dark:text-slate-50">
          Welcome back, {first}
        </h1>
        <p className="mt-1 text-slate-600 dark:text-slate-400">
          Track mastery and pick up where you left off.
        </p>
      </div>

      {error ? (
        <p className="text-sm text-red-600 dark:text-red-400">{error}</p>
      ) : null}

      <div className="grid gap-4 sm:grid-cols-2">
        <ProgressCard
          title="Overall mastery"
          value={dashboard?.overall_mastery ?? 0}
          subtitle={
            dashboard
              ? `Across ${dashboard.topics_practiced} topic${
                  dashboard.topics_practiced === 1 ? "" : "s"
                } with recorded progress`
              : loading
                ? "Loading…"
                : undefined
          }
        />
        <Card>
          <CardHeader>
            <CardTitle className="text-base font-medium text-slate-600 dark:text-slate-400">
              Next step
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <p className="text-sm text-slate-600 dark:text-slate-400">
              {isInstitution
                ? "Continue with a class subject or start a new topic."
                : "Continue with free learning or start a new topic."}
            </p>
            <Button asChild>
              <Link href="/subjects">
                <BookOpen className="size-4" />
                {isInstitution ? "Browse class subjects" : "Browse free learning"}
              </Link>
            </Button>
          </CardContent>
        </Card>
      </div>

      <TutorLanguageToggle token={token} />

      <div>
        <h2 className="mb-3 text-lg font-semibold text-slate-900 dark:text-slate-50">
          Recent topics
        </h2>
        {loading && !dashboard ? (
          <p className="text-sm text-slate-500">Loading activity…</p>
        ) : null}
        {!loading && dashboard && dashboard.recent_topics.length === 0 ? (
          <p className="text-sm text-slate-500">
            {isInstitution
              ? "No recent activity yet. Open a subject from your class and start learning."
              : "No recent activity yet. Open a subject and start learning."}
          </p>
        ) : null}
        <ul className="grid gap-3 sm:grid-cols-2">
          {(dashboard?.recent_topics ?? []).map((t) => (
            <li key={t.id}>
              <Link
                href={`/learn/${t.id}?topicName=${encodeURIComponent(t.topic_name)}`}
                className="block rounded-xl border border-slate-200/80 bg-white p-4 shadow-sm transition hover:shadow-md dark:border-slate-800 dark:bg-slate-900"
              >
                <p className="font-medium text-slate-900 dark:text-slate-100">
                  {t.topic_name}
                </p>
                <p className="mt-1 text-xs text-slate-500">
                  Mastery {Math.round(t.mastery_score ?? 0)}%
                </p>
              </Link>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
