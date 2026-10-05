"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { getTopicCurriculumTree } from "@/lib/api/curriculumStructure";
import {
  createClassSessionInstance,
  createClassSessionPlan,
  archiveClassSessionPlan,
  enrollWholeClass,
  listClassSessionInstances,
  listClassSessionPlans,
  publishClassSessionPlan,
  setClassSessionPlanItems,
  startClassSessionInstance,
  unpublishClassSessionPlan,
  validateClassSessionPlan,
} from "@/lib/api/classroom";
import {
  createCatalogSessionPlan,
  deleteCatalogSessionPlan,
  listCatalogSessionPlans,
  publishCatalogSessionPlan,
  setCatalogSessionPlanItems,
  unpublishCatalogSessionPlan,
  validateCatalogSessionPlan,
} from "@/lib/api/catalogClassroom";
import type { ClassSessionInstance, ClassSessionPlan } from "@/lib/types/classroom";
import type { CurriculumTree, CurriculumZone } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Calendar, Loader2, Plus } from "lucide-react";
import { SessionIntroductionEditor } from "@/components/classroom/SessionIntroductionEditor";

const ZONE_LABELS: Record<number, string> = {
  0: "Curiosity",
  1: "Core Teaching",
  2: "Extension 1",
  3: "Extension 2",
  4: "Extension 3",
};

type ClassroomPlanningPanelProps = {
  token: string;
  teacherTopicId: string;
  classId: string;
  subjectId: string;
  topicName: string;
  curriculumBuilderHref: string;
  onToast: (message: string, variant?: "ok" | "err") => void;
  /** catalog = admin independent-student session plans */
  planScope?: "teacher" | "catalog";
};

export function ClassroomPlanningPanel({
  token,
  teacherTopicId,
  classId,
  subjectId,
  topicName,
  curriculumBuilderHref,
  onToast,
  planScope = "teacher",
}: ClassroomPlanningPanelProps) {
  const isCatalog = planScope === "catalog";
  const topicSource = isCatalog ? "catalog" : "teacher";
  const [tab, setTab] = useState<"plans" | "calendar">("plans");
  const [tree, setTree] = useState<CurriculumTree | null>(null);
  const [plans, setPlans] = useState<ClassSessionPlan[]>([]);
  const [instances, setInstances] = useState<ClassSessionInstance[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [selectedPlanId, setSelectedPlanId] = useState<string | null>(null);
  const [validationErrors, setValidationErrors] = useState<string[]>([]);
  const [planModalOpen, setPlanModalOpen] = useState(false);
  const [planTitle, setPlanTitle] = useState("");
  const [planSequence, setPlanSequence] = useState("1");
  const [scheduleModalOpen, setScheduleModalOpen] = useState(false);
  const [scheduleDate, setScheduleDate] = useState(new Date().toISOString().slice(0, 10));
  const [scheduleTime, setScheduleTime] = useState("09:00");
  const [scheduleDuration, setScheduleDuration] = useState("60");

  const readiness = useMemo(() => {
    if (!tree) {
      return {
        v2: false,
        published: false,
        classSessions: false,
        ready: false,
      };
    }
    // Once class sessions have been enabled (first curriculum publish), teachers/admins
    // must keep editing session plans even if curriculum is later demoted to draft.
    const classSessionsEnabled =
      Boolean(tree.supports_class_sessions) ||
      (tree.curriculum_schema_version === "v2" && Boolean(tree.curriculum_published_at));

    return {
      v2: tree.curriculum_schema_version === "v2",
      published: Boolean(tree.curriculum_published_at),
      classSessions: classSessionsEnabled,
      ready: tree.curriculum_schema_version === "v2" && classSessionsEnabled,
    };
  }, [tree]);

  const selectedPlan = useMemo(
    () => plans.find((p) => p.id === selectedPlanId) ?? null,
    [plans, selectedPlanId]
  );

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const treePromise = getTopicCurriculumTree(token, teacherTopicId, topicSource);
      const plansPromise = isCatalog
        ? listCatalogSessionPlans(token, teacherTopicId)
        : listClassSessionPlans(token, {
            teacher_topic_id: teacherTopicId,
            class_id: classId,
          });
      const instancesPromise = isCatalog
        ? Promise.resolve([] as ClassSessionInstance[])
        : listClassSessionInstances(token, { class_id: classId }).catch((err) => {
            // Calendar load must not block Session plans editing.
            console.warn("Failed to load class session instances", err);
            return [] as ClassSessionInstance[];
          });

      const [t, p, i] = await Promise.all([treePromise, plansPromise, instancesPromise]);
      setTree(t);
      setPlans(p);
      setInstances(i);
      if (!selectedPlanId && p.length > 0) setSelectedPlanId(p[0].id);
    } catch (e) {
      onToast(e instanceof Error ? e.message : "Failed to load classroom data", "err");
    } finally {
      setLoading(false);
    }
  }, [token, teacherTopicId, classId, onToast, selectedPlanId, isCatalog, topicSource]);

  useEffect(() => {
    void load();
  }, [load]);

  const sortedZones = useMemo(
    () => [...(tree?.zones ?? [])].sort((a, b) => a.zone_number - b.zone_number),
    [tree]
  );

  async function handleCreatePlan() {
    const title = planTitle.trim();
    const sequence_number = Number(planSequence);
    if (!title) {
      onToast("Plan title is required", "err");
      return;
    }
    if (!Number.isFinite(sequence_number) || sequence_number < 1) {
      onToast("Invalid sequence number", "err");
      return;
    }
    setBusy(true);
    try {
      const plan = isCatalog
        ? await createCatalogSessionPlan(token, {
            catalog_topic_id: teacherTopicId,
            sequence_number,
            title,
          })
        : await createClassSessionPlan(token, {
            teacher_topic_id: teacherTopicId,
            class_id: classId,
            subject_id: subjectId,
            sequence_number,
            title,
          });
      onToast("Plan created");
      setPlanModalOpen(false);
      setPlanTitle("");
      setPlanSequence("1");
      setSelectedPlanId(plan.id);
      await load();
    } catch (e) {
      onToast(e instanceof Error ? e.message : "Create failed", "err");
    } finally {
      setBusy(false);
    }
  }

  async function persistPlanItems(
    items: Parameters<typeof setClassSessionPlanItems>[2]
  ) {
    if (!selectedPlan) return;
    const updated = isCatalog
      ? await setCatalogSessionPlanItems(token, selectedPlan.id, items)
      : await setClassSessionPlanItems(token, selectedPlan.id, items);
    setPlans((prev) => prev.map((p) => (p.id === updated.id ? updated : p)));
  }

  async function removePlanItem(itemId: string) {
    if (!selectedPlan) return;
    setBusy(true);
    try {
      const plan = await ensurePlanIsDraft();
      if (!plan) return;
      const items = plan.items
        .filter((it) => it.item_id !== itemId)
        .map((it, idx) => ({
          item_id: it.item_id,
          sort_order: idx,
          item_type: it.item_type,
          curriculum_zone_id: it.curriculum_zone_id ?? undefined,
          curriculum_cluster_id: it.curriculum_cluster_id ?? undefined,
          curriculum_concept_id: it.curriculum_concept_id ?? undefined,
          zone_number: it.zone_number ?? undefined,
          is_required: it.is_required,
        }));
      await persistPlanItems(items);
      onToast("Item removed");
    } catch (e) {
      onToast(e instanceof Error ? e.message : "Remove failed", "err");
    } finally {
      setBusy(false);
    }
  }

  async function movePlanItem(itemId: string, direction: -1 | 1) {
    if (!selectedPlan) return;
    setBusy(true);
    try {
      const plan = await ensurePlanIsDraft();
      if (!plan) return;
      const sorted = [...plan.items].sort((a, b) => a.sort_order - b.sort_order);
      const idx = sorted.findIndex((it) => it.item_id === itemId);
      const swap = idx + direction;
      if (idx < 0 || swap < 0 || swap >= sorted.length) return;
      const next = [...sorted];
      [next[idx], next[swap]] = [next[swap], next[idx]];
      const items = next.map((it, order) => ({
        item_id: it.item_id,
        sort_order: order,
        item_type: it.item_type,
        curriculum_zone_id: it.curriculum_zone_id ?? undefined,
        curriculum_cluster_id: it.curriculum_cluster_id ?? undefined,
        curriculum_concept_id: it.curriculum_concept_id ?? undefined,
        zone_number: it.zone_number ?? undefined,
        is_required: it.is_required,
      }));
      await persistPlanItems(items);
      onToast("Order updated");
    } catch (e) {
      onToast(e instanceof Error ? e.message : "Reorder failed", "err");
    } finally {
      setBusy(false);
    }
  }

  async function addZoneCoverageToPlan(zone: CurriculumZone) {
    if (!selectedPlan) {
      onToast("Select a session plan to edit", "err");
      return;
    }
    if (zone.zone_number !== 0) {
      onToast("Zone coverage is only for Zone 0 curiosity", "err");
      return;
    }
    setBusy(true);
    try {
      const plan = await ensurePlanIsDraft();
      if (!plan) return;
      const existing = plan.items;
      const items = [
        ...existing.map((it, idx) => ({
          item_id: it.item_id,
          sort_order: idx,
          item_type: it.item_type,
          curriculum_zone_id: it.curriculum_zone_id ?? undefined,
          curriculum_cluster_id: it.curriculum_cluster_id ?? undefined,
          curriculum_concept_id: it.curriculum_concept_id ?? undefined,
          zone_number: it.zone_number ?? undefined,
          is_required: it.is_required,
        })),
        {
          sort_order: existing.length,
          item_type: "zone_coverage" as const,
          curriculum_zone_id: zone.id,
          zone_number: 0,
        },
      ];
      await persistPlanItems(items);
      onToast("Zone 0 curiosity added to plan");
    } catch (e) {
      onToast(e instanceof Error ? e.message : "Failed to add zone coverage", "err");
    } finally {
      setBusy(false);
    }
  }

  async function addClusterToPlan(zone: CurriculumZone, clusterId: string) {
    if (!selectedPlan) {
      onToast("Select a session plan to edit", "err");
      return;
    }
    setBusy(true);
    try {
      const plan = await ensurePlanIsDraft();
      if (!plan) return;
      const existing = plan.items;
      const items = [
        ...existing.map((it, idx) => ({
          item_id: it.item_id,
          sort_order: idx,
          item_type: it.item_type,
          curriculum_zone_id: it.curriculum_zone_id ?? undefined,
          curriculum_cluster_id: it.curriculum_cluster_id ?? undefined,
          curriculum_concept_id: it.curriculum_concept_id ?? undefined,
          is_required: it.is_required,
        })),
        {
          sort_order: existing.length,
          item_type: "cluster_coverage" as const,
          curriculum_zone_id: zone.id,
          curriculum_cluster_id: clusterId,
        },
      ];
      await persistPlanItems(items);
      onToast("Cluster added to session plan");
    } catch (e) {
      onToast(e instanceof Error ? e.message : "Failed to add cluster", "err");
    } finally {
      setBusy(false);
    }
  }

  async function handleValidateAndPublish() {
    if (!selectedPlan) return;
    setBusy(true);
    setValidationErrors([]);
    try {
      const v = isCatalog
        ? await validateCatalogSessionPlan(token, selectedPlan.id)
        : await validateClassSessionPlan(token, selectedPlan.id);
      if (!v.ready_to_publish) {
        setValidationErrors(v.errors.map((e) => e.message));
        onToast("Fix validation errors before publishing", "err");
        return;
      }
      const published = isCatalog
        ? await publishCatalogSessionPlan(token, selectedPlan.id)
        : await publishClassSessionPlan(token, selectedPlan.id);
      setPlans((prev) => prev.map((p) => (p.id === published.id ? published : p)));
      onToast("Plan published");
    } catch (e) {
      onToast(e instanceof Error ? e.message : "Publish failed", "err");
    } finally {
      setBusy(false);
    }
  }

  async function ensurePlanIsDraft(): Promise<ClassSessionPlan | null> {
    if (!selectedPlan) return null;
    if (selectedPlan.status === "draft") return selectedPlan;
    const draft = isCatalog
      ? await unpublishCatalogSessionPlan(token, selectedPlan.id)
      : await unpublishClassSessionPlan(token, selectedPlan.id);
    setPlans((prev) => prev.map((p) => (p.id === draft.id ? draft : p)));
    return draft;
  }

  async function handleUnpublish() {
    if (!selectedPlan || selectedPlan.status !== "published") return;
    const label = `Session ${selectedPlan.sequence_number}: ${selectedPlan.title}`;
    if (
      !confirm(
        `Unpublish "${label}"?\n\nThe plan will return to draft so you can edit title, description, and coverage. Students will not see it until you publish again.`
      )
    ) {
      return;
    }
    setBusy(true);
    try {
      await ensurePlanIsDraft();
      onToast("Plan unpublished — you can edit again");
    } catch (e) {
      onToast(e instanceof Error ? e.message : "Unpublish failed", "err");
    } finally {
      setBusy(false);
    }
  }

  async function handleDeletePlan() {
    if (!selectedPlan) return;
    const label = `Session ${selectedPlan.sequence_number}: ${selectedPlan.title}`;
    if (
      !confirm(
        `Delete "${label}"?\n\nThis cannot be undone. Scheduled class sessions that already used this plan are not removed.`
      )
    ) {
      return;
    }
    setBusy(true);
    try {
      if (isCatalog) {
        await deleteCatalogSessionPlan(token, selectedPlan.id);
      } else {
        await archiveClassSessionPlan(token, selectedPlan.id);
      }
      const remaining = plans.filter((p) => p.id !== selectedPlan.id);
      setPlans(remaining);
      setSelectedPlanId(remaining[0]?.id ?? null);
      onToast("Session plan deleted");
    } catch (e) {
      onToast(e instanceof Error ? e.message : "Delete failed", "err");
    } finally {
      setBusy(false);
    }
  }

  async function scheduleSelectedPlan() {
    if (!selectedPlan || selectedPlan.status !== "published") {
      onToast("Select a published plan to schedule", "err");
      return;
    }
    setScheduleModalOpen(true);
  }

  async function submitSchedule() {
    if (!selectedPlan) return;
    const start = new Date(`${scheduleDate}T${scheduleTime}:00`);
    const durationMin = Number(scheduleDuration) || 60;
    const end = new Date(start.getTime() + durationMin * 60 * 1000);
    setBusy(true);
    try {
      await createClassSessionInstance(token, {
        class_session_plan_id: selectedPlan.id,
        scheduled_start: start.toISOString(),
        scheduled_end: end.toISOString(),
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      });
      onToast("Instance scheduled");
      setScheduleModalOpen(false);
      await load();
      setTab("calendar");
    } catch (e) {
      onToast(e instanceof Error ? e.message : "Schedule failed", "err");
    } finally {
      setBusy(false);
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-16 text-slate-500">
        <Loader2 className="mr-2 size-5 animate-spin" />
        Loading classroom planning…
      </div>
    );
  }

  if (!readiness.ready) {
    return (
      <div className="rounded-xl border border-dashed border-amber-200 bg-amber-50/80 p-6 text-sm text-amber-950 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-100">
        <p className="font-medium">Classroom planning requirements</p>
        <ul className="mt-3 space-y-2">
          <li className={readiness.v2 ? "text-emerald-800 dark:text-emerald-200" : ""}>
            {readiness.v2 ? "✓" : "○"} Curriculum schema v2
          </li>
          <li className={readiness.published ? "text-emerald-800 dark:text-emerald-200" : ""}>
            {readiness.published ? "✓" : "○"} Curriculum published at least once
          </li>
          <li
            className={readiness.classSessions ? "text-emerald-800 dark:text-emerald-200" : ""}
          >
            {readiness.classSessions ? "✓" : "○"} Class sessions enabled (auto on first publish)
          </li>
        </ul>
        <p className="mt-3">
          Publish the structured curriculum for <strong>{topicName}</strong> once, then you can
          create and edit session plans here (even if curriculum is later draft again).
        </p>
        <Link
          href={curriculumBuilderHref}
          className="mt-3 inline-block text-violet-700 underline dark:text-violet-300"
        >
          Open curriculum builder →
        </Link>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-50">
            Classroom planning
          </h2>
          <p className="text-xs text-slate-500">
            Zone order is fixed (0→4). You control session boundaries and cluster coverage.
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={busy}
            onClick={() => setPlanModalOpen(true)}
          >
            <Plus className="mr-1 size-4" />
            New plan
          </Button>
        </div>
      </div>

      <div className="flex gap-1 border-b border-slate-200 dark:border-slate-700">
        {(isCatalog ? (["plans"] as const) : (["plans", "calendar"] as const)).map((id) => (
          <button
            key={id}
            type="button"
            onClick={() => setTab(id)}
            className={cn(
              "rounded-t-lg px-3 py-2 text-sm font-medium",
              tab === id
                ? "bg-slate-100 text-slate-900 dark:bg-slate-800 dark:text-slate-50"
                : "text-slate-500 hover:text-slate-800"
            )}
          >
            {id === "plans" ? "Session plans" : "Calendar"}
          </button>
        ))}
      </div>

      {tab === "plans" ? (
        <div className="grid gap-4 lg:grid-cols-12">
          <aside className="lg:col-span-3">
            <ul className="space-y-1">
              {plans.length === 0 ? (
                <li className="text-sm text-slate-500">No plans yet.</li>
              ) : (
                plans.map((p) => (
                  <li key={p.id}>
                    <button
                      type="button"
                      onClick={() => setSelectedPlanId(p.id)}
                      className={cn(
                        "w-full rounded-lg border px-3 py-2 text-left text-sm",
                        selectedPlanId === p.id
                          ? "border-violet-300 bg-violet-50 dark:border-violet-800 dark:bg-violet-950/40"
                          : "border-slate-200 hover:bg-slate-50 dark:border-slate-700"
                      )}
                    >
                      <span className="font-medium">
                        #{p.sequence_number} {p.title}
                      </span>
                      <span className="mt-0.5 block text-xs text-slate-500">{p.status}</span>
                    </button>
                  </li>
                ))
              )}
            </ul>
          </aside>

          <section className="space-y-4 lg:col-span-4">
            <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-300">
              Zone ladder (system order)
            </h3>
            <div className="space-y-2">
              {sortedZones.map((zone) => (
                <div
                  key={zone.id}
                  className="rounded-lg border border-slate-200 p-3 dark:border-slate-700"
                >
                  <p className="text-xs font-semibold text-slate-500">
                    Zone {zone.zone_number} — {ZONE_LABELS[zone.zone_number] ?? zone.title}
                  </p>
                  {zone.zone_number === 0 ? (
                    <button
                      type="button"
                      disabled={busy || !selectedPlan}
                      onClick={() => void addZoneCoverageToPlan(zone)}
                      className="mt-2 text-xs text-violet-600 hover:underline disabled:opacity-40"
                    >
                      + Add zone curiosity
                    </button>
                  ) : (
                  <ul className="mt-2 space-y-1">
                    {zone.clusters.map((cluster) => (
                      <li key={cluster.id} className="flex items-center justify-between gap-2">
                        <span className="text-sm">{cluster.title}</span>
                        <button
                          type="button"
                          disabled={busy || !selectedPlan}
                          onClick={() => void addClusterToPlan(zone, cluster.id)}
                          className="text-xs text-violet-600 hover:underline disabled:opacity-40"
                        >
                          + Add
                        </button>
                      </li>
                    ))}
                  </ul>
                  )}
                </div>
              ))}
            </div>
          </section>

          <section className="lg:col-span-5">
            {selectedPlan ? (
              <div className="rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-900">
                <h3 className="font-semibold text-slate-900 dark:text-slate-50">
                  {selectedPlan.title}
                </h3>
                <p className="text-xs text-slate-500">
                  Session #{selectedPlan.sequence_number} · {selectedPlan.status}
                  {selectedPlan.status === "published" ? (
                    <span className="ml-2 text-amber-600 dark:text-amber-400">
                      Published — editing will return this plan to draft
                    </span>
                  ) : null}
                </p>
                <SessionIntroductionEditor
                  token={token}
                  plan={selectedPlan}
                  planScope={planScope}
                  disabled={busy}
                  onBeforeSave={async () => {
                    await ensurePlanIsDraft();
                  }}
                  onSaved={(updated) =>
                    setPlans((prev) => prev.map((p) => (p.id === updated.id ? updated : p)))
                  }
                  onToast={onToast}
                />
                <ul className="mt-3 space-y-1">
                  {selectedPlan.items.length === 0 ? (
                    <li className="text-sm text-slate-500">No coverage items yet.</li>
                  ) : (
                    selectedPlan.items.map((it, idx) => (
                      <li
                        key={it.item_id}
                        className="flex items-center justify-between gap-2 rounded border border-slate-100 px-2 py-1 text-sm dark:border-slate-800"
                      >
                        <span>
                          Z{it.zone_number ?? "?"} · {it.display_name_snapshot ?? it.item_type}
                        </span>
                        {selectedPlan.status === "draft" || selectedPlan.status === "published" ? (
                          <span className="flex gap-1 text-xs">
                            <button
                              type="button"
                              disabled={busy || idx === 0}
                              onClick={() => void movePlanItem(it.item_id, -1)}
                              className="text-slate-500 hover:text-slate-800 disabled:opacity-30"
                            >
                              ↑
                            </button>
                            <button
                              type="button"
                              disabled={busy || idx === selectedPlan.items.length - 1}
                              onClick={() => void movePlanItem(it.item_id, 1)}
                              className="text-slate-500 hover:text-slate-800 disabled:opacity-30"
                            >
                              ↓
                            </button>
                            <button
                              type="button"
                              disabled={busy}
                              onClick={() => void removePlanItem(it.item_id)}
                              className="text-red-600 hover:underline"
                            >
                              Remove
                            </button>
                          </span>
                        ) : null}
                      </li>
                    ))
                  )}
                </ul>
                {validationErrors.length > 0 ? (
                  <ul className="mt-3 space-y-1 text-xs text-red-600 dark:text-red-400">
                    {validationErrors.map((msg) => (
                      <li key={msg}>{msg}</li>
                    ))}
                  </ul>
                ) : null}
                <div className="mt-4 flex flex-wrap gap-2">
                  {selectedPlan.status === "draft" ? (
                    <Button
                      type="button"
                      size="sm"
                      disabled={busy}
                      onClick={() => void handleValidateAndPublish()}
                    >
                      Validate & publish
                    </Button>
                  ) : (
                    <>
                      {!isCatalog ? (
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          disabled={busy}
                          onClick={() => void scheduleSelectedPlan()}
                        >
                          <Calendar className="mr-1 size-4" />
                          Schedule
                        </Button>
                      ) : null}
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        disabled={busy}
                        onClick={() => void handleUnpublish()}
                      >
                        Unpublish to draft
                      </Button>
                    </>
                  )}
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    disabled={busy}
                    onClick={() => void handleDeletePlan()}
                    className="text-red-600 hover:text-red-700 dark:text-red-400"
                  >
                    Delete session
                  </Button>
                </div>
              </div>
            ) : (
              <p className="text-sm text-slate-500">Select or create a session plan.</p>
            )}
          </section>
        </div>
      ) : (
        <div className="space-y-2">
          {instances.length === 0 ? (
            <p className="text-sm text-slate-500">No scheduled instances.</p>
          ) : (
            instances.map((inst) => (
              <div
                key={inst.id}
                className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-slate-200 px-3 py-2 dark:border-slate-700"
              >
                <div>
                  <p className="text-sm font-medium">{inst.plan_snapshot.title}</p>
                  <p className="text-xs text-slate-500">
                    {new Date(inst.scheduled_start).toLocaleString()} · {inst.status} ·{" "}
                    {inst.enrollment_count} enrolled
                  </p>
                </div>
                <div className="flex gap-2">
                  {inst.status === "scheduled" ? (
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      disabled={busy}
                      onClick={async () => {
                        setBusy(true);
                        try {
                          await startClassSessionInstance(token, inst.id);
                          onToast("Session marked live");
                          await load();
                        } catch (e) {
                          onToast(e instanceof Error ? e.message : "Failed", "err");
                        } finally {
                          setBusy(false);
                        }
                      }}
                    >
                      Start
                    </Button>
                  ) : null}
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    disabled={busy}
                    onClick={async () => {
                      setBusy(true);
                      try {
                        await enrollWholeClass(token, inst.id);
                        onToast("Whole class enrolled");
                        await load();
                      } catch (e) {
                        onToast(e instanceof Error ? e.message : "Enroll failed", "err");
                      } finally {
                        setBusy(false);
                      }
                    }}
                  >
                    Enroll class
                  </Button>
                </div>
              </div>
            ))
          )}
        </div>
      )}

      {planModalOpen ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-md rounded-xl bg-white p-4 shadow-lg dark:bg-slate-900">
            <h3 className="font-semibold text-slate-900 dark:text-slate-50">New session plan</h3>
            <input
              value={planTitle}
              onChange={(e) => setPlanTitle(e.target.value)}
              placeholder="Plan title"
              className="mt-3 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm dark:border-slate-600 dark:bg-slate-950"
            />
            <input
              value={planSequence}
              onChange={(e) => setPlanSequence(e.target.value)}
              placeholder="Sequence number"
              className="mt-2 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm dark:border-slate-600 dark:bg-slate-950"
            />
            <div className="mt-4 flex justify-end gap-2">
              <Button type="button" variant="outline" onClick={() => setPlanModalOpen(false)}>
                Cancel
              </Button>
              <Button type="button" disabled={busy} onClick={() => void handleCreatePlan()}>
                Create
              </Button>
            </div>
          </div>
        </div>
      ) : null}

      {scheduleModalOpen ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-md rounded-xl bg-white p-4 shadow-lg dark:bg-slate-900">
            <h3 className="font-semibold text-slate-900 dark:text-slate-50">Schedule instance</h3>
            <input
              type="date"
              value={scheduleDate}
              onChange={(e) => setScheduleDate(e.target.value)}
              className="mt-3 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm dark:border-slate-600 dark:bg-slate-950"
            />
            <input
              type="time"
              value={scheduleTime}
              onChange={(e) => setScheduleTime(e.target.value)}
              className="mt-2 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm dark:border-slate-600 dark:bg-slate-950"
            />
            <input
              value={scheduleDuration}
              onChange={(e) => setScheduleDuration(e.target.value)}
              placeholder="Duration (minutes)"
              className="mt-2 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm dark:border-slate-600 dark:bg-slate-950"
            />
            <div className="mt-4 flex justify-end gap-2">
              <Button type="button" variant="outline" onClick={() => setScheduleModalOpen(false)}>
                Cancel
              </Button>
              <Button type="button" disabled={busy} onClick={() => void submitSchedule()}>
                Schedule
              </Button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
