"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/hooks/useAuth";
import { Button } from "@/components/ui/button";
import { AdminLearningFlowPanel } from "@/components/admin/AdminLearningFlowPanel";
import { V2CurriculumWorkflowNav } from "@/components/curriculum/V2CurriculumWorkflowNav";
import { ensureV2CurriculumStarted } from "@/lib/api/curriculumStructure";
import {
  createAdminCatalogSubject,
  deleteAdminCatalogSubject,
  deleteAdminCatalogTopic,
  getAdminCatalogSubjects,
  getAdminCatalogTopics,
  updateAdminCatalogSubject,
  updateAdminCatalogTopic,
  createAdminCatalogTopic,
} from "@/lib/api";
import type { AdminCatalogSubject, AdminCatalogTopic } from "@/lib/types";
import { cn } from "@/lib/utils";
import {
  BookOpen,
  Layers,
  Loader2,
  Pencil,
  Plus,
  Trash2,
} from "lucide-react";

const GRADE_OPTIONS = [
  "K",
  "1",
  "2",
  "3",
  "4",
  "5",
  "6",
  "7",
  "8",
  "9",
  "10",
  "11",
  "12",
];

function groupSubjectsByGrade(subjects: AdminCatalogSubject[]): Map<string, AdminCatalogSubject[]> {
  const m = new Map<string, AdminCatalogSubject[]>();
  for (const s of subjects) {
    const g = s.grade.trim() || "Other";
    const list = m.get(g) ?? [];
    list.push(s);
    m.set(g, list);
  }
  for (const list of m.values()) {
    list.sort((a, b) => a.name.localeCompare(b.name));
  }
  return m;
}

export default function AdminCurriculumPage() {
  const router = useRouter();
  const { token, ready, user } = useAuth();
  const [subjects, setSubjects] = useState<AdminCatalogSubject[]>([]);
  const [topics, setTopics] = useState<AdminCatalogTopic[]>([]);
  const [loadingSubjects, setLoadingSubjects] = useState(true);
  const [loadingTopics, setLoadingTopics] = useState(false);
  const [selectedSubjectId, setSelectedSubjectId] = useState<string | null>(null);
  const [selectedTopic, setSelectedTopic] = useState<AdminCatalogTopic | null>(null);

  const [toast, setToast] = useState<{ msg: string; variant: "ok" | "err" } | null>(null);
  const showToast = useCallback((msg: string, variant: "ok" | "err" = "ok") => {
    setToast({ msg, variant });
    window.setTimeout(() => setToast(null), 3200);
  }, []);

  const loadSubjects = useCallback(async () => {
    if (!token || user?.role !== "admin") return;
    setLoadingSubjects(true);
    try {
      const list = await getAdminCatalogSubjects(token);
      setSubjects(list);
    } catch (e) {
      showToast(e instanceof Error ? e.message : "Failed to load subjects", "err");
    } finally {
      setLoadingSubjects(false);
    }
  }, [token, user?.role, showToast]);

  const loadTopics = useCallback(
    async (subjectId: string) => {
      if (!token) return;
      setLoadingTopics(true);
      try {
        const list = await getAdminCatalogTopics(token, subjectId);
        setTopics(list);
      } catch (e) {
        showToast(e instanceof Error ? e.message : "Failed to load topics", "err");
        setTopics([]);
      } finally {
        setLoadingTopics(false);
      }
    },
    [token, showToast]
  );

  useEffect(() => {
    if (!ready || !token || user?.role !== "admin") return;
    void loadSubjects();
  }, [ready, token, user?.role, loadSubjects]);

  useEffect(() => {
    if (!selectedSubjectId || !token) {
      setTopics([]);
      setSelectedTopic(null);
      return;
    }
    void loadTopics(selectedSubjectId);
  }, [selectedSubjectId, token, loadTopics]);

  const byGrade = useMemo(() => groupSubjectsByGrade(subjects), [subjects]);
  const gradeKeys = useMemo(() => {
    const ordered = GRADE_OPTIONS.filter((g) => byGrade.has(g));
    const rest = [...byGrade.keys()].filter((g) => !GRADE_OPTIONS.includes(g)).sort();
    return [...ordered, ...rest];
  }, [byGrade]);

  const selectedSubject = subjects.find((s) => s.id === selectedSubjectId) ?? null;

  // --- Subject modal ---
  const [subjectModalOpen, setSubjectModalOpen] = useState(false);
  const [subjectEditing, setSubjectEditing] = useState<AdminCatalogSubject | null>(null);
  const [subName, setSubName] = useState("");
  const [subGrade, setSubGrade] = useState("3");
  const [subBoard, setSubBoard] = useState("");
  const [subDesc, setSubDesc] = useState("");
  const [subSaving, setSubSaving] = useState(false);

  function openNewSubject() {
    setSubjectEditing(null);
    setSubName("");
    setSubGrade("3");
    setSubBoard("");
    setSubDesc("");
    setSubjectModalOpen(true);
  }

  function openEditSubject(s: AdminCatalogSubject) {
    setSubjectEditing(s);
    setSubName(s.name);
    setSubGrade(s.grade);
    setSubBoard(s.board);
    setSubDesc(s.description);
    setSubjectModalOpen(true);
  }

  async function saveSubject() {
    if (!token) return;
    const name = subName.trim();
    if (!name) {
      showToast("Subject name is required", "err");
      return;
    }
    if (!subGrade.trim()) {
      showToast("Grade is required", "err");
      return;
    }
    setSubSaving(true);
    try {
      if (subjectEditing) {
        await updateAdminCatalogSubject(token, subjectEditing.id, {
          name,
          grade: subGrade.trim(),
          board: subBoard.trim() || "General",
          description: subDesc.trim() || undefined,
          academic_year: subjectEditing.academic_year,
          curriculum_version: subjectEditing.curriculum_version,
          status: subjectEditing.status,
          is_active: subjectEditing.is_active,
        });
        showToast("Subject updated");
      } else {
        await createAdminCatalogSubject(token, {
          name,
          grade: subGrade.trim(),
          board: subBoard.trim() || undefined,
          description: subDesc.trim() || undefined,
        });
        showToast("Subject created");
      }
      setSubjectModalOpen(false);
      await loadSubjects();
    } catch (e) {
      showToast(e instanceof Error ? e.message : "Save failed", "err");
    } finally {
      setSubSaving(false);
    }
  }

  async function confirmDeleteSubject(s: AdminCatalogSubject) {
    if (!token) return;
    if (
      !confirm(
        `Delete subject "${s.name}" (${s.grade})? This will delete all topics and content under this subject.`
      )
    ) {
      return;
    }
    try {
      await deleteAdminCatalogSubject(token, s.id);
      showToast("Subject deleted");
      if (selectedSubjectId === s.id) {
        setSelectedSubjectId(null);
        setSelectedTopic(null);
      }
      await loadSubjects();
    } catch (e) {
      showToast(e instanceof Error ? e.message : "Delete failed", "err");
    }
  }

  // --- Topic modal ---
  const [topicModalOpen, setTopicModalOpen] = useState(false);
  const [topicEditing, setTopicEditing] = useState<AdminCatalogTopic | null>(null);
  const [topName, setTopName] = useState("");
  const [topDesc, setTopDesc] = useState("");
  const [topDiff, setTopDiff] = useState("medium");
  const [topDepth, setTopDepth] = useState("standard");
  const [topSaving, setTopSaving] = useState(false);

  function openNewTopic() {
    if (!selectedSubjectId) return;
    setTopicEditing(null);
    setTopName("");
    setTopDesc("Describe this topic (min 10 characters for the catalog).");
    setTopDiff("medium");
    setTopDepth("standard");
    setTopicModalOpen(true);
  }

  function openEditTopic(t: AdminCatalogTopic) {
    setTopicEditing(t);
    setTopName(t.topic_name);
    setTopDesc(t.topic_description);
    setTopDiff(t.difficulty_level);
    setTopDepth(t.default_depth);
    setTopicModalOpen(true);
  }

  async function saveTopic() {
    if (!token || !selectedSubjectId) return;
    const name = topName.trim();
    const desc = topDesc.trim();
    if (!name) {
      showToast("Topic name is required", "err");
      return;
    }
    if (desc.length < 10) {
      showToast("Description must be at least 10 characters", "err");
      return;
    }

    setTopSaving(true);
    try {
      if (topicEditing) {
        await updateAdminCatalogTopic(token, topicEditing.id, {
          topic_name: name,
          topic_slug: topicEditing.topic_slug,
          topic_description: desc,
          key_concepts: topicEditing.key_concepts ?? [],
          concept_clusters: topicEditing.concept_clusters ?? null,
          difficulty_level: topDiff,
          default_depth: topDepth,
          topic_order: topicEditing.topic_order,
          estimated_time: topicEditing.estimated_time,
          academic_year: "2024",
          curriculum_version: "v2",
          status: topicEditing.status,
          is_active: topicEditing.is_active,
        });
        showToast("Topic updated");
        setTopicModalOpen(false);
        const list = await getAdminCatalogTopics(token, selectedSubjectId);
        setTopics(list);
        const u = list.find((x) => x.id === topicEditing.id);
        if (u) setSelectedTopic(u);
      } else {
        const created = await createAdminCatalogTopic(token, {
          subject_id: selectedSubjectId,
          topic_name: name,
          topic_description: desc,
          key_concepts: [],
          concept_clusters: null,
          difficulty_level: topDiff,
          default_depth: topDepth,
          curriculum_version: "v2",
        });
        await ensureV2CurriculumStarted(token, created.id, "catalog");
        showToast("Topic created");
        setTopicModalOpen(false);
        router.push(`/admin/curriculum/builder/${created.id}`);
      }
    } catch (e) {
      showToast(e instanceof Error ? e.message : "Save failed", "err");
    } finally {
      setTopSaving(false);
    }
  }

  async function confirmDeleteTopic(t: AdminCatalogTopic) {
    if (!token) return;
    if (
      !confirm(
        `Delete topic "${t.topic_name}"? This will delete structured curriculum and session plans under this topic.`
      )
    ) {
      return;
    }
    try {
      await deleteAdminCatalogTopic(token, t.id);
      showToast("Topic deleted");
      if (selectedTopic?.id === t.id) setSelectedTopic(null);
      if (selectedSubjectId) await loadTopics(selectedSubjectId);
    } catch (e) {
      showToast(e instanceof Error ? e.message : "Delete failed", "err");
    }
  }

  if (!ready || user?.role !== "admin") {
    return (
      <div className="mx-auto max-w-4xl text-sm text-slate-500">
        {!ready ? "Loading…" : "Admin only."}
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-[1400px] space-y-6">
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

      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900 dark:text-slate-50">
            Curriculum builder
          </h1>
          <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
            Global catalog — structured curriculum and session planning for every topic.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button type="button" variant="outline" asChild>
            <Link href="/admin">Back to admin</Link>
          </Button>
          <Button type="button" onClick={() => void openNewSubject()}>
            <Plus className="mr-1 size-4" />
            New subject
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
        <aside className="lg:col-span-3">
          <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900">
            <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-800 dark:text-slate-100">
              <Layers className="size-4 opacity-70" />
              Subjects by grade
            </div>
            {loadingSubjects ? (
              <p className="flex items-center gap-2 text-sm text-slate-500">
                <Loader2 className="size-4 animate-spin" /> Loading…
              </p>
            ) : subjects.length === 0 ? (
              <p className="text-sm text-slate-500">No global subjects yet. Create one.</p>
            ) : (
              <div className="custom-scrollbar max-h-[min(70vh,640px)] space-y-4 overflow-y-auto pr-1">
                {gradeKeys.map((grade) => (
                  <div key={grade}>
                    <p className="mb-2 text-xs font-bold uppercase tracking-wide text-slate-400">
                      Grade {grade}
                    </p>
                    <ul className="space-y-1">
                      {(byGrade.get(grade) ?? []).map((s) => (
                        <li key={s.id}>
                          <div
                            className={cn(
                              "flex items-center gap-1 rounded-lg border px-2 py-1.5 text-sm transition",
                              selectedSubjectId === s.id
                                ? "border-violet-300 bg-violet-50 dark:border-violet-700 dark:bg-violet-950/40"
                                : "border-transparent hover:bg-slate-50 dark:hover:bg-slate-800/60"
                            )}
                          >
                            <button
                              type="button"
                              className="min-w-0 flex-1 truncate text-left font-medium text-slate-800 dark:text-slate-100"
                              onClick={() => {
                                setSelectedSubjectId(s.id);
                                setSelectedTopic(null);
                              }}
                            >
                              {s.name}
                            </button>
                            <button
                              type="button"
                              className="rounded p-1 text-slate-500 hover:bg-slate-200 dark:hover:bg-slate-700"
                              title="Edit"
                              onClick={() => openEditSubject(s)}
                            >
                              <Pencil className="size-3.5" />
                            </button>
                            <button
                              type="button"
                              className="rounded p-1 text-red-500 hover:bg-red-50 dark:hover:bg-red-950/50"
                              title="Delete"
                              onClick={() => void confirmDeleteSubject(s)}
                            >
                              <Trash2 className="size-3.5" />
                            </button>
                          </div>
                        </li>
                      ))}
                    </ul>
                  </div>
                ))}
              </div>
            )}
          </div>
        </aside>

        <section className="lg:col-span-4">
          <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2 text-sm font-semibold text-slate-800 dark:text-slate-100">
                <BookOpen className="size-4 opacity-70" />
                Topics
                {selectedSubject ? (
                  <span className="font-normal text-slate-500">· {selectedSubject.name}</span>
                ) : null}
              </div>
              <Button
                type="button"
                size="sm"
                variant="secondary"
                disabled={!selectedSubjectId}
                onClick={() => openNewTopic()}
              >
                <Plus className="mr-1 size-3.5" />
                New topic
              </Button>
            </div>
            {!selectedSubjectId ? (
              <p className="text-sm text-slate-500">Select a subject to view topics.</p>
            ) : loadingTopics ? (
              <p className="flex items-center gap-2 text-sm text-slate-500">
                <Loader2 className="size-4 animate-spin" /> Loading topics…
              </p>
            ) : topics.length === 0 ? (
              <p className="text-sm text-slate-500">No topics yet for this subject.</p>
            ) : (
              <ul className="custom-scrollbar max-h-[min(70vh,640px)] space-y-2 overflow-y-auto pr-1">
                {topics.map((t) => (
                  <li key={t.id}>
                    <div
                      className={cn(
                        "rounded-xl border p-3 shadow-sm transition",
                        selectedTopic?.id === t.id
                          ? "border-violet-400 bg-violet-50/80 dark:border-violet-600 dark:bg-violet-950/30"
                          : "border-slate-200 bg-slate-50/50 dark:border-slate-700 dark:bg-slate-800/40"
                      )}
                    >
                      <button
                        type="button"
                        className="w-full text-left"
                        onClick={() => setSelectedTopic(t)}
                      >
                        <p className="font-medium text-slate-900 dark:text-slate-50">{t.topic_name}</p>
                        <p className="mt-1 line-clamp-2 text-xs text-slate-600 dark:text-slate-400">
                          {t.topic_description}
                        </p>
                        <p className="mt-2 text-xs text-slate-500">
                          {t.difficulty_level} · {t.default_depth}
                        </p>
                      </button>
                      <div className="mt-2 flex flex-wrap gap-2 border-t border-slate-200/80 pt-2 dark:border-slate-700">
                        <Button type="button" variant="secondary" size="sm" className="h-8" asChild>
                          <Link href={`/admin/curriculum/builder/${t.id}`}>
                            Open Structured Curriculum
                          </Link>
                        </Button>
                        <Button type="button" variant="secondary" size="sm" className="h-8" asChild>
                          <Link
                            href={`/admin/curriculum/planning/${t.id}?topicName=${encodeURIComponent(t.topic_name)}`}
                          >
                            Session Planning
                          </Link>
                        </Button>
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          className="h-8"
                          onClick={() => openEditTopic(t)}
                        >
                          Edit
                        </Button>
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          className="h-8 text-red-600"
                          onClick={() => void confirmDeleteTopic(t)}
                        >
                          Delete
                        </Button>
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </section>

        <section className="lg:col-span-5">
          <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900">
            {!selectedTopic ? (
              <p className="text-center text-sm text-slate-500">
                Select a topic to view learning flow, or create a new topic to open the structured
                curriculum builder.
              </p>
            ) : (
              <>
                <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-50">
                  {selectedTopic.topic_name}
                </h2>
                <p className="mt-1 text-xs text-slate-500">Slug: {selectedTopic.topic_slug}</p>

                <V2CurriculumWorkflowNav
                  className="mt-4"
                  topicName={selectedTopic.topic_name}
                  builderHref={`/admin/curriculum/builder/${selectedTopic.id}`}
                  planningHref={`/admin/curriculum/planning/${selectedTopic.id}?topicName=${encodeURIComponent(selectedTopic.topic_name)}`}
                  active="learningFlow"
                />

                <p className="mt-4 text-xs font-medium text-slate-500 dark:text-slate-400">
                  Learning flow — prerequisites and topic progression
                </p>

                <div className="mt-4">
                  {token ? (
                    <AdminLearningFlowPanel
                      token={token}
                      topicId={selectedTopic.id}
                      sameSubjectTopics={topics}
                      subjectGrade={selectedSubject?.grade ?? ""}
                      onToast={showToast}
                    />
                  ) : null}
                </div>
              </>
            )}
          </div>
        </section>
      </div>

      {subjectModalOpen && (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/40 p-4">
          <div className="max-h-[90vh] w-full max-w-md overflow-y-auto rounded-xl border border-slate-200 bg-white p-6 shadow-xl dark:border-slate-700 dark:bg-slate-900">
            <h3 className="text-lg font-semibold text-slate-900 dark:text-slate-50">
              {subjectEditing ? "Edit subject" : "New subject"}
            </h3>
            <div className="mt-4 space-y-3">
              <label className="block text-xs font-medium text-slate-600 dark:text-slate-400">
                Name *
                <input
                  value={subName}
                  onChange={(e) => setSubName(e.target.value)}
                  className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm dark:border-slate-600 dark:bg-slate-950"
                />
              </label>
              <label className="block text-xs font-medium text-slate-600 dark:text-slate-400">
                Grade *
                <select
                  value={subGrade}
                  onChange={(e) => setSubGrade(e.target.value)}
                  className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm dark:border-slate-600 dark:bg-slate-950"
                >
                  {GRADE_OPTIONS.map((g) => (
                    <option key={g} value={g}>
                      Grade {g}
                    </option>
                  ))}
                </select>
              </label>
              <label className="block text-xs font-medium text-slate-600 dark:text-slate-400">
                Board (optional)
                <input
                  value={subBoard}
                  onChange={(e) => setSubBoard(e.target.value)}
                  placeholder="General"
                  className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm dark:border-slate-600 dark:bg-slate-950"
                />
              </label>
              <label className="block text-xs font-medium text-slate-600 dark:text-slate-400">
                Description (optional, min 10 chars if set)
                <textarea
                  value={subDesc}
                  onChange={(e) => setSubDesc(e.target.value)}
                  rows={3}
                  className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm dark:border-slate-600 dark:bg-slate-950"
                />
              </label>
            </div>
            <div className="mt-6 flex justify-end gap-2">
              <Button type="button" variant="outline" onClick={() => setSubjectModalOpen(false)}>
                Cancel
              </Button>
              <Button type="button" disabled={subSaving} onClick={() => void saveSubject()}>
                {subSaving ? "Saving…" : "Save"}
              </Button>
            </div>
          </div>
        </div>
      )}

      {topicModalOpen && (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/40 p-4">
          <div className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-xl border border-slate-200 bg-white p-6 shadow-xl dark:border-slate-700 dark:bg-slate-900">
            <h3 className="text-lg font-semibold text-slate-900 dark:text-slate-50">
              {topicEditing ? "Edit topic" : "New topic"}
            </h3>
            <p className="mt-2 text-xs text-slate-500">
              {topicEditing
                ? "Update topic metadata. Concepts are managed in structured curriculum."
                : "After save you will open the structured curriculum builder."}
            </p>
            <div className="mt-4 space-y-3">
              <label className="block text-xs font-medium text-slate-600 dark:text-slate-400">
                Topic name *
                <input
                  value={topName}
                  onChange={(e) => setTopName(e.target.value)}
                  className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm dark:border-slate-600 dark:bg-slate-950"
                />
              </label>
              <label className="block text-xs font-medium text-slate-600 dark:text-slate-400">
                Description * (≥10 chars)
                <textarea
                  value={topDesc}
                  onChange={(e) => setTopDesc(e.target.value)}
                  rows={4}
                  className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm dark:border-slate-600 dark:bg-slate-950"
                />
              </label>
              <div className="grid grid-cols-2 gap-3">
                <label className="block text-xs font-medium text-slate-600 dark:text-slate-400">
                  Difficulty
                  <select
                    value={topDiff}
                    onChange={(e) => setTopDiff(e.target.value)}
                    className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm dark:border-slate-600 dark:bg-slate-950"
                  >
                    <option value="basic">basic</option>
                    <option value="medium">medium</option>
                    <option value="hard">hard</option>
                  </select>
                </label>
                <label className="block text-xs font-medium text-slate-600 dark:text-slate-400">
                  Default depth
                  <input
                    value={topDepth}
                    onChange={(e) => setTopDepth(e.target.value)}
                    className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm dark:border-slate-600 dark:bg-slate-950"
                  />
                </label>
              </div>
            </div>
            <div className="mt-6 flex justify-end gap-2">
              <Button type="button" variant="outline" onClick={() => setTopicModalOpen(false)}>
                Cancel
              </Button>
              <Button type="button" disabled={topSaving} onClick={() => void saveTopic()}>
                {topSaving ? "Saving…" : "Save"}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
