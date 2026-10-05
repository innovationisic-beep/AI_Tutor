"use client";

import { Suspense } from "react";
import { TeacherWorkspace } from "@/components/teacher/workspace/TeacherWorkspace";

function WorkspaceFallback() {
  return (
    <div className="flex min-h-[40vh] items-center justify-center">
      <p className="text-sm text-slate-500">Loading workspace…</p>
    </div>
  );
}

export default function TeacherWorkspacePage() {
  return (
    <Suspense fallback={<WorkspaceFallback />}>
      <TeacherWorkspace />
    </Suspense>
  );
}
