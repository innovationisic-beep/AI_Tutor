"use client";

import { Suspense, useCallback, useState } from "react";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useAuth } from "@/hooks/useAuth";
import { CurriculumBuilder } from "@/components/curriculum/CurriculumBuilder";
import { cn } from "@/lib/utils";

export default function TeacherCurriculumBuilderPage() {
  return (
    <Suspense
      fallback={
        <div className="mx-auto max-w-4xl text-sm text-slate-500">Loading…</div>
      }
    >
      <TeacherCurriculumBuilderInner />
    </Suspense>
  );
}

function TeacherCurriculumBuilderInner() {
  const params = useParams();
  const searchParams = useSearchParams();
  const topicId = typeof params.topicId === "string" ? params.topicId : "";
  const classId = searchParams.get("classId") ?? "";
  const subjectId = searchParams.get("subjectId") ?? "";
  const topicName = searchParams.get("topicName") ?? undefined;
  const { token, ready } = useAuth();
  const [toast, setToast] = useState<{ msg: string; variant: "ok" | "err" } | null>(null);

  const showToast = useCallback((msg: string, variant: "ok" | "err" = "ok") => {
    setToast({ msg, variant });
    window.setTimeout(() => setToast(null), 3200);
  }, []);

  const backHref =
    classId && subjectId
      ? `/teacher/workspace?${new URLSearchParams({ classId, subjectId }).toString()}`
      : "/teacher/workspace";

  if (!ready) {
    return <div className="mx-auto max-w-4xl text-sm text-slate-500">Loading…</div>;
  }

  if (!token || !topicId) {
    return (
      <div className="mx-auto max-w-4xl text-sm text-slate-500">
        Missing topic.{" "}
        <Link href={backHref} className="text-violet-600 underline">
          Back to workspace
        </Link>
      </div>
    );
  }

  return (
    <>
      {toast ? (
        <div
          className={cn(
            "fixed bottom-6 right-6 z-50 rounded-xl border px-4 py-3 text-sm shadow-lg",
            toast.variant === "ok"
              ? "border-emerald-200 bg-emerald-50 text-emerald-900 dark:border-emerald-800 dark:bg-emerald-950 dark:text-emerald-100"
              : "border-red-200 bg-red-50 text-red-900 dark:border-red-900 dark:bg-red-950 dark:text-red-100"
          )}
          role="status"
        >
          {toast.msg}
        </div>
      ) : null}
      <CurriculumBuilder
        token={token}
        topicId={topicId}
        topicSource="teacher"
        topicName={topicName}
        backHref={backHref}
        backLabel="Back to workspace"
        planningHref={
          classId && subjectId
            ? `/teacher/workspace/classroom?${new URLSearchParams({
                classId,
                subjectId,
                topicId,
                topicName: topicName ?? "Topic",
              }).toString()}`
            : null
        }
        onToast={showToast}
      />
    </>
  );
}
