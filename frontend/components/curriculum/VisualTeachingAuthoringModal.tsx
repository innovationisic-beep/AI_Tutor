"use client";

import { useEffect, useMemo, useState } from "react";
import { X } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  normalizeVisualTeachingAssetKeys,
  updateCurriculumConcept,
  visualTeachingImageUrl,
  type VisualTeachingImageInput,
} from "@/lib/api/curriculumStructure";
import {
  emptyVisualState,
  validateRegionGeometry,
  VisualTeachingStage,
  type VisualState,
} from "@/lib/visual-teaching";
import type { CurriculumTopicSource } from "@/lib/types";
import { cn } from "@/lib/utils";
import {
  AnnotatePanel,
  ImagesPanel,
  useImageAnnotation,
} from "@/components/curriculum/ImageAnnotationEditor";

export type VisualTeachingDraft = {
  images: VisualTeachingImageInput[];
};

export function visualTeachingIsConfigured(
  draft: VisualTeachingDraft | null | undefined
): boolean {
  return Boolean(draft?.images && draft.images.length > 0);
}

export function visualTeachingPreview(
  draft: VisualTeachingDraft | null | undefined
): string {
  if (!draft?.images?.length) return "";
  const n = draft.images.length;
  const stale = draft.images.filter((i) => i.annotations_status === "stale").length;
  const parts = [`${n} image${n === 1 ? "" : "s"}`];
  if (stale) parts.push(`${stale} stale`);
  return parts.join(" · ");
}

export function validateVisualTeachingDraft(
  draft: VisualTeachingDraft
): string[] {
  const errors: string[] = [];
  const assetKeys = new Set<string>();
  for (const img of draft.images) {
    const key = (img.asset_key || "").trim();
    if (!key) {
      errors.push("Every image needs an asset key");
      continue;
    }
    if (assetKeys.has(key)) {
      errors.push(`Duplicate asset key "${key}"`);
    }
    assetKeys.add(key);
    if (img.annotations_status === "stale") {
      errors.push(
        `Image "${key}" annotations are stale — reconfirm before saving for publish`
      );
    }
    if (!(img.teaching_purpose || "").trim()) {
      errors.push(`Image "${key}" needs a teaching purpose`);
    }
    const regionIds = new Set<string>();
    for (const r of img.regions ?? []) {
      const rid = (r.region_id || "").trim();
      if (!rid) {
        errors.push(`Image "${key}" has a region without id`);
        continue;
      }
      if (regionIds.has(rid)) {
        errors.push(`Image "${key}" has duplicate region_id "${rid}"`);
      }
      regionIds.add(rid);
      const check = validateRegionGeometry(r.shape, r.geometry);
      if (!check.ok) {
        errors.push(`Image "${key}" region "${rid}": ${check.message}`);
      }
    }
    const anchorIds = new Set<string>();
    for (const a of img.anchors ?? []) {
      const aid = (a.anchor_id || "").trim();
      if (!aid) {
        errors.push(`Image "${key}" has an anchor without id`);
        continue;
      }
      if (anchorIds.has(aid)) {
        errors.push(`Image "${key}" has duplicate anchor_id "${aid}"`);
      }
      anchorIds.add(aid);
      const x = Number(a.point?.x);
      const y = Number(a.point?.y);
      if (
        !Number.isFinite(x) ||
        !Number.isFinite(y) ||
        x < 0 ||
        x > 1 ||
        y < 0 ||
        y > 1
      ) {
        errors.push(`Image "${key}" anchor "${aid}" has invalid coordinates`);
      }
    }
    const connectionIds = new Set<string>();
    for (const c of img.connections ?? []) {
      const cid = (c.connection_id || "").trim();
      if (!cid) {
        errors.push(`Image "${key}" has a connection without id`);
        continue;
      }
      if (connectionIds.has(cid)) {
        errors.push(`Image "${key}" has duplicate connection_id "${cid}"`);
      }
      connectionIds.add(cid);
      const fr = (c.from_anchor || "").trim();
      const to = (c.to_anchor || "").trim();
      if (!fr || !to || !anchorIds.has(fr) || !anchorIds.has(to)) {
        errors.push(
          `Image "${key}" connection "${cid}" references unknown anchors`
        );
      } else if (fr === to) {
        errors.push(
          `Image "${key}" connection "${cid}" is self-referential`
        );
      }
    }
  }
  return errors;
}

type VisualTeachingAuthoringModalProps = {
  conceptId: string;
  conceptLabel?: string;
  topicSource: CurriculumTopicSource;
  token: string;
  initial: VisualTeachingDraft;
  onClose: () => void;
  onSaved: (saved: VisualTeachingDraft) => void | Promise<void>;
  onNotify?: (msg: string, variant?: "ok" | "err") => void;
};

type TabId = "images" | "annotate" | "preview";

export function VisualTeachingAuthoringModal({
  conceptId,
  conceptLabel,
  topicSource,
  token,
  initial,
  onClose,
  onSaved,
  onNotify,
}: VisualTeachingAuthoringModalProps) {
  const [images, setImages] = useState<VisualTeachingImageInput[]>(() =>
    initial.images.map((img) => ({
      ...img,
      regions: (img.regions ?? []).map((r) => ({ ...r })),
      anchors: (img.anchors ?? []).map((a) => ({ ...a, point: { ...a.point } })),
      connections: (img.connections ?? []).map((c) => ({ ...c })),
    }))
  );
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [tab, setTab] = useState<TabId>("images");
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [previewState, setPreviewState] = useState<VisualState>(emptyVisualState());

  const committedKeys = useMemo(
    () => new Set(initial.images.map((i) => i.asset_key).filter(Boolean)),
    [initial.images]
  );

  const selected = images[selectedIndex] ?? null;


  function markDirty() {
    setDirty(true);
    setError(null);
  }

  function requestClose() {
    if (dirty && !confirm("Discard unsaved Visual Teaching changes?")) return;
    onClose();
  }

  async function save() {
    const draft: VisualTeachingDraft = {
      images: normalizeVisualTeachingAssetKeys(images),
    };
    const softErrors = validateVisualTeachingDraft(draft).filter(
      (e) => !e.includes("stale")
    );
    // Allow save with stale (author can reconfirm later) but block hard geometry errors.
    if (softErrors.length) {
      setError(softErrors[0]!);
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await updateCurriculumConcept(token, conceptId, {
        topic_source: topicSource,
        visual_teaching: { images: draft.images },
      });
      setImages(draft.images);
      setDirty(false);
      onNotify?.("Visual Teaching saved");
      await onSaved(draft);
      onClose();
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Save failed";
      setError(msg);
      onNotify?.(msg, "err");
    } finally {
      setSaving(false);
    }
  }


  const annotation = useImageAnnotation({
    images,
    setImages,
    selectedIndex,
    markDirty,
    active: tab === "annotate",
    onNotify,
  });

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      const mode = annotation.gesture.mode;
      if (
        mode === "drawing" ||
        mode === "moving" ||
        mode === "resizing" ||
        mode === "moving_arrow" ||
        mode === "moving_arrow_label" ||
        mode === "resizing_arrow_label"
      ) {
        e.preventDefault();
        annotation.setAnnotateGesture({ mode: "idle" });
        return;
      }
      requestClose();
    };
    window.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dirty, annotation.gesture.mode]);

  const previewHighlights = useMemo(() => {
    if (!selected?.regions?.length && !(selected?.connections ?? []).length) {
      return emptyVisualState();
    }
    return {
      ...emptyVisualState(),
      highlights: (selected?.regions ?? []).map((r) => r.region_id),
      labels_visible: (selected?.regions ?? []).map((r) => r.region_id),
      arrows: (selected?.connections ?? []).map((c) => c.connection_id),
      dim_others: false,
      ...previewState,
    };
  }, [selected, previewState]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/50 p-4 backdrop-blur-[1px]"
      role="dialog"
      aria-modal="true"
      aria-label="Visual Teaching"
      onClick={requestClose}
    >
      <div
        className="flex max-h-[94vh] w-full max-w-5xl flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl dark:border-slate-700 dark:bg-slate-950"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex shrink-0 items-start justify-between gap-3 border-b border-slate-200 px-5 py-4 dark:border-slate-700 sm:px-6">
          <div className="min-w-0">
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
              Visual Teaching
            </p>
            <h2 className="truncate text-xl font-semibold text-slate-900 dark:text-slate-50">
              {conceptLabel || "Concept"}
            </h2>
            <p className="mt-1 max-w-2xl text-sm text-slate-600 dark:text-slate-400">
              Upload diagrams and annotate regions and arrows. The tutor plans
              spoken beats against these annotations.
            </p>
          </div>
          <button
            type="button"
            onClick={requestClose}
            disabled={saving}
            className="shrink-0 rounded-lg border border-slate-200 p-2 text-slate-600 hover:bg-slate-50 disabled:opacity-50 dark:border-slate-600 dark:text-slate-300 dark:hover:bg-slate-900"
            aria-label="Close"
          >
            <X className="size-4" />
          </button>
        </div>

        <div className="flex shrink-0 gap-1 border-b border-slate-200 px-5 pt-2 dark:border-slate-700 sm:px-6">
          {(
            [
              ["images", "Images"],
              ["annotate", "Annotate"],
              ["preview", "Preview"],
            ] as const
          ).map(([id, label]) => (
            <button
              key={id}
              type="button"
              onClick={() => setTab(id)}
              className={cn(
                "rounded-t-lg px-3 py-2 text-sm font-medium",
                tab === id
                  ? "bg-slate-100 text-slate-900 dark:bg-slate-800 dark:text-slate-50"
                  : "text-slate-500 hover:text-slate-800 dark:hover:text-slate-200"
              )}
            >
              {label}
            </button>
          ))}
        </div>

        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-5 py-4 sm:px-6">
          {error ? (
            <p className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800 dark:border-rose-900 dark:bg-rose-950/40 dark:text-rose-200">
              {error}
            </p>
          ) : null}

          {tab === "images" ? (
            <ImagesPanel
              conceptId={conceptId}
              topicSource={topicSource}
              token={token}
              busy={saving}
              images={images}
              selectedIndex={selectedIndex}
              committedKeys={committedKeys}
              onSelect={setSelectedIndex}
              onChange={(next) => {
                setImages(next);
                markDirty();
                if (selectedIndex >= next.length) {
                  setSelectedIndex(Math.max(0, next.length - 1));
                }
              }}
              onNotify={onNotify}
            />
          ) : null}

          {tab !== "images" && !selected ? (
            <p className="text-sm text-slate-500">Upload an image first.</p>
          ) : null}

          {tab === "annotate" && selected ? (
            <AnnotatePanel
              conceptId={conceptId}
              image={selected}
              canPreview={committedKeys.has(selected.asset_key)}
              drawTool={annotation.drawTool}
              draftPreviewRegions={annotation.draftPreviewRegions}
              draftPreviewArrow={annotation.draftPreviewArrow}
              selectedRegionId={annotation.selectedRegionId}
              selectedConnectionId={annotation.selectedConnectionId}
              authoringCursor={annotation.authoringCursor}
              onDrawToolChange={(t) => {
                annotation.setDrawTool(t);
                annotation.setAnnotateGesture({ mode: "idle" });
                annotation.setHoverCursor(null);
              }}
              onSelectRegion={(id) => {
                annotation.setSelectedRegionId(id);
                if (id) annotation.setSelectedConnectionId(null);
              }}
              onSelectConnection={(id) => {
                annotation.setSelectedConnectionId(id);
                if (id) annotation.setSelectedRegionId(null);
              }}
              onPointerDown={annotation.onAnnotatePointerDown}
              onPointerMove={annotation.onAnnotatePointerMove}
              onPointerUp={annotation.onAnnotatePointerUp}
              onPointerCancel={annotation.onAnnotatePointerCancel}
              onPatchRegion={(regionId, patch) => {
                if (
                  patch.region_id &&
                  patch.region_id !== regionId &&
                  (selected.regions ?? []).some(
                    (r) =>
                      r.region_id !== regionId &&
                      r.region_id === patch.region_id
                  )
                ) {
                  onNotify?.(`Region id "${patch.region_id}" is already used`, "err");
                  return;
                }
                const regions = (selected.regions ?? []).map((r) =>
                  r.region_id === regionId ? { ...r, ...patch } : r
                );
                annotation.patchImage(selectedIndex, { regions });
                if (patch.region_id && patch.region_id !== regionId) {
                  annotation.setSelectedRegionId(patch.region_id);
                }
              }}
              onDeleteRegion={(regionId) => {
                annotation.patchImage(selectedIndex, {
                  regions: (selected.regions ?? []).filter(
                    (r) => r.region_id !== regionId
                  ),
                });
                if (annotation.selectedRegionId === regionId) annotation.setSelectedRegionId(null);
              }}
              onPatchConnection={(connectionId, patch) => {
                if (
                  patch.connection_id &&
                  patch.connection_id !== connectionId &&
                  (selected.connections ?? []).some(
                    (c) =>
                      c.connection_id !== connectionId &&
                      c.connection_id === patch.connection_id
                  )
                ) {
                  onNotify?.(
                    `Arrow id "${patch.connection_id}" is already used`,
                    "err"
                  );
                  return;
                }
                const connections = (selected.connections ?? []).map((c) =>
                  c.connection_id === connectionId ? { ...c, ...patch } : c
                );
                annotation.patchImage(selectedIndex, { connections });
                if (
                  patch.connection_id &&
                  patch.connection_id !== connectionId
                ) {
                  annotation.setSelectedConnectionId(patch.connection_id);
                }
              }}
              onDeleteConnection={annotation.deleteArrow}
            />
          ) : null}

          {tab === "preview" && selected ? (
            <div className="space-y-3">
              <p className="text-xs text-slate-500">
                Preview highlights all regions and arrows. Toggle dim / pointer
                below.
              </p>
              <div className="flex flex-wrap gap-2">
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={() =>
                    setPreviewState((s) => ({
                      ...s,
                      dim_others: !s.dim_others,
                    }))
                  }
                >
                  Dim others: {previewState.dim_others ? "on" : "off"}
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={() => {
                    const first = selected.regions?.[0]?.region_id ?? null;
                    setPreviewState((s) => ({
                      ...s,
                      pointer: s.pointer ? null : first,
                    }));
                  }}
                >
                  Pointer
                </Button>
              </div>
              {committedKeys.has(selected.asset_key) ? (
                <VisualTeachingStage
                  imageUrl={visualTeachingImageUrl(conceptId, selected.asset_key)}
                  alt={selected.title || selected.asset_key}
                  naturalWidth={selected.natural_width}
                  naturalHeight={selected.natural_height}
                  regions={(selected.regions ?? []).map((r) => ({
                    region_id: r.region_id,
                    label: r.label ?? "",
                    teaching_purpose: r.teaching_purpose ?? "",
                    sort_order: 0,
                    shape: r.shape,
                    geometry: r.geometry as never,
                    focus_point: r.focus_point,
                  }))}
                  anchors={(selected.anchors ?? []).map((a) => ({
                    anchor_id: a.anchor_id,
                    label: a.label ?? "",
                    point: a.point,
                  }))}
                  connections={(selected.connections ?? []).map((c) => ({
                    connection_id: c.connection_id,
                    from_anchor: c.from_anchor,
                    to_anchor: c.to_anchor,
                    label: c.label ?? "",
                    teaching_purpose: c.teaching_purpose ?? "",
                    kind: c.kind ?? "flow",
                    color: c.color ?? null,
                    label_bg_color: c.label_bg_color ?? null,
                    label_text_color: c.label_text_color ?? null,
                    label_box: c.label_box ?? null,
                  }))}
                  visualState={previewHighlights}
                  showAllOutlines
                  svgIdScope={`preview-${selected.asset_key || "image"}`}
                  className="aspect-[4/3] max-h-[50vh] w-full rounded-xl"
                />
              ) : (
                <p className="text-sm text-amber-700 dark:text-amber-300">
                  Save once to preview newly uploaded images.
                </p>
              )}
            </div>
          ) : null}
        </div>

        <div className="flex shrink-0 flex-wrap items-center gap-3 border-t border-slate-200 px-5 py-4 dark:border-slate-700 sm:px-6">
          <button
            type="button"
            disabled={saving}
            onClick={() => void save()}
            className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50 dark:bg-slate-100 dark:text-slate-900"
          >
            {saving ? "Saving…" : "Save"}
          </button>
          <button
            type="button"
            disabled={saving}
            onClick={requestClose}
            className="rounded-lg border border-slate-200 px-4 py-2 text-sm text-slate-700 dark:border-slate-600 dark:text-slate-200"
          >
            Cancel
          </button>
          {dirty ? (
            <span className="text-xs text-amber-700 dark:text-amber-300">
              Unsaved changes
            </span>
          ) : null}
        </div>
      </div>
    </div>
  );
}

