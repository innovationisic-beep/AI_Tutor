"use client";

import { useEffect } from "react";
import { useAuth } from "@/hooks/useAuth";
import { useProgress } from "@/hooks/useProgress";
import { SubjectCard } from "@/components/subjects/SubjectCard";

export default function SubjectsPage() {
  const { token, isInstitution } = useAuth();
  const { subjects, fetchSubjects, loading, error } = useProgress(
    token,
    isInstitution
  );

  useEffect(() => {
    void fetchSubjects();
  }, [fetchSubjects]);

  const title = isInstitution ? "Class & subjects" : "Free learning";
  const subtitle = isInstitution
    ? "Your school’s subjects (linked to your class). Pick one to see topics and mastery."
    : "Browse the shared curriculum. Pick a subject to see topics and mastery.";

  return (
    <div className="w-full max-w-5xl space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        <p className="mt-1 text-slate-600 dark:text-slate-400">{subtitle}</p>
      </div>

      {error ? (
        <p className="text-sm text-red-600 dark:text-red-400">{error}</p>
      ) : null}

      {loading && subjects.length === 0 ? (
        <p className="text-sm text-slate-500">Loading subjects…</p>
      ) : null}

      <div className="grid gap-4 sm:grid-cols-2">
        {subjects.map((s) => (
          <SubjectCard key={s.id} subject={s} />
        ))}
      </div>

      {!loading && subjects.length === 0 && !error ? (
        <p className="text-sm text-slate-500">
          {isInstitution
            ? "No subjects are set up for your class yet. Ask your teacher or school admin."
            : "No subjects are available yet. If this persists, the platform curriculum may still be loading."}
        </p>
      ) : null}
    </div>
  );
}
