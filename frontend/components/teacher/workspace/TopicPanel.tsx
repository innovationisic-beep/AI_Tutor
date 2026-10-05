"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Check, Pencil, Plus, Trash2, X } from "lucide-react";
import type { TeacherTopicRecord } from "@/lib/types";
import {
  createTeacherTopic,
  deleteTeacherTopic,
  updateTeacherTopic,
} from "@/lib/api";
import { ensureV2CurriculumStarted } from "@/lib/api/curriculumStructure";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type TopicPanelProps = {
  token: string | null;
  classId: string;
  subjectId: string;
  topics: TeacherTopicRecord[];
  selectedTopic: TeacherTopicRecord | null;
  onSelectTopic: (t: TeacherTopicRecord) => void;
  onTopicCreated: (t: TeacherTopicRecord) => void;
  onTopicUpdated: (t: TeacherTopicRecord) => void;
  onTopicDeleted: (topicId: string) => void;
  loading: boolean;
  error: string | null;
  onToast: (message: string, variant?: "ok" | "err") => void;
  /** When true, show the new-topic form (controlled from workspace header). */
  openCreateForm?: boolean;
  onOpenCreateFormChange?: (open: boolean) => void;
};

function builderHref(
  topic: TeacherTopicRecord,
  classId: string,
  subjectId: string
): string {
  return `/teacher/workspace/curriculum/${topic.id}?${new URLSearchParams({
    classId,
    subjectId,
    topicName: topic.topic_name,
  }).toString()}`;
}

function planningHref(
  topic: TeacherTopicRecord,
  classId: string,
  subjectId: string
): string {
  return `/teacher/workspace/classroom?${new URLSearchParams({
    classId,
    subjectId,
    topicId: topic.id,
    topicName: topic.topic_name,
  }).toString()}`;
}

export function TopicPanel({
  token,
  classId,
  subjectId,
  topics,
  selectedTopic,
  onSelectTopic,
  onTopicCreated,
  onTopicUpdated,
  onTopicDeleted,
  loading,
  error,
  onToast,
  openCreateForm,
  onOpenCreateFormChange,
}: TopicPanelProps) {
  const router = useRouter();
  const [expanded, setExpanded] = useState(false);
  const [name, setName] = useState("");
  const [creating, setCreating] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editName, setEditName] = useState("");
  const [savingEditId, setSavingEditId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const setCreateFormOpen = (open: boolean) => {
    setExpanded(open);
    onOpenCreateFormChange?.(open);
  };

  useEffect(() => {
    if (openCreateForm) setExpanded(true);
  }, [openCreateForm]);

  useEffect(() => {
    if (!loading && topics.length === 0) setExpanded(true);
  }, [loading, topics.length, classId, subjectId]);

  async function handleCreate() {
    const trimmed = name.trim();
    if (!token || !trimmed) return;
    setCreating(true);
    try {
      const row = await createTeacherTopic(token, {
        class_id: classId,
        subject_id: subjectId,
        topic_name: trimmed,
      });
      await ensureV2CurriculumStarted(token, row.id, "teacher");
      onTopicCreated(row);
      onSelectTopic(row);
      setName("");
      setCreateFormOpen(false);
      onToast("Topic created");
      router.push(builderHref(row, classId, subjectId));
    } catch (e) {
      onToast(e instanceof Error ? e.message : "Failed to create topic", "err");
    } finally {
      setCreating(false);
    }
  }

  async function saveEdit(topicId: string) {
    const trimmed = editName.trim();
    if (!token || !trimmed) {
      onToast("Topic name is required", "err");
      return;
    }
    setSavingEditId(topicId);
    try {
      const row = await updateTeacherTopic(token, topicId, {
        topic_name: trimmed,
      });
      onTopicUpdated(row);
      setEditingId(null);
      onToast("Topic updated");
    } catch (e) {
      onToast(e instanceof Error ? e.message : "Failed to update topic", "err");
    } finally {
      setSavingEditId(null);
    }
  }

  async function handleDelete(topic: TeacherTopicRecord) {
    if (!token) return;
    if (
      !window.confirm(
        `Delete topic "${topic.topic_name}"? Structured curriculum and session plans for this topic may become unreachable.`
      )
    ) {
      return;
    }
    setDeletingId(topic.id);
    try {
      await deleteTeacherTopic(token, topic.id);
      onTopicDeleted(topic.id);
      if (editingId === topic.id) {
        setEditingId(null);
        setEditName("");
      }
      onToast("Topic deleted");
    } catch (e) {
      onToast(e instanceof Error ? e.message : "Failed to delete topic", "err");
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <div className="flex min-h-[280px] flex-col rounded-xl border border-slate-200/90 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900 md:min-h-[420px]">
      <div className="mb-3 flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
          Topics
        </h2>
        <button
          type="button"
          onClick={() => setCreateFormOpen(!expanded)}
          className="inline-flex items-center gap-1 rounded-lg bg-slate-900 px-2.5 py-1.5 text-xs font-medium text-white shadow-sm transition hover:bg-slate-800 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-slate-200"
        >
          <Plus className="size-3.5" />
          New Topic
        </button>
      </div>

      {expanded ? (
        <div className="mb-3 flex flex-col gap-2 rounded-lg border border-slate-200 bg-slate-50/80 p-3 dark:border-slate-700 dark:bg-slate-800/50">
          <label className="text-xs font-medium text-slate-600 dark:text-slate-400">
            Topic name
          </label>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Photosynthesis"
            className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-100"
            onKeyDown={(e) => {
              if (e.key === "Enter") void handleCreate();
            }}
          />
          <p className="text-xs text-slate-500">
            New topics open the structured curriculum builder immediately.
          </p>
          <div className="flex gap-2">
            <button
              type="button"
              disabled={creating || !name.trim() || !token}
              onClick={() => void handleCreate()}
              className="rounded-lg bg-slate-900 px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50 dark:bg-slate-100 dark:text-slate-900"
            >
              {creating ? "Creating…" : "Create"}
            </button>
            <button
              type="button"
              onClick={() => {
                setCreateFormOpen(false);
                setName("");
              }}
              className="rounded-lg px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-800"
            >
              Cancel
            </button>
          </div>
        </div>
      ) : null}

      {error ? (
        <p className="mb-2 text-xs text-red-600 dark:text-red-400">{error}</p>
      ) : null}
      {loading ? (
        <p className="text-sm text-slate-500">Loading topics…</p>
      ) : topics.length === 0 ? (
        <p className="py-6 text-center text-sm text-slate-500 dark:text-slate-400">
          No topics yet. Create one to start structured curriculum.
        </p>
      ) : (
        <ul className="flex flex-1 flex-col gap-2 overflow-y-auto">
          {topics.map((t) => {
            const active = selectedTopic?.id === t.id;
            const editing = editingId === t.id;
            return (
              <li
                key={t.id}
                className={cn(
                  "rounded-lg border transition",
                  active
                    ? "border-slate-300 bg-slate-100 shadow-sm dark:border-slate-600 dark:bg-slate-800"
                    : "border-slate-200 bg-slate-50/50 dark:border-slate-700 dark:bg-slate-800/40"
                )}
              >
                {editing ? (
                  <div className="flex min-w-0 flex-wrap items-center gap-1 px-2 py-2">
                    <input
                      value={editName}
                      onChange={(e) => setEditName(e.target.value)}
                      className="min-w-0 flex-1 rounded-md border border-slate-200 bg-white px-2 py-1 text-sm dark:border-slate-600 dark:bg-slate-900 dark:text-slate-100"
                      autoFocus
                      onKeyDown={(e) => {
                        if (e.key === "Enter") void saveEdit(t.id);
                        if (e.key === "Escape") {
                          setEditingId(null);
                          setEditName("");
                        }
                      }}
                    />
                    <button
                      type="button"
                      disabled={savingEditId === t.id || !editName.trim()}
                      onClick={() => void saveEdit(t.id)}
                      className="rounded-md p-1.5 text-emerald-700 hover:bg-emerald-50 disabled:opacity-50 dark:text-emerald-400 dark:hover:bg-emerald-950/50"
                      aria-label="Save topic name"
                    >
                      <Check className="size-4" />
                    </button>
                    <button
                      type="button"
                      disabled={savingEditId === t.id}
                      onClick={() => {
                        setEditingId(null);
                        setEditName("");
                      }}
                      className="rounded-md p-1.5 text-slate-600 hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-800"
                      aria-label="Cancel edit"
                    >
                      <X className="size-4" />
                    </button>
                  </div>
                ) : (
                  <>
                    <button
                      type="button"
                      onClick={() => onSelectTopic(t)}
                      className={cn(
                        "w-full px-3 py-2.5 text-left text-sm font-medium transition",
                        active
                          ? "text-slate-900 dark:text-slate-50"
                          : "text-slate-700 dark:text-slate-300"
                      )}
                    >
                      {t.topic_name}
                    </button>
                    <div className="flex flex-wrap gap-2 border-t border-slate-200/80 px-2 py-2 dark:border-slate-700">
                      <Button type="button" variant="secondary" size="sm" className="h-8" asChild>
                        <Link href={builderHref(t, classId, subjectId)}>
                          Open Structured Curriculum
                        </Link>
                      </Button>
                      <Button type="button" variant="secondary" size="sm" className="h-8" asChild>
                        <Link href={planningHref(t, classId, subjectId)}>
                          Session Planning
                        </Link>
                      </Button>
                    </div>
                    <div className="flex justify-end gap-0.5 px-2 pb-2 opacity-100 sm:opacity-60">
                      <button
                        type="button"
                        disabled={!token || deletingId === t.id}
                        onClick={() => {
                          setEditingId(t.id);
                          setEditName(t.topic_name);
                        }}
                        className="rounded-md p-1.5 text-slate-500 hover:bg-slate-200/80 hover:text-slate-900 disabled:opacity-50 dark:hover:bg-slate-700 dark:hover:text-slate-100"
                        aria-label="Edit topic name"
                      >
                        <Pencil className="size-3.5" />
                      </button>
                      <button
                        type="button"
                        disabled={!token || deletingId === t.id}
                        onClick={() => void handleDelete(t)}
                        className="rounded-md p-1.5 text-red-600 hover:bg-red-50 disabled:opacity-50 dark:text-red-400 dark:hover:bg-red-950/40"
                        aria-label="Delete topic"
                      >
                        <Trash2 className="size-3.5" />
                      </button>
                    </div>
                  </>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
