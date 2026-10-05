"use client";

import { Suspense, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";

function TopicRedirectInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const classId = searchParams.get("classId") ?? "";
  const subjectId = searchParams.get("subjectId") ?? "";

  useEffect(() => {
    const q = new URLSearchParams();
    if (classId) q.set("classId", classId);
    if (subjectId) q.set("subjectId", subjectId);
    const suffix = q.toString() ? `?${q.toString()}` : "";
    router.replace(`/teacher/workspace${suffix}`);
  }, [router, classId, subjectId]);

  return (
    <p className="mx-auto max-w-lg py-12 text-center text-sm text-slate-500">
      Redirecting to content workspace…
    </p>
  );
}

export default function TeacherTopicPage() {
  return (
    <Suspense
      fallback={
        <p className="text-center text-sm text-slate-500">Loading…</p>
      }
    >
      <TopicRedirectInner />
    </Suspense>
  );
}
