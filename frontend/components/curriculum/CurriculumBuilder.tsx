"use client";

import { useCallback, useEffect, useMemo, useState, type DragEvent, type ReactNode } from "react";
import Link from "next/link";
import {
  ChevronDown,
  ChevronRight,
  GripVertical,
  Layers,
  Loader2,
  Plus,
  Trash2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { BulletListEditor } from "@/components/classroom/BulletListEditor";
import { VtseTemplateAuthoringPage } from "@/components/curriculum/VtseTemplateAuthoringPage";
import {
  StoryHookAuthoringModal,
  storyHookIsConfigured,
  storyHookSeedPreview,
  type StoryHookDraft,
} from "@/components/curriculum/StoryHookAuthoringModal";
import {
  VisualTeachingAuthoringModal,
  visualTeachingIsConfigured,
  visualTeachingPreview,
  type VisualTeachingDraft,
} from "@/components/curriculum/VisualTeachingAuthoringModal";
import { VtseVisualsAuthoringModal } from "@/components/curriculum/VtseVisualsAuthoringModal";
import {
  createCurriculumCluster,
  createCurriculumConcept,
  createCurriculumZone,
  deleteCurriculumCluster,
  deleteCurriculumConcept,
  deleteCurriculumZone,
  getTopicCurriculumTree,
  moveCurriculumConcept,
  previewTeachingOrder,
  publishTopicCurriculum,
  unpublishTopicCurriculum,
  updateCurriculumCluster,
  updateCurriculumConcept,
  updateCurriculumZone,
  normalizeStoryHookVisualAssetKeys,
  normalizeVisualTeachingAssetKeys,
  validateTopicCurriculum,
  type StoryHookVisualInput,
  type VisualTeachingImageInput,
} from "@/lib/api/curriculumStructure";
import type {
  ConceptStoryHookVisual,
  ConceptVisualTeachingImage,
  CurriculumCluster,
  CurriculumConcept,
  CurriculumTopicSource,
  CurriculumTree,
  CurriculumValidation,
  CurriculumZone,
} from "@/lib/types";
import { cn } from "@/lib/utils";
import { ConceptStructuredContent } from "@/components/curriculum/ConceptStructuredContent";
import { V2CurriculumWorkflowNav } from "@/components/curriculum/V2CurriculumWorkflowNav";

const ZONE_LABELS: Record<number, string> = {
  0: "Curiosity",
  1: "Core Teaching",
  2: "Extension 1",
  3: "Extension 2",
  4: "Extension 3",
};

type Selection =
  | { kind: "zone"; id: string }
  | { kind: "cluster"; id: string }
  | { kind: "concept"; id: string }
  | null;

type CurriculumBuilderProps = {
  token: string;
  topicId: string;
  topicSource: CurriculumTopicSource;
  topicName?: string;
  backHref: string;
  backLabel?: string;
  planningHref?: string | null;
  onToast?: (message: string, variant?: "ok" | "err") => void;
};

function statusBadge(status: string) {
  return status === "published"
    ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200"
    : "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-200";
}

export function CurriculumBuilder({
  token,
  topicId,
  topicSource,
  topicName,
  backHref,
  backLabel = "Back",
  planningHref,
  onToast,
}: CurriculumBuilderProps) {
  const [tree, setTree] = useState<CurriculumTree | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [selection, setSelection] = useState<Selection>(null);
  const [expandedZones, setExpandedZones] = useState<Set<string>>(new Set());
  const [validation, setValidation] = useState<CurriculumValidation | null>(null);
  const [showValidation, setShowValidation] = useState(false);

  const [addZoneOpen, setAddZoneOpen] = useState(false);
  const [addZoneNumber, setAddZoneNumber] = useState(0);
  const [addZoneTitle, setAddZoneTitle] = useState("");

  const notify = useCallback(
    (message: string, variant: "ok" | "err" = "ok") => {
      onToast?.(message, variant);
    },
    [onToast]
  );

  const loadTree = useCallback(async () => {
    setLoading(true);
    try {
      const data = await getTopicCurriculumTree(token, topicId, topicSource);
      setTree(data);
      setExpandedZones((prev) => {
        const next = new Set(prev);
        for (const z of data.zones) next.add(z.id);
        return next;
      });
    } catch (e) {
      notify(e instanceof Error ? e.message : "Failed to load curriculum", "err");
      setTree(null);
    } finally {
      setLoading(false);
    }
  }, [token, topicId, topicSource, notify]);

  useEffect(() => {
    void loadTree();
  }, [loadTree]);

  const availableZoneNumbers = useMemo(() => {
    const used = new Set((tree?.zones ?? []).map((z) => z.zone_number));
    return [0, 1, 2, 3, 4].filter((n) => !used.has(n));
  }, [tree?.zones]);

  const selectedZone = useMemo(() => {
    if (!tree || !selection || selection.kind !== "zone") return null;
    return tree.zones.find((z) => z.id === selection.id) ?? null;
  }, [tree, selection]);

  const selectedCluster = useMemo(() => {
    if (!tree || !selection || selection.kind !== "cluster") return null;
    for (const z of tree.zones) {
      const c = z.clusters.find((cl) => cl.id === selection.id);
      if (c) return c;
    }
    return null;
  }, [tree, selection]);

  const selectedConcept = useMemo(() => {
    if (!tree || !selection || selection.kind !== "concept") return null;
    for (const z of tree.zones) {
      for (const cl of z.clusters) {
        const c = cl.concepts.find((co) => co.id === selection.id);
        if (c) return c;
      }
    }
    return null;
  }, [tree, selection]);

  async function runValidate() {
    setBusy(true);
    try {
      const result = await validateTopicCurriculum(token, topicId, topicSource);
      setValidation(result);
      setShowValidation(true);
      if (result.ready_to_publish) {
        notify("Curriculum is ready to publish");
      } else {
        notify(`${result.errors.length} error(s) found`, "err");
      }
    } catch (e) {
      notify(e instanceof Error ? e.message : "Validation failed", "err");
    } finally {
      setBusy(false);
    }
  }

  async function runPublish() {
    if (
      !confirm(
        "Publish curriculum? Published items stay stable for active sessions. Edits after publish create draft revisions — republish when ready."
      )
    ) {
      return;
    }
    setBusy(true);
    try {
      const result = await validateTopicCurriculum(token, topicId, topicSource);
      setValidation(result);
      setShowValidation(true);
      if (!result.ready_to_publish) {
        const summary =
          result.errors.length > 0
            ? result.errors.map((e) => e.message).join(" · ")
            : "Curriculum is not ready to publish";
        notify(summary, "err");
        return;
      }
      await publishTopicCurriculum(token, topicId, topicSource);
      notify("Curriculum published");
      setShowValidation(false);
      await loadTree();
    } catch (e) {
      notify(e instanceof Error ? e.message : "Publish failed", "err");
    } finally {
      setBusy(false);
    }
  }

  async function runUnpublish() {
    if (
      !confirm(
        "Unpublish curriculum? Student launch and session planning will require publishing again before use."
      )
    ) {
      return;
    }
    setBusy(true);
    try {
      await unpublishTopicCurriculum(token, topicId, topicSource);
      notify("Curriculum unpublished");
      setShowValidation(false);
      await loadTree();
    } catch (e) {
      notify(e instanceof Error ? e.message : "Unpublish failed", "err");
    } finally {
      setBusy(false);
    }
  }

  const isPublished = Boolean(tree?.curriculum_published_at);

  async function handleAddZone() {
    const title = addZoneTitle.trim();
    if (!title) {
      notify("Zone title is required", "err");
      return;
    }
    setBusy(true);
    try {
      await createCurriculumZone(token, {
        topic_id: topicId,
        topic_source: topicSource,
        zone_number: addZoneNumber,
        title,
      });
      notify("Zone created");
      setAddZoneOpen(false);
      setAddZoneTitle("");
      await loadTree();
    } catch (e) {
      notify(e instanceof Error ? e.message : "Create zone failed", "err");
    } finally {
      setBusy(false);
    }
  }

  function toggleZoneExpanded(zoneId: string) {
    setExpandedZones((prev) => {
      const next = new Set(prev);
      if (next.has(zoneId)) next.delete(zoneId);
      else next.add(zoneId);
      return next;
    });
  }

  async function handleMoveConcept(
    conceptId: string,
    targetClusterId: string,
    targetIndex: number
  ) {
    if (busy) return;
    setBusy(true);
    try {
      await moveCurriculumConcept(token, conceptId, {
        topic_source: topicSource,
        target_cluster_id: targetClusterId,
        target_index: targetIndex,
      });
      notify("Concept moved");
      await loadTree();
    } catch (e) {
      notify(e instanceof Error ? e.message : "Move failed", "err");
      await loadTree();
    } finally {
      setBusy(false);
    }
  }

  const displayName = tree?.topic_name ?? topicName ?? "Topic";

  return (
    <div className="mx-auto max-w-[1400px] space-y-6">
      {planningHref ? (
        <V2CurriculumWorkflowNav
          topicName={displayName}
          builderHref={`#`}
          planningHref={planningHref}
          workspaceHref={backHref}
          active="builder"
        />
      ) : null}
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900 dark:text-slate-50">
            Structured curriculum
          </h1>
          <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
            <Link href={backHref} className="text-violet-600 hover:underline dark:text-violet-400">
              {backLabel}
            </Link>
            {" / "}
            <span className="text-slate-800 dark:text-slate-200">{displayName}</span>
            {" / "}
            <span>Builder</span>
            {tree ? (
              <>
                {" "}
                · schema {tree.curriculum_schema_version} · revision{" "}
                {tree.curriculum_revision}
                {tree.curriculum_published_at ? (
                  <> · published {new Date(tree.curriculum_published_at).toLocaleString()}</>
                ) : null}
              </>
            ) : null}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            variant="secondary"
            disabled={busy || loading || availableZoneNumbers.length === 0}
            onClick={() => {
              setAddZoneNumber(availableZoneNumbers[0] ?? 0);
              setAddZoneTitle(ZONE_LABELS[availableZoneNumbers[0] ?? 0] ?? "");
              setAddZoneOpen(true);
            }}
          >
            <Plus className="mr-1 size-4" />
            Add zone
          </Button>
          <Button type="button" variant="secondary" disabled={busy || loading} onClick={() => void runValidate()}>
            {busy ? <Loader2 className="size-4 animate-spin" /> : "Validate"}
          </Button>
          <Button
            type="button"
            variant={isPublished ? "outline" : "default"}
            disabled={busy || loading}
            onClick={() => void (isPublished ? runUnpublish() : runPublish())}
          >
            {isPublished ? "Unpublish" : "Publish"}
          </Button>
        </div>
      </div>

      {showValidation && validation ? (
        <div
          className={cn(
            "rounded-xl border p-4 text-sm",
            validation.ready_to_publish
              ? "border-emerald-200 bg-emerald-50 dark:border-emerald-800 dark:bg-emerald-950/40"
              : "border-amber-200 bg-amber-50 dark:border-amber-800 dark:bg-amber-950/40"
          )}
        >
          <div className="flex items-start justify-between gap-2">
            <p className="font-medium text-slate-900 dark:text-slate-50">
              {validation.ready_to_publish
                ? "Ready to publish"
                : `${validation.errors.length} error(s), ${validation.warnings.length} warning(s)`}
            </p>
            <button
              type="button"
              className="text-xs text-slate-500 hover:text-slate-800"
              onClick={() => setShowValidation(false)}
            >
              Dismiss
            </button>
          </div>
          {validation.errors.length > 0 ? (
            <ul className="mt-2 list-disc space-y-1 pl-5 text-red-700 dark:text-red-300">
              {validation.errors.map((issue, i) => (
                <li key={`err-${i}`}>
                  {issue.path ? `${issue.path}: ` : ""}
                  {issue.message}
                </li>
              ))}
            </ul>
          ) : null}
          {validation.warnings.length > 0 ? (
            <ul className="mt-2 list-disc space-y-1 pl-5 text-amber-800 dark:text-amber-200">
              {validation.warnings.map((issue, i) => (
                <li key={`warn-${i}`}>
                  {issue.path ? `${issue.path}: ` : ""}
                  {issue.message}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
        <aside className="lg:col-span-5">
          <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900">
            <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-800 dark:text-slate-100">
              <Layers className="size-4 opacity-70" />
              Curriculum tree
            </div>
            {loading ? (
              <p className="flex items-center gap-2 text-sm text-slate-500">
                <Loader2 className="size-4 animate-spin" /> Loading…
              </p>
            ) : !tree || tree.zones.length === 0 ? (
              <p className="text-sm text-slate-500">
                No zones yet. Add zone 0 (Curiosity) and zone 1 (Core Teaching) to start.
              </p>
            ) : (
              <ul className="custom-scrollbar max-h-[min(70vh,640px)] space-y-2 overflow-y-auto pr-1">
                {[...tree.zones]
                  .sort((a, b) => a.zone_number - b.zone_number)
                  .map((zone) => (
                    <ZoneTreeNode
                      key={zone.id}
                      zone={zone}
                      topicId={topicId}
                      topicSource={topicSource}
                      token={token}
                      expanded={expandedZones.has(zone.id)}
                      selection={selection}
                      busy={busy}
                      onToggle={() => toggleZoneExpanded(zone.id)}
                      onSelect={setSelection}
                      onReload={loadTree}
                      onNotify={notify}
                      onBusy={setBusy}
                      onMoveConcept={handleMoveConcept}
                    />
                  ))}
              </ul>
            )}
          </div>
        </aside>

        <section className="lg:col-span-7">
          <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900">
            {selectedZone ? (
              <ZoneDetailPanel
                zone={selectedZone}
                topicSource={topicSource}
                token={token}
                busy={busy}
                onBusy={setBusy}
                onReload={loadTree}
                onNotify={notify}
                onDeleted={() => setSelection(null)}
              />
            ) : selectedCluster ? (
              <ClusterDetailPanel
                cluster={selectedCluster}
                topicSource={topicSource}
                token={token}
                busy={busy}
                onBusy={setBusy}
                onReload={loadTree}
                onNotify={notify}
                onDeleted={() => setSelection(null)}
              />
            ) : selectedConcept ? (
              <ConceptDetailPanel
                concept={selectedConcept}
                topicId={topicId}
                topicSource={topicSource}
                token={token}
                busy={busy}
                onBusy={setBusy}
                onReload={loadTree}
                onNotify={notify}
                onDeleted={() => setSelection(null)}
              />
            ) : (
              <p className="text-center text-sm text-slate-500">
                Select a zone, cluster, or concept in the tree to edit details.
              </p>
            )}
          </div>
        </section>
      </div>

      {addZoneOpen ? (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-md rounded-xl border border-slate-200 bg-white p-6 shadow-xl dark:border-slate-700 dark:bg-slate-900">
            <h3 className="text-lg font-semibold text-slate-900 dark:text-slate-50">Add curriculum zone</h3>
            <div className="mt-4 space-y-3">
              <label className="block text-xs font-medium text-slate-600 dark:text-slate-400">
                Zone number
                <select
                  value={addZoneNumber}
                  onChange={(e) => {
                    const n = Number(e.target.value);
                    setAddZoneNumber(n);
                    if (!addZoneTitle.trim()) setAddZoneTitle(ZONE_LABELS[n] ?? "");
                  }}
                  className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm dark:border-slate-600 dark:bg-slate-950"
                >
                  {availableZoneNumbers.map((n) => (
                    <option key={n} value={n}>
                      Zone {n} — {ZONE_LABELS[n]}
                    </option>
                  ))}
                </select>
              </label>
              <label className="block text-xs font-medium text-slate-600 dark:text-slate-400">
                Title
                <input
                  value={addZoneTitle}
                  onChange={(e) => setAddZoneTitle(e.target.value)}
                  className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm dark:border-slate-600 dark:bg-slate-950"
                />
              </label>
            </div>
            <div className="mt-6 flex justify-end gap-2">
              <Button type="button" variant="outline" onClick={() => setAddZoneOpen(false)}>
                Cancel
              </Button>
              <Button type="button" disabled={busy} onClick={() => void handleAddZone()}>
                {busy ? "Creating…" : "Create zone"}
              </Button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

type TreeCallbacks = {
  topicId: string;
  topicSource: CurriculumTopicSource;
  token: string;
  selection: Selection;
  busy: boolean;
  onToggle: () => void;
  onSelect: (sel: Selection) => void;
  onReload: () => Promise<void>;
  onNotify: (msg: string, variant?: "ok" | "err") => void;
  onBusy: (v: boolean) => void;
  onMoveConcept: (
    conceptId: string,
    targetClusterId: string,
    targetIndex: number
  ) => Promise<void>;
};

type ConceptDragPayload = {
  conceptId: string;
  sourceClusterId: string;
  sourceZoneId: string;
};

const CONCEPT_DRAG_MIME = "application/x-ai-tutor-concept";

function parseConceptDrag(dataTransfer: DataTransfer): ConceptDragPayload | null {
  try {
    const raw =
      dataTransfer.getData(CONCEPT_DRAG_MIME) || dataTransfer.getData("text/plain");
    if (!raw) return null;
    const parsed = JSON.parse(raw) as ConceptDragPayload;
    if (!parsed?.conceptId || !parsed?.sourceClusterId || !parsed?.sourceZoneId) {
      return null;
    }
    return parsed;
  } catch {
    return null;
  }
}

function ZoneTreeNode({
  zone,
  expanded,
  ...cb
}: { zone: CurriculumZone; expanded: boolean } & TreeCallbacks) {
  const isSelected = cb.selection?.kind === "zone" && cb.selection.id === zone.id;
  const [clusterOpen, setClusterOpen] = useState(false);
  const [clusterTitle, setClusterTitle] = useState("");

  async function submitCluster() {
    const title = clusterTitle.trim();
    if (!title) {
      cb.onNotify("Cluster title is required", "err");
      return;
    }
    cb.onBusy(true);
    try {
      await createCurriculumCluster(cb.token, {
        topic_id: cb.topicId,
        topic_source: cb.topicSource,
        curriculum_zone_id: zone.id,
        title,
      });
      cb.onNotify("Cluster created");
      setClusterTitle("");
      setClusterOpen(false);
      await cb.onReload();
    } catch (e) {
      cb.onNotify(e instanceof Error ? e.message : "Create cluster failed", "err");
    } finally {
      cb.onBusy(false);
    }
  }

  const canAddCluster = zone.zone_number !== 0;

  return (
    <li className="rounded-lg border border-slate-200 dark:border-slate-700">
      <div
        className={cn(
          "flex items-center gap-1 px-2 py-2",
          isSelected && "bg-violet-50 dark:bg-violet-950/30"
        )}
      >
        <button
          type="button"
          className="rounded p-0.5 text-slate-500"
          onClick={cb.onToggle}
          aria-label={expanded ? "Collapse" : "Expand"}
        >
          {expanded ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
        </button>
        <button
          type="button"
          className="min-w-0 flex-1 text-left text-sm font-medium text-slate-800 dark:text-slate-100"
          onClick={() => cb.onSelect({ kind: "zone", id: zone.id })}
        >
          Zone {zone.zone_number}: {zone.title}
          {zone.is_system_zone ? (
            <span className="ml-1 text-xs font-normal text-slate-500">(system)</span>
          ) : null}
        </button>
        <span className={cn("rounded-full px-2 py-0.5 text-[10px] font-medium", statusBadge(zone.status))}>
          {zone.status}
        </span>
        {canAddCluster ? (
          <button
            type="button"
            disabled={cb.busy}
            className="rounded p-1 text-violet-600 hover:bg-violet-50 disabled:opacity-40 dark:hover:bg-violet-950/40"
            title="Add cluster"
            onClick={() => setClusterOpen(true)}
          >
            <Plus className="size-3.5" />
          </button>
        ) : null}
      </div>
      {clusterOpen ? (
        <div className="border-t border-slate-100 px-3 py-2 dark:border-slate-800">
          <input
            value={clusterTitle}
            onChange={(e) => setClusterTitle(e.target.value)}
            placeholder="Cluster title"
            className="w-full rounded border border-slate-200 px-2 py-1 text-xs dark:border-slate-600 dark:bg-slate-950"
          />
          <div className="mt-2 flex gap-2">
            <button
              type="button"
              disabled={cb.busy}
              onClick={() => void submitCluster()}
              className="rounded bg-violet-600 px-2 py-1 text-[11px] text-white"
            >
              Add
            </button>
            <button
              type="button"
              onClick={() => {
                setClusterOpen(false);
                setClusterTitle("");
              }}
              className="text-[11px] text-slate-500"
            >
              Cancel
            </button>
          </div>
        </div>
      ) : null}
      {expanded ? (
        <ul className="border-t border-slate-100 px-2 py-1 dark:border-slate-800">
          {zone.zone_number === 0 ? (
            <li className="py-2 pl-6 text-xs text-slate-500">
              Topic curiosity zone — no clusters or concepts
            </li>
          ) : zone.clusters.length === 0 ? (
            <li className="py-2 pl-6 text-xs text-slate-500">No clusters</li>
          ) : (
            zone.clusters.map((cluster) => (
              <ClusterTreeNode key={cluster.id} cluster={cluster} zoneId={zone.id} {...cb} />
            ))
          )}
        </ul>
      ) : null}
    </li>
  );
}

function ClusterTreeNode({
  cluster,
  zoneId,
  ...cb
}: { cluster: CurriculumCluster; zoneId: string } & TreeCallbacks) {
  const isSelected = cb.selection?.kind === "cluster" && cb.selection.id === cluster.id;
  const [conceptOpen, setConceptOpen] = useState(false);
  const [conceptName, setConceptName] = useState("");
  const [runtimeKey, setRuntimeKey] = useState("");
  const [dropIndex, setDropIndex] = useState<number | null>(null);

  async function submitConcept() {
    const name = conceptName.trim();
    if (!name) {
      cb.onNotify("Concept display name is required", "err");
      return;
    }
    cb.onBusy(true);
    try {
      await createCurriculumConcept(cb.token, {
        topic_id: cb.topicId,
        topic_source: cb.topicSource,
        curriculum_cluster_id: cluster.id,
        display_name: name,
        ...(runtimeKey.trim() ? { legacy_concept_key: runtimeKey.trim() } : {}),
      });
      cb.onNotify("Concept created");
      setConceptName("");
      setRuntimeKey("");
      setConceptOpen(false);
      await cb.onReload();
    } catch (e) {
      cb.onNotify(e instanceof Error ? e.message : "Create concept failed", "err");
    } finally {
      cb.onBusy(false);
    }
  }

  function allowDrop(e: DragEvent) {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
  }

  async function handleDropAt(e: DragEvent, targetIndex: number) {
    e.preventDefault();
    e.stopPropagation();
    setDropIndex(null);
    if (cb.busy) return;
    const payload = parseConceptDrag(e.dataTransfer);
    if (!payload) return;
    if (payload.sourceZoneId !== zoneId) {
      cb.onNotify("Concepts can only move within the same curriculum zone", "err");
      return;
    }
    let index = targetIndex;
    if (
      payload.sourceClusterId === cluster.id &&
      cluster.concepts.findIndex((c) => c.id === payload.conceptId) < targetIndex &&
      cluster.concepts.some((c) => c.id === payload.conceptId)
    ) {
      // When moving down within the same list, account for removal of the source item.
      index = Math.max(0, targetIndex - 1);
    }
    await cb.onMoveConcept(payload.conceptId, cluster.id, index);
  }

  return (
    <li className="py-1 pl-4">
      <div
        className={cn(
          "flex items-center gap-1 rounded-md px-2 py-1.5",
          isSelected && "bg-violet-50 dark:bg-violet-950/30"
        )}
        onDragOver={allowDrop}
        onDragLeave={() => setDropIndex(null)}
        onDrop={(e) => void handleDropAt(e, cluster.concepts.length)}
      >
        <button
          type="button"
          className="min-w-0 flex-1 text-left text-sm text-slate-700 dark:text-slate-200"
          onClick={() => cb.onSelect({ kind: "cluster", id: cluster.id })}
        >
          C{cluster.cluster_number}: {cluster.title}
        </button>
        <span className={cn("rounded-full px-2 py-0.5 text-[10px] font-medium", statusBadge(cluster.status))}>
          {cluster.status}
        </span>
        <button
          type="button"
          disabled={cb.busy}
          className="rounded p-1 text-violet-600 hover:bg-violet-50 disabled:opacity-40 dark:hover:bg-violet-950/40"
          title="Add concept"
          onClick={() => setConceptOpen(true)}
        >
          <Plus className="size-3.5" />
        </button>
      </div>
      {conceptOpen ? (
        <div className="mb-2 rounded border border-slate-200 p-2 dark:border-slate-700">
          <input
            value={conceptName}
            onChange={(e) => setConceptName(e.target.value)}
            placeholder="Display name"
            className="mb-1 w-full rounded border border-slate-200 px-2 py-1 text-xs dark:border-slate-600 dark:bg-slate-950"
          />
          <input
            value={runtimeKey}
            onChange={(e) => setRuntimeKey(e.target.value)}
            placeholder="Runtime key (optional)"
            className="w-full rounded border border-slate-200 px-2 py-1 text-xs dark:border-slate-600 dark:bg-slate-950"
          />
          <div className="mt-2 flex gap-2">
            <button
              type="button"
              disabled={cb.busy}
              onClick={() => void submitConcept()}
              className="rounded bg-violet-600 px-2 py-1 text-[11px] text-white"
            >
              Add
            </button>
            <button
              type="button"
              onClick={() => {
                setConceptOpen(false);
                setConceptName("");
                setRuntimeKey("");
              }}
              className="text-[11px] text-slate-500"
            >
              Cancel
            </button>
          </div>
        </div>
      ) : null}
      <ul className="pl-2">
        {cluster.concepts.length === 0 ? (
          <li
            className={cn(
              "rounded border border-dashed px-2 py-3 text-xs text-slate-400",
              dropIndex === 0 && "border-violet-400 bg-violet-50/60 dark:bg-violet-950/20"
            )}
            onDragOver={(e) => {
              allowDrop(e);
              setDropIndex(0);
            }}
            onDrop={(e) => void handleDropAt(e, 0)}
          >
            Drop concepts here
          </li>
        ) : (
          cluster.concepts.map((concept, index) => {
            const conceptSelected =
              cb.selection?.kind === "concept" && cb.selection.id === concept.id;
            return (
              <li key={concept.id}>
                {dropIndex === index ? (
                  <div className="my-0.5 h-0.5 rounded bg-violet-500" aria-hidden />
                ) : null}
                <div
                  className={cn(
                    "flex items-stretch gap-1 rounded-md",
                    conceptSelected && "bg-violet-50 dark:bg-violet-950/30"
                  )}
                  onDragOver={(e) => {
                    allowDrop(e);
                    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
                    const before = e.clientY < rect.top + rect.height / 2;
                    setDropIndex(before ? index : index + 1);
                  }}
                  onDrop={(e) => {
                    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
                    const before = e.clientY < rect.top + rect.height / 2;
                    void handleDropAt(e, before ? index : index + 1);
                  }}
                >
                  <div
                    draggable={!cb.busy}
                    onDragStart={(e) => {
                      const payload: ConceptDragPayload = {
                        conceptId: concept.id,
                        sourceClusterId: cluster.id,
                        sourceZoneId: zoneId,
                      };
                      const raw = JSON.stringify(payload);
                      e.dataTransfer.setData(CONCEPT_DRAG_MIME, raw);
                      e.dataTransfer.setData("text/plain", raw);
                      e.dataTransfer.effectAllowed = "move";
                    }}
                    onDragEnd={() => setDropIndex(null)}
                    className="flex cursor-grab touch-none items-center rounded-l-md px-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600 active:cursor-grabbing dark:hover:bg-slate-800"
                    aria-label={`Drag to reorder: ${concept.display_name}`}
                    role="button"
                    tabIndex={0}
                  >
                    <GripVertical className="size-3.5" aria-hidden />
                  </div>
                  <button
                    type="button"
                    className={cn(
                      "min-w-0 flex-1 rounded-r-md px-2 py-1 text-left text-xs text-slate-600 dark:text-slate-300",
                      conceptSelected && "font-medium"
                    )}
                    onClick={() => cb.onSelect({ kind: "concept", id: concept.id })}
                  >
                    {concept.display_name}
                  </button>
                </div>
              </li>
            );
          })
        )}
        {cluster.concepts.length > 0 && dropIndex === cluster.concepts.length ? (
          <li className="my-0.5 h-0.5 rounded bg-violet-500" aria-hidden />
        ) : null}
      </ul>
    </li>
  );
}

function ZoneDetailPanel({
  zone,
  topicSource,
  token,
  busy,
  onBusy,
  onReload,
  onNotify,
  onDeleted,
}: {
  zone: CurriculumZone;
  topicSource: CurriculumTopicSource;
  token: string;
  busy: boolean;
  onBusy: (v: boolean) => void;
  onReload: () => Promise<void>;
  onNotify: (msg: string, variant?: "ok" | "err") => void;
  onDeleted: () => void;
}) {
  const [title, setTitle] = useState(zone.title);
  const [description, setDescription] = useState(zone.description);
  const deleteLocked = zone.status === "published";

  useEffect(() => {
    setTitle(zone.title);
    setDescription(zone.description);
  }, [zone.id, zone.title, zone.description]);

  async function save() {
    onBusy(true);
    try {
      await updateCurriculumZone(token, zone.id, {
        topic_source: topicSource,
        title: title.trim(),
        description: description.trim(),
      });
      onNotify("Zone saved");
      await onReload();
    } catch (e) {
      onNotify(e instanceof Error ? e.message : "Save failed", "err");
    } finally {
      onBusy(false);
    }
  }

  async function remove() {
    if (zone.is_system_zone) {
      onNotify("System zone cannot be deleted", "err");
      return;
    }
    if (!confirm(`Delete zone ${zone.zone_number}: ${zone.title}?`)) return;
    onBusy(true);
    try {
      await deleteCurriculumZone(token, zone.id, topicSource);
      onNotify("Zone deleted");
      onDeleted();
      await onReload();
    } catch (e) {
      onNotify(e instanceof Error ? e.message : "Delete failed", "err");
    } finally {
      onBusy(false);
    }
  }

  return (
    <DetailShell
      title={`Zone ${zone.zone_number}`}
      subtitle={ZONE_LABELS[zone.zone_number] ?? zone.purpose}
      status={zone.status}
      readOnly={false}
      busy={busy}
      onSave={() => void save()}
      onDelete={
        zone.is_system_zone || deleteLocked ? undefined : () => void remove()
      }
    >
      <MetaRow label="Allows VTSE" value={zone.allows_vtse ? "Yes" : "No"} />
      <MetaRow label="System zone" value={zone.is_system_zone ? "Yes" : "No"} />
      {deleteLocked ? (
        <p className="text-xs text-amber-700 dark:text-amber-300">
          Published — saving edits creates a draft revision. Republish when ready. Delete is
          blocked while published.
        </p>
      ) : null}
      <Field label="Title" value={title} onChange={setTitle} />
      <Field
        label="Description"
        value={description}
        onChange={setDescription}
        multiline
      />
    </DetailShell>
  );
}

function ClusterDetailPanel({
  cluster,
  topicSource,
  token,
  busy,
  onBusy,
  onReload,
  onNotify,
  onDeleted,
}: {
  cluster: CurriculumCluster;
  topicSource: CurriculumTopicSource;
  token: string;
  busy: boolean;
  onBusy: (v: boolean) => void;
  onReload: () => Promise<void>;
  onNotify: (msg: string, variant?: "ok" | "err") => void;
  onDeleted: () => void;
}) {
  const [title, setTitle] = useState(cluster.title);
  const [description, setDescription] = useState(cluster.description ?? "");
  const [minutes, setMinutes] = useState(
    cluster.estimated_learning_minutes != null ? String(cluster.estimated_learning_minutes) : ""
  );
  const deleteLocked = cluster.status === "published";

  useEffect(() => {
    setTitle(cluster.title);
    setDescription(cluster.description ?? "");
    setMinutes(
      cluster.estimated_learning_minutes != null ? String(cluster.estimated_learning_minutes) : ""
    );
  }, [
    cluster.id,
    cluster.title,
    cluster.description,
    cluster.estimated_learning_minutes,
  ]);

  async function save() {
    onBusy(true);
    try {
      const parsed = minutes.trim() ? Number(minutes) : null;
      const updated = await updateCurriculumCluster(token, cluster.id, {
        topic_source: topicSource,
        title: title.trim(),
        description: description.trim(),
        estimated_learning_minutes: parsed,
      });
      setDescription(updated.description ?? description);
      setTitle(updated.title ?? title);
      onNotify("Cluster saved");
      await onReload();
    } catch (e) {
      onNotify(e instanceof Error ? e.message : "Save failed", "err");
    } finally {
      onBusy(false);
    }
  }

  async function remove() {
    if (!confirm(`Delete cluster ${cluster.cluster_number}: ${cluster.title}?`)) return;
    onBusy(true);
    try {
      await deleteCurriculumCluster(token, cluster.id, topicSource);
      onNotify("Cluster deleted");
      onDeleted();
      await onReload();
    } catch (e) {
      onNotify(e instanceof Error ? e.message : "Delete failed", "err");
    } finally {
      onBusy(false);
    }
  }

  return (
    <DetailShell
      title={`Cluster ${cluster.cluster_number}`}
      subtitle={cluster.title}
      status={cluster.status}
      readOnly={false}
      busy={busy}
      onSave={() => void save()}
      onDelete={deleteLocked ? undefined : () => void remove()}
    >
      {deleteLocked ? (
        <p className="text-xs text-amber-700 dark:text-amber-300">
          Published — edits create draft revisions. Delete blocked until demoted via edit workflow.
        </p>
      ) : null}
      <Field label="Title" value={title} onChange={setTitle} />
      <Field
        label="Description"
        value={description}
        onChange={setDescription}
        multiline
      />
      <p className="text-xs text-slate-500 dark:text-slate-400">
        Study points and learning outcomes are authored on each concept. Cluster introductions
        aggregate concept objectives in concept order.
      </p>
      <Field
        label="Estimated learning minutes"
        value={minutes}
        onChange={setMinutes}
        inputMode="numeric"
      />
      <MetaRow label="Concepts" value={String(cluster.concepts.length)} />
    </DetailShell>
  );
}

function ConceptDetailPanel({
  concept,
  topicId,
  topicSource,
  token,
  busy,
  onBusy,
  onReload,
  onNotify,
  onDeleted,
}: {
  concept: CurriculumConcept;
  topicId: string;
  topicSource: CurriculumTopicSource;
  token: string;
  busy: boolean;
  onBusy: (v: boolean) => void;
  onReload: () => Promise<void>;
  onNotify: (msg: string, variant?: "ok" | "err") => void;
  onDeleted: () => void;
}) {
  const [displayName, setDisplayName] = useState(concept.display_name);
  const [runtimeKey, setRuntimeKey] = useState(concept.canonical_runtime_key);
  const [difficulty, setDifficulty] = useState(concept.difficulty_level);
  const [minutes, setMinutes] = useState(
    concept.estimated_learning_minutes != null ? String(concept.estimated_learning_minutes) : ""
  );
  const [studyPoints, setStudyPoints] = useState<string[]>(concept.study_points ?? []);
  const [outcomes, setOutcomes] = useState<string[]>(concept.learning_outcomes ?? []);
  const [hookTitle, setHookTitle] = useState(concept.story_hook?.title ?? "");
  const [hookBody, setHookBody] = useState(concept.story_hook?.body ?? "");
  const [hookIntent, setHookIntent] = useState(
    concept.story_hook?.teacher_intent ?? ""
  );
  const [hookVisuals, setHookVisuals] = useState<StoryHookVisualInput[]>(
    () => concept.story_hook?.visuals?.map(toVisualInput) ?? []
  );
  const [vtImages, setVtImages] = useState<VisualTeachingImageInput[]>(
    () => concept.visual_teaching?.images?.map(toVtImageInput) ?? []
  );
  const [teachingSequence, setTeachingSequence] = useState<TeachingStageId[]>(
    () => sanitizeTeachingSequence(concept.teaching_sequence)
  );
  const [teachingOrderMode, setTeachingOrderMode] = useState<"manual" | "auto">(
    concept.teaching_sequence_mode === "auto" ? "auto" : "manual"
  );
  const [vtseModalOpen, setVtseModalOpen] = useState(false);
  const [storyHookModalOpen, setStoryHookModalOpen] = useState(false);
  const [visualTeachingModalOpen, setVisualTeachingModalOpen] = useState(false);
  const [vtseVisualsOpen, setVtseVisualsOpen] = useState(false);
  const [vtseVisuals, setVtseVisuals] = useState(concept.vtse_visuals ?? null);
  const deleteLocked = concept.status === "published";

  const hookDraft: StoryHookDraft = {
    title: hookTitle,
    body: hookBody,
    teacher_intent: hookIntent,
    visuals: hookVisuals,
  };
  const hookConfigured = storyHookIsConfigured(hookDraft);
  const hookPreview = storyHookSeedPreview(hookBody);
  const vtDraft: VisualTeachingDraft = { images: vtImages };
  const vtConfigured = visualTeachingIsConfigured(vtDraft);
  const vtPreview = visualTeachingPreview(vtDraft);

  useEffect(() => {
    setDisplayName(concept.display_name);
    setRuntimeKey(concept.canonical_runtime_key);
    setDifficulty(concept.difficulty_level);
    setMinutes(
      concept.estimated_learning_minutes != null ? String(concept.estimated_learning_minutes) : ""
    );
    setStudyPoints(concept.study_points ?? []);
    setOutcomes(concept.learning_outcomes ?? []);
    setHookTitle(concept.story_hook?.title ?? "");
    setHookBody(concept.story_hook?.body ?? "");
    setHookIntent(concept.story_hook?.teacher_intent ?? "");
    setHookVisuals(concept.story_hook?.visuals?.map(toVisualInput) ?? []);
    setVtImages(concept.visual_teaching?.images?.map(toVtImageInput) ?? []);
    setVtseVisuals(concept.vtse_visuals ?? null);
    setTeachingSequence(sanitizeTeachingSequence(concept.teaching_sequence));
    setTeachingOrderMode(concept.teaching_sequence_mode === "auto" ? "auto" : "manual");
  }, [
    concept.id,
    concept.display_name,
    concept.canonical_runtime_key,
    concept.difficulty_level,
    concept.estimated_learning_minutes,
    concept.study_points,
    concept.learning_outcomes,
    concept.story_hook,
    concept.visual_teaching,
    concept.vtse_visuals,
    concept.teaching_sequence,
    concept.teaching_sequence_mode,
  ]);

  async function save() {
    onBusy(true);
    try {
      const parsed = minutes.trim() ? Number(minutes) : null;
      const trimmedKey = runtimeKey.trim();
      const savedStudy = studyPoints.map((s) => s.trim()).filter(Boolean);
      const savedOutcomes = outcomes.map((s) => s.trim()).filter(Boolean);
      const savedHookTitle = hookTitle.trim();
      const savedHookBody = hookBody.trim();
      const savedHookIntent = hookIntent.trim();
      const savedVisuals = normalizeStoryHookVisualAssetKeys(hookVisuals);
      const story_hook = {
        title: savedHookTitle,
        body: savedHookBody,
        teacher_intent: savedHookIntent,
        visuals: savedVisuals,
      };
      const savedVtImages = normalizeVisualTeachingAssetKeys(vtImages);
      await updateCurriculumConcept(token, concept.id, {
        topic_source: topicSource,
        display_name: displayName.trim(),
        difficulty_level: difficulty,
        estimated_learning_minutes: parsed,
        study_points: savedStudy,
        learning_outcomes: savedOutcomes,
        story_hook,
        visual_teaching: { images: savedVtImages },
        teaching_sequence: teachingSequence,
        teaching_sequence_mode: teachingOrderMode,
        ...(trimmedKey && trimmedKey !== concept.canonical_runtime_key
          ? { canonical_runtime_key: trimmedKey }
          : {}),
      });
      setStudyPoints(savedStudy);
      setOutcomes(savedOutcomes);
      setHookTitle(savedHookTitle);
      setHookBody(savedHookBody);
      setHookIntent(savedHookIntent);
      setHookVisuals(savedVisuals);
      setVtImages(savedVtImages);
      onNotify(
        trimmedKey !== concept.canonical_runtime_key
          ? "Concept saved — republish curriculum and start a new session for the new runtime key."
          : "Concept saved"
      );
      await onReload();
      return true;
    } catch (e) {
      onNotify(e instanceof Error ? e.message : "Save failed", "err");
      return false;
    } finally {
      onBusy(false);
    }
  }

  async function previewAuto(regenerate: boolean) {
    if (teachingOrderMode !== "auto") return;
    const saved = await save();
    if (!saved) return;
    onBusy(true);
    try {
      await previewTeachingOrder(token, concept.id, {
        topic_source: topicSource,
        regenerate,
      });
      onNotify(regenerate ? "Auto order regenerated" : "Auto order updated");
      await onReload();
    } catch (e) {
      onNotify(e instanceof Error ? e.message : "Could not preview Auto order", "err");
    } finally {
      onBusy(false);
    }
  }

  async function remove() {
    if (!confirm(`Delete concept "${concept.display_name}"?`)) return;
    onBusy(true);
    try {
      await deleteCurriculumConcept(token, concept.id, topicSource);
      onNotify("Concept deleted");
      onDeleted();
      await onReload();
    } catch (e) {
      onNotify(e instanceof Error ? e.message : "Delete failed", "err");
    } finally {
      onBusy(false);
    }
  }

  return (
    <DetailShell
      title="Concept"
      subtitle={concept.slug}
      status={concept.status}
      readOnly={false}
      busy={busy}
      onSave={() => void save()}
      onDelete={deleteLocked ? undefined : () => void remove()}
    >
      <Field label="Display name" value={displayName} onChange={setDisplayName} />
      <Field
        label="Canonical runtime key"
        value={runtimeKey}
        onChange={setRuntimeKey}
      />
      <p className="-mt-2 text-xs text-slate-500 dark:text-slate-400">
        Used by sessions, RAG, and VTSE as{" "}
        <code className="rounded bg-slate-100 px-1 dark:bg-slate-800">current_concept</code>.
        Use a short label (e.g.{" "}
        <span className="italic">non-living things</span>), not a question. After changing,
        republish the curriculum and start a new student session.
      </p>
      <label className="block text-xs font-medium text-slate-600 dark:text-slate-400">
        Difficulty
        <select
          value={difficulty}
          onChange={(e) => setDifficulty(e.target.value)}
          className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm dark:border-slate-600 dark:bg-slate-950"
        >
          <option value="basic">basic</option>
          <option value="medium">medium</option>
          <option value="hard">hard</option>
        </select>
      </label>
      <Field
        label="Estimated learning minutes"
        value={minutes}
        onChange={setMinutes}
        inputMode="numeric"
      />
      <BulletListEditor
        label="What we will study"
        items={studyPoints}
        onChange={setStudyPoints}
        disabled={busy}
        emptyHint="No study points yet — click Add bullet."
      />
      <BulletListEditor
        label="Learning outcomes"
        items={outcomes}
        onChange={setOutcomes}
        disabled={busy}
        emptyHint="No outcomes yet — click Add bullet."
      />
      <div className="space-y-2 rounded-lg border border-slate-200 p-3 dark:border-slate-700">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            Story Hook
          </p>
          {hookConfigured ? (
            <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-[11px] font-medium text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200">
              Configured
              {hookVisuals.length > 0
                ? ` · ${hookVisuals.length} visual${hookVisuals.length === 1 ? "" : "s"}`
                : ""}
            </span>
          ) : (
            <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-medium text-amber-900 dark:bg-amber-950 dark:text-amber-200">
              Not configured
            </span>
          )}
        </div>
        {hookPreview ? (
          <p className="line-clamp-2 text-sm text-slate-600 dark:text-slate-300">
            {hookPreview}
          </p>
        ) : (
          <p className="text-xs text-slate-500 dark:text-slate-400">
            Open the editor to author the narrative seed and supporting images.
          </p>
        )}
        <button
          type="button"
          disabled={busy}
          onClick={() => setStoryHookModalOpen(true)}
          className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm font-medium text-slate-800 hover:bg-slate-50 disabled:opacity-50 dark:border-slate-600 dark:bg-slate-950 dark:text-slate-100 dark:hover:bg-slate-900"
        >
          {hookConfigured ? "Edit Story Hook" : "Configure Story Hook"}
        </button>
      </div>
      {storyHookModalOpen ? (
        <StoryHookAuthoringModal
          conceptId={concept.id}
          conceptLabel={displayName || concept.display_name}
          topicSource={topicSource}
          token={token}
          initial={hookDraft}
          onClose={() => setStoryHookModalOpen(false)}
          onNotify={onNotify}
          onSaved={async (saved) => {
            setHookTitle(saved.title);
            setHookBody(saved.body);
            setHookIntent(saved.teacher_intent);
            setHookVisuals(saved.visuals);
            await onReload();
          }}
        />
      ) : null}
      <div className="space-y-2 rounded-lg border border-slate-200 p-3 dark:border-slate-700">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            Visual Teaching
          </p>
          {vtConfigured ? (
            <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-[11px] font-medium text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200">
              Configured
              {vtPreview ? ` · ${vtPreview}` : ""}
            </span>
          ) : (
            <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-medium text-amber-900 dark:bg-amber-950 dark:text-amber-200">
              Not configured
            </span>
          )}
        </div>
        <p className="text-xs text-slate-500 dark:text-slate-400">
          Annotate diagrams the tutor will teach from. Independent of VTSE and Story
          Hook — place it anywhere in the teaching sequence.
        </p>
        <button
          type="button"
          disabled={busy}
          onClick={() => setVisualTeachingModalOpen(true)}
          className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm font-medium text-slate-800 hover:bg-slate-50 disabled:opacity-50 dark:border-slate-600 dark:bg-slate-950 dark:text-slate-100 dark:hover:bg-slate-900"
        >
          {vtConfigured ? "Edit Visual Teaching" : "Configure Visual Teaching"}
        </button>
      </div>
      {visualTeachingModalOpen ? (
        <VisualTeachingAuthoringModal
          conceptId={concept.id}
          conceptLabel={displayName || concept.display_name}
          topicSource={topicSource}
          token={token}
          initial={vtDraft}
          onClose={() => setVisualTeachingModalOpen(false)}
          onNotify={onNotify}
          onSaved={async (saved) => {
            setVtImages(saved.images);
            await onReload();
          }}
        />
      ) : null}
      <div className="space-y-2 rounded-lg border border-slate-200 p-3 dark:border-slate-700">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            VTSE visuals
          </p>
          {vtseVisuals?.images?.length ? (
            <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-[11px] font-medium text-emerald-800">
              {vtseVisuals.images.length} image{vtseVisuals.images.length === 1 ? "" : "s"}
            </span>
          ) : (
            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-600">
              Board only
            </span>
          )}
        </div>
        <p className="text-xs text-slate-500 dark:text-slate-400">
          Optional diagrams for the VTSE stage. Regions highlight when their template slot is spoken.
        </p>
        <button
          type="button"
          disabled={busy}
          onClick={() => setVtseVisualsOpen(true)}
          className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm font-medium text-slate-800 hover:bg-slate-50 disabled:opacity-50 dark:border-slate-600 dark:bg-slate-950 dark:text-slate-100"
        >
          {vtseVisuals?.images?.length ? "Edit VTSE visuals" : "Add VTSE visuals"}
        </button>
      </div>
      {vtseVisualsOpen ? (
        <VtseVisualsAuthoringModal
          conceptId={concept.id}
          conceptLabel={displayName || concept.display_name}
          topicSource={topicSource}
          token={token}
          template={concept.vtse_template}
          initial={vtseVisuals}
          onClose={() => setVtseVisualsOpen(false)}
          onNotify={onNotify}
          onSaved={async (saved) => {
            setVtseVisuals(saved.images.length ? saved : null);
            await onReload();
          }}
        />
      ) : null}
      <div className="space-y-2 rounded-lg border border-slate-200 p-3 dark:border-slate-700">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            VTSE Template
          </p>
          {concept.vtse_template?.strategy_id ? (
            <span className="rounded-full bg-sky-100 px-2 py-0.5 text-[11px] font-medium text-sky-800 dark:bg-sky-950 dark:text-sky-200">
              {VTSE_STRATEGY_LABELS[concept.vtse_template.strategy_id] ||
                concept.vtse_template.strategy_id}
            </span>
          ) : (
            <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-medium text-amber-900 dark:bg-amber-950 dark:text-amber-200">
              Required — not set
            </span>
          )}
        </div>
        <p className="text-xs text-slate-500 dark:text-slate-400">
          Open the editor to lock the teaching layout and author outline points. DeepSeek
          expands each point into a full teacher explanation while teaching.
        </p>
        <button
          type="button"
          disabled={busy}
          onClick={() => setVtseModalOpen(true)}
          className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm font-medium text-slate-800 hover:bg-slate-50 disabled:opacity-50 dark:border-slate-600 dark:bg-slate-950 dark:text-slate-100 dark:hover:bg-slate-900"
        >
          VTSE Template
        </button>
      </div>
      {vtseModalOpen ? (
        <VtseTemplateAuthoringPage
          mode="modal"
          conceptId={concept.id}
          topicSource={topicSource}
          token={token}
          onClose={() => setVtseModalOpen(false)}
          onSaved={async () => {
            await onReload();
          }}
        />
      ) : null}
      <TeachingSequenceEditor
        sequence={teachingSequence}
        onChange={setTeachingSequence}
        disabled={busy}
        mode={teachingOrderMode}
        onModeChange={setTeachingOrderMode}
        autoOrder={listedTeachingStages(concept.teaching_sequence_auto)}
        autoStatus={concept.teaching_sequence_auto_status || ""}
        autoReason={concept.teaching_sequence_auto_reason || ""}
        autoStale={Boolean(concept.teaching_sequence_auto_stale)}
        onPreview={(regenerate) => void previewAuto(regenerate)}
      />
      <MetaRow label="Published revision" value={String(concept.published_revision)} />
      <ConceptStructuredContent
        token={token}
        topicId={topicId}
        topicSource={topicSource}
        concept={concept}
        onNotify={onNotify}
      />
    </DetailShell>
  );
}

function DetailShell({
  title,
  subtitle,
  status,
  readOnly,
  busy,
  onSave,
  onDelete,
  children,
}: {
  title: string;
  subtitle: string;
  status: string;
  readOnly: boolean;
  busy: boolean;
  onSave: () => void;
  onDelete?: () => void;
  children: ReactNode;
}) {
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-50">{title}</h2>
          <p className="text-xs text-slate-500">{subtitle}</p>
        </div>
        <span className={cn("rounded-full px-2.5 py-1 text-xs font-medium", statusBadge(status))}>
          {status}
          {readOnly ? " (locked)" : ""}
        </span>
      </div>
      <div className="space-y-3">{children}</div>
      <div className="flex flex-wrap gap-2 border-t border-slate-200 pt-4 dark:border-slate-700">
        <Button type="button" disabled={busy} onClick={onSave}>
          {busy ? "Saving…" : "Save changes"}
        </Button>
        {onDelete ? (
          <Button type="button" variant="outline" disabled={busy} onClick={onDelete}>
            <Trash2 className="mr-1 size-4" />
            Delete
          </Button>
        ) : null}
      </div>
    </div>
  );
}

function toVisualInput(v: ConceptStoryHookVisual): StoryHookVisualInput {
  return {
    id: v.id,
    asset_key: v.asset_key,
    storage_key: v.storage_key,
    description: v.description,
    teaching_purpose: v.teaching_purpose,
    mime_type: v.mime_type,
  };
}

function toVtImageInput(v: ConceptVisualTeachingImage): VisualTeachingImageInput {
  return {
    id: v.id,
    asset_key: v.asset_key,
    storage_key: v.storage_key,
    mime_type: v.mime_type,
    title: v.title,
    teaching_purpose: v.teaching_purpose,
    natural_width: v.natural_width,
    natural_height: v.natural_height,
    content_hash: v.content_hash,
    annotations_status: v.annotations_status === "stale" ? "stale" : "confirmed",
    regions: (v.regions ?? []).map((r) => ({
      region_id: r.region_id,
      label: r.label,
      teaching_purpose: r.teaching_purpose,
      shape: r.shape,
      geometry: r.geometry,
      focus_point: r.focus_point,
      label_box: r.label_box ?? null,
      highlight_color: r.highlight_color ?? null,
      label_bg_color: r.label_bg_color ?? null,
      label_text_color: r.label_text_color ?? null,
    })),
    anchors: (v.anchors ?? []).map((a) => ({
      anchor_id: a.anchor_id,
      label: a.label,
      point: a.point,
    })),
    connections: (v.connections ?? []).map((c) => ({
      connection_id: c.connection_id,
      from_anchor: c.from_anchor,
      to_anchor: c.to_anchor,
      label: c.label,
      teaching_purpose: c.teaching_purpose ?? "",
      kind: c.kind ?? "flow",
      color: c.color ?? null,
      label_bg_color: c.label_bg_color ?? null,
      label_text_color: c.label_text_color ?? null,
      label_box: c.label_box ?? null,
    })),
  };
}

type TeachingStageId = "vtse" | "story_hook" | "visual_teaching";

const VTSE_STRATEGY_LABELS: Record<string, string> = {
  hierarchy_concept_intro: "Hierarchy",
  clustered_trait_list: "Trait list",
  comparison_contrast: "Comparison",
  cycle_process: "Cycle",
  linear_process: "Linear process",
};

const TEACHING_STAGE_LABELS: Record<TeachingStageId, string> = {
  vtse: "VTSE",
  story_hook: "Story Hook",
  visual_teaching: "Visual Teaching",
};

const ALL_TEACHING_STAGES: TeachingStageId[] = [
  "vtse",
  "story_hook",
  "visual_teaching",
];

function listedTeachingStages(
  raw: Array<"vtse" | "story_hook" | "visual_teaching" | "media"> | undefined | null
): TeachingStageId[] {
  const allowed = new Set<TeachingStageId>(ALL_TEACHING_STAGES);
  return (raw ?? [])
    .map((s) => String(s).trim().toLowerCase())
    .filter((s): s is TeachingStageId => allowed.has(s as TeachingStageId));
}

function sanitizeTeachingSequence(
  raw: Array<"vtse" | "story_hook" | "visual_teaching" | "media"> | undefined | null
): TeachingStageId[] {
  const next = listedTeachingStages(raw);
  return next.length > 0 ? next : ["vtse"];
}

function TeachingSequenceEditor({
  sequence,
  onChange,
  disabled,
  mode,
  onModeChange,
  autoOrder,
  autoStatus,
  autoReason,
  autoStale,
  onPreview,
}: {
  sequence: TeachingStageId[];
  onChange: (next: TeachingStageId[]) => void;
  disabled?: boolean;
  mode: "manual" | "auto";
  onModeChange: (mode: "manual" | "auto") => void;
  autoOrder: TeachingStageId[];
  autoStatus: string;
  autoReason: string;
  autoStale: boolean;
  onPreview: (regenerate: boolean) => void;
}) {
  const locked = mode === "auto";
  function move(index: number, dir: -1 | 1) {
    const next = [...sequence];
    const j = index + dir;
    if (j < 0 || j >= next.length) return;
    const tmp = next[index]!;
    next[index] = next[j]!;
    next[j] = tmp;
    onChange(next);
  }

  function toggle(stage: TeachingStageId) {
    if (sequence.includes(stage)) {
      const next = sequence.filter((s) => s !== stage);
      onChange(next.length > 0 ? next : ["vtse"]);
      return;
    }
    onChange([...sequence, stage]);
  }

  return (
    <div className="space-y-2 rounded-lg border border-slate-200 p-3 dark:border-slate-700">
      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
        Teaching order
      </p>
      <div className="flex gap-4 text-sm">
        <label className="flex items-center gap-1.5">
          <input
            type="radio"
            name="teaching-order-mode"
            checked={mode === "manual"}
            disabled={disabled}
            onChange={() => onModeChange("manual")}
          />
          Manual
        </label>
        <label className="flex items-center gap-1.5">
          <input
            type="radio"
            name="teaching-order-mode"
            checked={mode === "auto"}
            disabled={disabled}
            onChange={() => onModeChange("auto")}
          />
          Auto
        </label>
      </div>
      <p className="text-xs text-slate-500 dark:text-slate-400">
        {locked
          ? "Auto reorders the stages you already enabled. The manual order stays saved and is used if Auto cannot resolve."
          : "Order of concept teaching stages. Callouts (Fact / Myth / Important) are not part of this sequence. VTSE, Story Hook, and Visual Teaching are independent — enable any subset and reorder freely."}
      </p>
      <ul className="space-y-2">
        {sequence.map((stage, index) => (
          <li
            key={stage}
            className="flex items-center justify-between gap-2 rounded-md border border-slate-100 bg-slate-50 px-2 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-900"
          >
            <span>
              {index + 1}. {TEACHING_STAGE_LABELS[stage]}
            </span>
            <span className="flex gap-1">
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={disabled || locked || index === 0}
                onClick={() => move(index, -1)}
              >
                ↑
              </Button>
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={disabled || locked || index === sequence.length - 1}
                onClick={() => move(index, 1)}
              >
                ↓
              </Button>
            </span>
          </li>
        ))}
      </ul>
      <div className="flex flex-wrap gap-3 pt-1">
        {ALL_TEACHING_STAGES.map((stage) => (
          <label
            key={stage}
            className="flex items-center gap-1.5 text-xs text-slate-600 dark:text-slate-300"
          >
            <input
              type="checkbox"
              checked={sequence.includes(stage)}
              disabled={disabled || locked}
              onChange={() => toggle(stage)}
            />
            {TEACHING_STAGE_LABELS[stage]}
          </label>
        ))}
      </div>
      {locked ? (
        <div className="space-y-2 border-t border-slate-200 pt-2 dark:border-slate-700">
          <p className="text-xs text-slate-600 dark:text-slate-300">
            {autoStatus === "resolved" && autoOrder.length > 0
              ? `Preview: ${autoOrder.map((stage) => TEACHING_STAGE_LABELS[stage]).join(" → ")}`
              : "No resolved Auto order yet. Students follow the manual order until preview succeeds."}
          </p>
          {autoReason ? (
            <p className="text-xs text-slate-500 dark:text-slate-400">{autoReason}</p>
          ) : null}
          {autoStale || autoStatus === "fallback" ? (
            <p className="text-xs text-amber-700 dark:text-amber-300">
              Students will follow the manual order until Preview or publish succeeds.
            </p>
          ) : null}
          <div className="flex gap-2">
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={disabled}
              onClick={() =>
                onPreview(autoStatus === "resolved" || autoStatus === "fallback")
              }
            >
              {autoStatus === "resolved" || autoStatus === "fallback" ? "Regenerate" : "Preview"}
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function Field({
  label,
  value,
  onChange,
  readOnly,
  multiline,
  inputMode,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  readOnly?: boolean;
  multiline?: boolean;
  inputMode?: "numeric" | "text";
}) {
  const className =
    "mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm disabled:opacity-60 dark:border-slate-600 dark:bg-slate-950";
  return (
    <label className="block text-xs font-medium text-slate-600 dark:text-slate-400">
      {label}
      {multiline ? (
        <textarea
          value={value}
          disabled={readOnly}
          rows={4}
          onChange={(e) => onChange(e.target.value)}
          className={className}
        />
      ) : (
        <input
          value={value}
          disabled={readOnly}
          inputMode={inputMode}
          onChange={(e) => onChange(e.target.value)}
          className={className}
        />
      )}
    </label>
  );
}

function MetaRow({ label, value }: { label: string; value: string }) {
  return (
    <p className="text-xs text-slate-600 dark:text-slate-400">
      <span className="font-medium text-slate-700 dark:text-slate-300">{label}:</span> {value}
    </p>
  );
}
