"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useAuth } from "@/hooks/useAuth";
import { CurriculumBuilder } from "@/components/curriculum/CurriculumBuilder";
import { getAdminCatalogSubjects, getAdminCatalogTopics } from "@/lib/api";
import { cn } from "@/lib/utils";

export default function AdminCurriculumBuilderPage() {
  const params = useParams();
  const topicId = typeof params.topicId === "string" ? params.topicId : "";
  const { token, ready, user } = useAuth();
  const [topicName, setTopicName] = useState<string | undefined>();
  const [toast, setToast] = useState<{ msg: string; variant: "ok" | "err" } | null>(null);

  const showToast = useCallback((msg: string, variant: "ok" | "err" = "ok") => {
    setToast({ msg, variant });
    window.setTimeout(() => setToast(null), 3200);
  }, []);

  useEffect(() => {
    if (!token || !topicId || user?.role !== "admin") return;
    let cancelled = false;
    (async () => {
      try {
        const subjects = await getAdminCatalogSubjects(token);
        for (const s of subjects) {
          const topics = await getAdminCatalogTopics(token, s.id);
          const hit = topics.find((t) => t.id === topicId);
          if (hit) {
            if (!cancelled) setTopicName(hit.topic_name);
            return;
          }
        }
      } catch {
        /* optional label */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token, topicId, user?.role]);

  if (!ready || user?.role !== "admin") {
    return (
      <div className="mx-auto max-w-4xl text-sm text-slate-500">
        {!ready ? "Loading…" : "Admin only."}
      </div>
    );
  }

  if (!token || !topicId) {
    return (
      <div className="mx-auto max-w-4xl text-sm text-slate-500">
        Missing topic.{" "}
        <Link href="/admin/curriculum" className="text-violet-600 underline">
          Back to curriculum
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
        topicSource="catalog"
        topicName={topicName}
        backHref="/admin/curriculum"
        backLabel="Back to catalog"
        planningHref={`/admin/curriculum/planning/${topicId}?topicName=${encodeURIComponent(topicName ?? "Topic")}`}
        onToast={showToast}
      />
    </>
  );
}
