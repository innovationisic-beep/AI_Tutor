"use client";

import { useMemo } from "react";
import { useParams, useSearchParams } from "next/navigation";
import { useAuth } from "@/hooks/useAuth";
import { VtseTemplateAuthoringPage } from "@/components/curriculum/VtseTemplateAuthoringPage";

export default function AdminVtseTemplatePage() {
  const params = useParams();
  const search = useSearchParams();
  const { token, ready, user } = useAuth();
  const conceptId = typeof params.conceptId === "string" ? params.conceptId : "";
  const topicId = search.get("topicId") || "";
  const topicSource = (search.get("topicSource") === "teacher" ? "teacher" : "catalog") as
    | "catalog"
    | "teacher";

  const backHref = useMemo(() => {
    if (topicId) return `/admin/curriculum/builder/${topicId}`;
    return "/admin/curriculum";
  }, [topicId]);

  if (!ready || user?.role !== "admin") {
    return (
      <div className="mx-auto max-w-4xl p-6 text-sm text-slate-500">
        {!ready ? "Loading…" : "Admin only."}
      </div>
    );
  }

  if (!token || !conceptId) {
    return <div className="p-6 text-sm text-slate-500">Missing concept.</div>;
  }

  return (
    <VtseTemplateAuthoringPage
      conceptId={conceptId}
      topicSource={topicSource}
      token={token}
      backHref={backHref}
    />
  );
}
