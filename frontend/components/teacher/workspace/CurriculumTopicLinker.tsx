"use client";

import { useCallback, useEffect, useState } from "react";
import { Download, Link2 } from "lucide-react";
import type { TeacherTopicRecord, Topic } from "@/lib/types";
import { getTopics, linkTeacherTopicToCurriculum } from "@/lib/api";

type CurriculumTopicLinkerProps = {
  token: string | null;
  selectedTopic: TeacherTopicRecord | null;
  curriculumSubjectId: string | null;
  onLinked: (row: TeacherTopicRecord) => void;
  onToast: (message: string, variant?: "ok" | "err") => void;
};

export function CurriculumTopicLinker({
  token,
  selectedTopic,
  curriculumSubjectId,
  onLinked,
  onToast,
}: CurriculumTopicLinkerProps) {
  const [topics, setTopics] = useState<Topic[]>([]);
  const [loading, setLoading] = useState(false);
  const [pick, setPick] = useState("");
  const [linking, setLinking] = useState(false);
  const [importOpen, setImportOpen] = useState(false);

  const loadTopics = useCallback(async () => {
    if (!token || !curriculumSubjectId) {
      setTopics([]);
      return;
    }
    setLoading(true);
    try {
      const list = await getTopics(token, curriculumSubjectId);
      setTopics(list);
    } catch {
      setTopics([]);
      onToast("Could not load curriculum topics", "err");
    } finally {
      setLoading(false);
    }
  }, [token, curriculumSubjectId, onToast]);

  useEffect(() => {
    void loadTopics();
  }, [loadTopics]);

  useEffect(() => {
    setPick("");
    setImportOpen(false);
  }, [selectedTopic?.id]);

  const effectiveTopicId =
    pick || (topics.length > 0 ? topics[0].id : "");

  if (!selectedTopic) {
    return null;
  }

  if (selectedTopic.curriculum_topic_id) {
    return (
      <div className="mb-4 flex items-center gap-2 rounded-xl border border-emerald-200/80 bg-emerald-50/60 px-4 py-3 text-sm text-emerald-900 shadow-sm dark:border-emerald-900/50 dark:bg-emerald-950/30 dark:text-emerald-100">
        <Link2 className="size-4 shrink-0 opacity-80" aria-hidden />
        <span>
          Linked to admin curriculum topic{" "}
          <code className="rounded bg-white/80 px-1.5 py-0.5 text-xs dark:bg-emerald-900/50">
            {String(selectedTopic.curriculum_topic_id).slice(0, 12)}…
          </code>
          — notes and questions can also use this catalog id when you create content.
        </span>
      </div>
    );
  }

  return (
    <div className="mb-4 rounded-xl border border-slate-200 bg-slate-50/40 p-4 shadow-sm dark:border-slate-700 dark:bg-slate-900/50">
      <p className="text-sm text-slate-700 dark:text-slate-300">
        Admin curriculum is <span className="font-medium">optional</span>. Your
        topics and content work without it.
      </p>
      {!curriculumSubjectId ? (
        <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">
          When your organization links this class subject to the curriculum catalog,
          you can import matching admin topics here as a shortcut.
        </p>
      ) : (
        <div className="mt-3">
          <button
            type="button"
            onClick={() => setImportOpen((o) => !o)}
            className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-800 shadow-sm transition hover:bg-slate-50 dark:border-slate-600 dark:bg-slate-950 dark:text-slate-100 dark:hover:bg-slate-900"
          >
            <Download className="size-4 opacity-70" aria-hidden />
            {importOpen ? "Hide import" : "Import from Admin Curriculum"}
          </button>
          {importOpen ? (
            <div className="mt-4 rounded-lg border border-slate-200 bg-white p-3 dark:border-slate-600 dark:bg-slate-950">
              <p className="mb-3 text-xs text-slate-600 dark:text-slate-400">
                Pick an admin topic to attach for suggestions and alignment. Structured
                curriculum is edited in the workspace builder.
              </p>
              {loading ? (
                <p className="text-xs text-slate-500">Loading curriculum topics…</p>
              ) : topics.length === 0 ? (
                <p className="text-center text-xs text-slate-500">
                  No admin topics in this subject yet.
                </p>
              ) : (
                <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
                  <label className="flex min-w-0 flex-1 flex-col gap-1">
                    <span className="text-xs font-medium text-slate-600 dark:text-slate-400">
                      Admin topic
                    </span>
                    <select
                      value={effectiveTopicId}
                      onChange={(e) => setPick(e.target.value)}
                      className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm shadow-sm dark:border-slate-600 dark:bg-slate-950 dark:text-slate-100"
                    >
                      {topics.map((t) => (
                        <option key={t.id} value={t.id}>
                          {t.topic_name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <button
                    type="button"
                    disabled={linking || !effectiveTopicId || !token}
                    onClick={async () => {
                      if (!token || !effectiveTopicId) return;
                      setLinking(true);
                      try {
                        const row = await linkTeacherTopicToCurriculum(
                          token,
                          selectedTopic.id,
                          effectiveTopicId
                        );
                        onLinked(row);
                        onToast("Linked to admin curriculum topic");
                        setImportOpen(false);
                      } catch (e) {
                        onToast(
                          e instanceof Error ? e.message : "Link failed",
                          "err"
                        );
                      } finally {
                        setLinking(false);
                      }
                    }}
                    className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white shadow-sm transition hover:bg-slate-800 disabled:opacity-50 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-slate-200"
                  >
                    {linking ? "Linking…" : "Use this admin topic"}
                  </button>
                </div>
              )}
            </div>
          ) : null}
        </div>
      )}
    </div>
  );
}
