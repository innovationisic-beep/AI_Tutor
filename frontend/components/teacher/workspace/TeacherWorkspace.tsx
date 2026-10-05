"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useAuth } from "@/hooks/useAuth";
import { getOrgStructure, getTeacherTopics } from "@/lib/api";
import type { OrgStructure, TeacherTopicRecord } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Plus } from "lucide-react";
import { TopicPanel } from "./TopicPanel";
import { ContentEditor } from "./ContentEditor";
import { CurriculumImportModal } from "./CurriculumImportModal";
import { cn } from "@/lib/utils";

export function TeacherWorkspace() {
  const searchParams = useSearchParams();
  const { token } = useAuth();

  const classId = searchParams.get("classId") ?? "";
  const subjectId = searchParams.get("subjectId") ?? "";

  const [structure, setStructure] = useState<OrgStructure>({ classes: [] });
  const [topics, setTopics] = useState<TeacherTopicRecord[]>([]);
  const [topicsLoading, setTopicsLoading] = useState(false);
  const [topicsError, setTopicsError] = useState<string | null>(null);

  const [selectedTopic, setSelectedTopic] = useState<TeacherTopicRecord | null>(
    null
  );

  const [toast, setToast] = useState<{
    text: string;
    variant: "ok" | "err";
  } | null>(null);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const [curriculumImportOpen, setCurriculumImportOpen] = useState(false);
  const [createTopicOpen, setCreateTopicOpen] = useState(false);

  const showToast = useCallback(
    (message: string, variant: "ok" | "err" = "ok") => {
      if (toastTimer.current) clearTimeout(toastTimer.current);
      setToast({ text: message, variant });
      toastTimer.current = setTimeout(() => {
        setToast(null);
        toastTimer.current = null;
      }, 3800);
    },
    []
  );

  useEffect(() => {
    return () => {
      if (toastTimer.current) clearTimeout(toastTimer.current);
    };
  }, []);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    getOrgStructure(token)
      .then((s) => {
        if (!cancelled) setStructure(s);
      })
      .catch(() => {
        if (!cancelled) setStructure({ classes: [] });
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  const { classDisplayName, subjectDisplayName } = useMemo(() => {
    if (!classId || !subjectId) {
      return {
        classDisplayName: null as string | null,
        subjectDisplayName: null as string | null,
      };
    }
    for (const c of structure.classes) {
      if (c.id !== classId) continue;
      const sub = c.subjects.find((s) => s.id === subjectId);
      return {
        classDisplayName: c.name,
        subjectDisplayName: sub?.name ?? null,
      };
    }
    return {
      classDisplayName: null as string | null,
      subjectDisplayName: null as string | null,
    };
  }, [structure.classes, classId, subjectId]);

  /** Notes/questions are stored under the teacher topic row; concepts validated there */
  const contentStorageTopicId = selectedTopic?.id ?? null;

  const refreshTopics = useCallback(async () => {
    if (!token || !classId || !subjectId) {
      setTopics([]);
      return;
    }
    setTopicsLoading(true);
    setTopicsError(null);
    try {
      const rows = await getTeacherTopics(token, classId, subjectId);
      setTopics(rows);
    } catch (e) {
      setTopicsError(
        e instanceof Error ? e.message : "Failed to load teacher topics"
      );
      setTopics([]);
    } finally {
      setTopicsLoading(false);
    }
  }, [token, classId, subjectId]);

  const refreshStructure = useCallback(async () => {
    if (!token) return;
    try {
      const s = await getOrgStructure(token);
      setStructure(s);
    } catch {
      /* keep existing structure */
    }
  }, [token]);

  const handleCurriculumImported = useCallback(() => {
    void Promise.all([refreshStructure(), refreshTopics()]);
  }, [refreshStructure, refreshTopics]);

  useEffect(() => {
    void refreshTopics();
  }, [refreshTopics]);

  const contextMissing = !classId || !subjectId;

  const structuredCurriculumHref = selectedTopic
    ? `/teacher/workspace/curriculum/${selectedTopic.id}?${new URLSearchParams({
        classId,
        subjectId,
        topicName: selectedTopic.topic_name,
      }).toString()}`
    : null;

  const classroomPlanningHref = selectedTopic
    ? `/teacher/workspace/classroom?${new URLSearchParams({
        classId,
        subjectId,
        topicId: selectedTopic.id,
        topicName: selectedTopic.topic_name,
      }).toString()}`
    : null;

  function handleTopicCreated(row: TeacherTopicRecord) {
    setTopics((prev) => {
      const i = prev.findIndex((t) => t.id === row.id);
      if (i >= 0) {
        const next = [...prev];
        next[i] = row;
        return next;
      }
      return [...prev, row];
    });
  }

  function handleTopicUpdated(row: TeacherTopicRecord) {
    setTopics((prev) =>
      prev.map((t) => (t.id === row.id ? row : t))
    );
    setSelectedTopic((cur) => (cur?.id === row.id ? row : cur));
  }

  function handleTopicDeleted(topicId: string) {
    setTopics((prev) => prev.filter((t) => t.id !== topicId));
    setSelectedTopic((cur) => (cur?.id === topicId ? null : cur));
  }

  if (contextMissing) {
    return (
      <div className="mx-auto max-w-lg rounded-xl border border-slate-200 bg-white p-8 text-center shadow-sm dark:border-slate-800 dark:bg-slate-900">
        <h1 className="text-lg font-semibold text-slate-900 dark:text-slate-50">
          Teacher workspace
        </h1>
        <p className="mt-2 text-sm text-slate-600 dark:text-slate-400">
          Pick a class and subject from the teacher panel first.
        </p>
        <Link
          href="/teacher"
          className="mt-4 inline-block text-sm font-medium text-violet-600 hover:underline dark:text-violet-400"
        >
          Go to Teacher Panel
        </Link>
      </div>
    );
  }

  return (
    <div className="relative mx-auto max-w-[1600px]">
      {toast ? (
        <div
          className={cn(
            "fixed bottom-6 right-6 z-50 max-w-sm rounded-xl border px-4 py-3 text-sm shadow-lg",
            toast.variant === "err"
              ? "border-red-200 bg-red-50 text-red-900 dark:border-red-900 dark:bg-red-950/90 dark:text-red-100"
              : "border-slate-200 bg-white text-slate-900 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-50"
          )}
          role="status"
        >
          {toast.text}
        </div>
      ) : null}

      <CurriculumImportModal
        open={curriculumImportOpen}
        onOpenChange={setCurriculumImportOpen}
        token={token}
        classId={classId}
        subjectId={subjectId}
        onImported={handleCurriculumImported}
        onToast={showToast}
      />

      <header className="mb-6 flex flex-col gap-1 border-b border-slate-200/80 pb-4 dark:border-slate-800">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight text-slate-900 dark:text-slate-50">
              Content workspace
            </h1>
            <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
              {classDisplayName && subjectDisplayName ? (
                <>
                  <span className="font-medium text-slate-800 dark:text-slate-200">
                    {classDisplayName}
                  </span>
                  <span className="mx-1.5 text-slate-400">·</span>
                  <span>{subjectDisplayName}</span>
                </>
              ) : (
                "Loading context…"
              )}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-3 text-sm">
            <Button
              type="button"
              size="sm"
              onClick={() => setCreateTopicOpen(true)}
            >
              <Plus className="mr-1 size-4" />
              New topic
            </Button>
            <button
              type="button"
              onClick={() => setCurriculumImportOpen(true)}
              className="inline-flex items-center rounded-lg border border-violet-200 bg-violet-50 px-3 py-1.5 text-sm font-medium text-violet-800 shadow-sm transition hover:bg-violet-100 dark:border-violet-800 dark:bg-violet-950/40 dark:text-violet-200 dark:hover:bg-violet-950/70"
            >
              Import curriculum
            </button>
            <Link
              href="/teacher"
              className="text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-100"
            >
              Change class
            </Link>
          </div>
        </div>
      </header>

      {!topicsLoading && topics.length === 0 ? (
        <p className="mb-4 rounded-lg border border-violet-200 bg-violet-50/80 px-4 py-3 text-sm text-violet-950 dark:border-violet-900/50 dark:bg-violet-950/30 dark:text-violet-100">
          No topics yet. Use <span className="font-medium">New topic</span> to build
          structured curriculum from scratch (same workflow as admin), or{" "}
          <span className="font-medium">Import curriculum</span> to copy from the
          catalog.
        </p>
      ) : null}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-12 lg:gap-6">
        <div className="lg:col-span-3">
          <TopicPanel
            token={token}
            classId={classId}
            subjectId={subjectId}
            topics={topics}
            selectedTopic={selectedTopic}
            onSelectTopic={setSelectedTopic}
            onTopicCreated={handleTopicCreated}
            onTopicUpdated={handleTopicUpdated}
            onTopicDeleted={handleTopicDeleted}
            loading={topicsLoading}
            error={topicsError}
            onToast={showToast}
            openCreateForm={createTopicOpen}
            onOpenCreateFormChange={setCreateTopicOpen}
          />
        </div>
        <div className="lg:col-span-9">
          <ContentEditor
            token={token}
            topicId={contentStorageTopicId}
            hasSelectedTopic={Boolean(selectedTopic)}
            selectedTopic={selectedTopic}
            peerTopics={topics}
            onToast={showToast}
            structuredCurriculumHref={structuredCurriculumHref}
            classroomPlanningHref={classroomPlanningHref}
          />
        </div>
      </div>
    </div>
  );
}
