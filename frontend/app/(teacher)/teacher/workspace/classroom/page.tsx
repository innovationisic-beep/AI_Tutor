"use client";

import { Suspense } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useAuth } from "@/hooks/useAuth";
import { ClassroomPlanningPanel } from "@/components/classroom/ClassroomPlanningPanel";
import { V2CurriculumWorkflowNav } from "@/components/curriculum/V2CurriculumWorkflowNav";
import { Button } from "@/components/ui/button";
import { useCallback, useState } from "react";

function Inner() {
  const { token } = useAuth();
  const searchParams = useSearchParams();
  const classId = searchParams.get("classId") ?? "";
  const subjectId = searchParams.get("subjectId") ?? "";
  const topicId = searchParams.get("topicId") ?? "";
  const topicName = searchParams.get("topicName") ?? "Topic";

  const [toast, setToast] = useState<{ text: string; ok: boolean } | null>(null);
  const showToast = useCallback((text: string, variant: "ok" | "err" = "ok") => {
    setToast({ text, ok: variant === "ok" });
    window.setTimeout(() => setToast(null), 3200);
  }, []);

  const backHref = `/teacher/workspace?${new URLSearchParams({ classId, subjectId }).toString()}`;
  const builderHref = `/teacher/workspace/curriculum/${topicId}?${new URLSearchParams({
    classId,
    subjectId,
    topicName,
  }).toString()}`;

  if (!token || !classId || !subjectId || !topicId) {
    return (
      <div className="mx-auto max-w-2xl p-6 text-center text-sm text-slate-500">
        <p>Open classroom planning from the teacher workspace with a topic selected.</p>
        <Button asChild className="mt-4" variant="outline">
          <Link href="/teacher/workspace">Back to workspace</Link>
        </Button>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-6xl space-y-4 p-4 md:p-6">
      <V2CurriculumWorkflowNav
        topicName={topicName}
        builderHref={builderHref}
        planningHref={null}
        workspaceHref={backHref}
        active="planning"
      />
      <div className="flex items-center justify-between gap-2">
        <div>
          <h1 className="text-xl font-semibold text-slate-900 dark:text-slate-50">
            Session planning — {topicName}
          </h1>
          <p className="text-sm text-slate-500">
            Define classroom sessions with cluster coverage for this topic.
          </p>
        </div>
      </div>
      {toast ? (
        <div
          className={
            toast.ok
              ? "rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-800"
              : "rounded-lg bg-red-50 px-3 py-2 text-sm text-red-800"
          }
        >
          {toast.text}
        </div>
      ) : null}
      <ClassroomPlanningPanel
        token={token}
        teacherTopicId={topicId}
        classId={classId}
        subjectId={subjectId}
        topicName={topicName}
        curriculumBuilderHref={builderHref}
        onToast={showToast}
      />
    </div>
  );
}

export default function TeacherClassroomPage() {
  return (
    <Suspense fallback={<p className="p-6 text-sm text-slate-500">Loading…</p>}>
      <Inner />
    </Suspense>
  );
}
