"use client";

import { useEffect, useMemo, useState } from "react";
import { X } from "lucide-react";
import {
  normalizeVisualTeachingAssetKeys,
  updateCurriculumConcept,
  uploadVtseVisualImage,
  vtseVisualImageUrl,
  type VisualTeachingImageInput,
  type VisualTeachingRegionInput,
} from "@/lib/api/curriculumStructure";
import { validateVisualTeachingDraft } from "@/components/curriculum/VisualTeachingAuthoringModal";
import {
  AnnotatePanel,
  ImagesPanel,
  useImageAnnotation,
} from "@/components/curriculum/ImageAnnotationEditor";
import type { ConceptVtseTemplate, CurriculumTopicSource, VtseVisuals } from "@/lib/types";
import {
  bindingFromSlot,
  imagesToVtsePackage,
  vtsePackageToImages,
} from "@/lib/vtse-visuals/authoring";
import { listVtseAuthorSlots } from "@/lib/vtse-visuals/slots";
import { cn } from "@/lib/utils";

const MAX_VTSE_IMAGES = 4;

type Props = {
  conceptId: string;
  conceptLabel: string;
  topicSource: CurriculumTopicSource;
  token: string;
  template: ConceptVtseTemplate | null | undefined;
  initial: VtseVisuals | null | undefined;
  onClose: () => void;
  onNotify?: (message: string, kind?: "ok" | "err") => void;
  onSaved: (saved: VtseVisuals) => void | Promise<void>;
};

export function VtseVisualsAuthoringModal({
  conceptId,
  conceptLabel,
  topicSource,
  token,
  template,
  initial,
  onClose,
  onNotify,
  onSaved,
}: Props) {
  const [images, setImages] = useState<VisualTeachingImageInput[]>(() =>
    vtsePackageToImages(initial)
  );
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [tab, setTab] = useState<"images" | "annotate">("images");
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const slots = useMemo(
    () => listVtseAuthorSlots(template, conceptLabel),
    [template, conceptLabel]
  );
  const committedKeys = useMemo(
    () => new Set((initial?.images ?? []).map((image) => image.asset_key).filter(Boolean)),
    [initial]
  );
  const selected = images[selectedIndex] ?? null;

  function markDirty() {
    setDirty(true);
    setError(null);
  }

  function requestClose() {
    if (dirty && !confirm("Discard unsaved VTSE visual changes?")) return;
    onClose();
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
      if (mode !== "idle") {
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

  async function save() {
    const draft = { images: normalizeVisualTeachingAssetKeys(images) };
    const softErrors = validateVisualTeachingDraft(draft).filter(
      (message) => !message.includes("stale") && !message.includes("teaching purpose")
    );
    if (softErrors.length) {
      setError(softErrors[0]!);
      return;
    }
    setSaving(true);
    setError(null);
    const pkg = imagesToVtsePackage(draft.images);
    try {
      await updateCurriculumConcept(token, conceptId, {
        topic_source: topicSource,
        vtse_visuals: pkg.images.length ? pkg : { images: [] },
      });
      setImages(draft.images);
      setDirty(false);
      onNotify?.("VTSE visuals saved");
      await onSaved(pkg);
      onClose();
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Save failed";
      setError(msg);
      onNotify?.(msg, "err");
    } finally {
      setSaving(false);
    }
  }

  function regionSlot(region: VisualTeachingRegionInput) {
    const binding = region.bindings?.[0];
    const value = binding
      ? `${binding.slot_key}|${binding.slot_index}|${binding.side}`
      : "";
    return (
      <label className="block text-xs">
        VTSE slot
        <select
          className="mt-1 w-full rounded border px-2 py-1 dark:border-slate-600 dark:bg-slate-950"
          value={value}
          onChange={(e) => {
            const slot = slots.find(
              (item) => `${item.slot_key}|${item.slot_index}|${item.side}` === e.target.value
            );
            const regions = (selected?.regions ?? []).map((row) =>
              row.region_id === region.region_id
                ? { ...row, bindings: slot ? [bindingFromSlot(slot)] : [] }
                : row
            );
            annotation.patchImage(selectedIndex, { regions });
          }}
        >
          <option value="">Choose a template slot</option>
          {slots.map((slot) => (
            <option
              key={`${slot.slot_key}|${slot.slot_index}|${slot.side}`}
              value={`${slot.slot_key}|${slot.slot_index}|${slot.side}`}
            >
              {slot.label}
            </option>
          ))}
        </select>
      </label>
    );
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/50 p-4 backdrop-blur-[1px]"
      role="dialog"
      aria-modal="true"
      aria-label="VTSE visuals"
      onClick={requestClose}
    >
      <div
        className="flex max-h-[94vh] w-full max-w-5xl flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl dark:border-slate-700 dark:bg-slate-950"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex shrink-0 items-start justify-between gap-3 border-b border-slate-200 px-5 py-4 dark:border-slate-700 sm:px-6">
          <div className="min-w-0">
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
              VTSE visuals
            </p>
            <h2 className="truncate text-xl font-semibold text-slate-900 dark:text-slate-50">
              {conceptLabel || "Concept"}
            </h2>
            <p className="mt-1 max-w-2xl text-sm text-slate-600 dark:text-slate-400">
              Annotate diagrams the same way as Visual Teaching. Each region also binds to one VTSE template slot.
            </p>
          </div>
          <button
            type="button"
            onClick={requestClose}
            disabled={saving}
            className="shrink-0 rounded-lg border border-slate-200 p-2 text-slate-600 hover:bg-slate-50 disabled:opacity-50 dark:border-slate-600 dark:text-slate-300"
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
                  : "text-slate-500 hover:text-slate-800"
              )}
            >
              {label}
            </button>
          ))}
        </div>
        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-5 py-4 sm:px-6">
          {error ? (
            <p className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800">
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
              maxImages={MAX_VTSE_IMAGES}
              uploadImage={uploadVtseVisualImage}
              imageUrl={vtseVisualImageUrl}
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
          {tab === "annotate" && !selected ? (
            <p className="text-sm text-slate-500">Upload an image first.</p>
          ) : null}
          {tab === "annotate" && selected ? (
            <AnnotatePanel
              conceptId={conceptId}
              image={selected}
              canPreview={committedKeys.has(selected.asset_key)}
              imageUrl={vtseVisualImageUrl}
              drawTool={annotation.drawTool}
              draftPreviewRegions={annotation.draftPreviewRegions}
              draftPreviewArrow={annotation.draftPreviewArrow}
              selectedRegionId={annotation.selectedRegionId}
              selectedConnectionId={annotation.selectedConnectionId}
              authoringCursor={annotation.authoringCursor}
              regionExtra={regionSlot}
              onDrawToolChange={(tool) => {
                annotation.setDrawTool(tool);
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
                    (region) => region.region_id !== regionId && region.region_id === patch.region_id
                  )
                ) {
                  onNotify?.(`Region id "${patch.region_id}" is already used`, "err");
                  return;
                }
                const regions = (selected.regions ?? []).map((region) =>
                  region.region_id === regionId ? { ...region, ...patch } : region
                );
                annotation.patchImage(selectedIndex, { regions });
                if (patch.region_id && patch.region_id !== regionId) {
                  annotation.setSelectedRegionId(patch.region_id);
                }
              }}
              onDeleteRegion={(regionId) => {
                annotation.patchImage(selectedIndex, {
                  regions: (selected.regions ?? []).filter((region) => region.region_id !== regionId),
                });
                if (annotation.selectedRegionId === regionId) annotation.setSelectedRegionId(null);
              }}
              onPatchConnection={(connectionId, patch) => {
                if (
                  patch.connection_id &&
                  patch.connection_id !== connectionId &&
                  (selected.connections ?? []).some(
                    (connection) =>
                      connection.connection_id !== connectionId &&
                      connection.connection_id === patch.connection_id
                  )
                ) {
                  onNotify?.(`Arrow id "${patch.connection_id}" is already used`, "err");
                  return;
                }
                const connections = (selected.connections ?? []).map((connection) =>
                  connection.connection_id === connectionId ? { ...connection, ...patch } : connection
                );
                annotation.patchImage(selectedIndex, { connections });
                if (patch.connection_id && patch.connection_id !== connectionId) {
                  annotation.setSelectedConnectionId(patch.connection_id);
                }
              }}
              onDeleteConnection={annotation.deleteArrow}
            />
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
            <span className="text-xs text-amber-700 dark:text-amber-300">Unsaved changes</span>
          ) : null}
        </div>
      </div>
    </div>
  );
}
