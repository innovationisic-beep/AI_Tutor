"use client";

import { useMemo } from "react";
import { useParams, useSearchParams } from "next/navigation";
import { useAuth } from "@/hooks/useAuth";
import { VtseTemplateAuthoringPage } from "@/components/curriculum/VtseTemplateAuthoringPage";

export default function TeacherVtseTemplatePage() {
  const params = useParams();
  const search = useSearchParams();
  const { token, ready, user } = useAuth();
  const conceptId = typeof params.conceptId === "string" ? params.conceptId : "";
  const topicId = search.get("topicId") || "";

  const backHref = useMemo(() => {
    if (topicId) return `/teacher/workspace/curriculum/${topicId}`;
    return "/teacher/workspace";
  }, [topicId]);

  if (!ready || (user?.role !== "teacher" && user?.role !== "admin")) {
    return (
      <div className="mx-auto max-w-4xl p-6 text-sm text-slate-500">
        {!ready ? "Loading…" : "Teacher access required."}
      </div>
    );
  }

  if (!token || !conceptId) {
    return <div className="p-6 text-sm text-slate-500">Missing concept.</div>;
  }

  return (
    <VtseTemplateAuthoringPage
      conceptId={conceptId}
      topicSource="teacher"
      token={token}
      backHref={backHref}
    />
  );
}
