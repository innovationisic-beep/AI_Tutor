"use client";

import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useAuth } from "@/hooks/useAuth";
import { ClassroomPlanningPanel } from "@/components/classroom/ClassroomPlanningPanel";
import { V2CurriculumWorkflowNav } from "@/components/curriculum/V2CurriculumWorkflowNav";

export default function AdminCatalogPlanningPage() {
  const params = useParams();
  const searchParams = useSearchParams();
  const topicId = typeof params.topicId === "string" ? params.topicId : "";
  const topicName = searchParams.get("topicName") ?? "Topic";
  const { token, ready, user } = useAuth();

  if (!ready || user?.role !== "admin") {
    return (
      <div className="mx-auto max-w-6xl text-sm text-slate-500">
        {!ready ? "Loading…" : "Admin only."}
      </div>
    );
  }

  if (!token || !topicId) {
    return (
      <div className="mx-auto max-w-6xl text-sm text-slate-500">
        Missing topic.{" "}
        <Link href="/admin/curriculum" className="text-violet-600 underline">
          Back to catalog
        </Link>
      </div>
    );
  }

  const builderHref = `/admin/curriculum/builder/${topicId}`;
  const catalogHref = "/admin/curriculum";

  return (
    <div className="mx-auto max-w-6xl space-y-4 px-4 py-6">
      <V2CurriculumWorkflowNav
        topicName={topicName}
        builderHref={builderHref}
        planningHref={null}
        workspaceHref={catalogHref}
        active="planning"
      />
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 className="text-xl font-semibold text-slate-900 dark:text-slate-100">
            Session planning — {topicName}
          </h1>
          <p className="text-sm text-slate-500">
            Define Session 1, 2, 3… for independent students on this catalog topic.
          </p>
        </div>
      </div>
      <ClassroomPlanningPanel
        token={token}
        teacherTopicId={topicId}
        classId=""
        subjectId=""
        topicName={topicName}
        curriculumBuilderHref={builderHref}
        planScope="catalog"
        onToast={(msg, variant) => {
          if (variant === "err") window.alert(msg);
          else console.info(msg);
        }}
      />
    </div>
  );
}
