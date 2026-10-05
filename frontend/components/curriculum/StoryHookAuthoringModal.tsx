"use client";

import { useEffect, useState } from "react";
import { Loader2, Plus, Trash2, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { AuthImage } from "@/components/media/AuthImage";
import {
  normalizeStoryHookVisualAssetKeys,
  storyHookVisualUrl,
  updateCurriculumConcept,
  uploadStoryHookVisual,
  type StoryHookVisualInput,
} from "@/lib/api/curriculumStructure";
import type { CurriculumTopicSource } from "@/lib/types";
import { cn } from "@/lib/utils";

export type StoryHookDraft = {
  title: string;
  body: string;
  teacher_intent: string;
  visuals: StoryHookVisualInput[];
};

export function storyHookIsConfigured(hook: StoryHookDraft | null | undefined): boolean {
  if (!hook) return false;
  return Boolean(
    hook.title.trim() ||
      hook.body.trim() ||
      hook.teacher_intent.trim() ||
      (hook.visuals && hook.visuals.length > 0)
  );
}

export function storyHookSeedPreview(body: string, max = 140): string {
  const text = body.trim().replace(/\s+/g, " ");
  if (!text) return "";
  if (text.length <= max) return text;
  return `${text.slice(0, max - 1)}…`;
}

type StoryHookAuthoringModalProps = {
  conceptId: string;
  conceptLabel?: string;
  topicSource: CurriculumTopicSource;
  token: string;
  /** Committed builder values — copied into a local draft on open. */
  initial: StoryHookDraft;
  onClose: () => void;
  /** Called after a successful API save with the normalized hook. */
  onSaved: (saved: StoryHookDraft) => void | Promise<void>;
  onNotify?: (msg: string, variant?: "ok" | "err") => void;
};

export function StoryHookAuthoringModal({
  conceptId,
  conceptLabel,
  topicSource,
  token,
  initial,
  onClose,
  onSaved,
  onNotify,
}: StoryHookAuthoringModalProps) {
  const [title, setTitle] = useState(initial.title);
  const [body, setBody] = useState(initial.body);
  const [intent, setIntent] = useState(initial.teacher_intent);
  const [visuals, setVisuals] = useState<StoryHookVisualInput[]>(() =>
    initial.visuals.map((v) => ({ ...v }))
  );
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") requestClose();
    };
    window.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- close handler uses latest dirty via requestClose
  }, [dirty]);

  function markDirty() {
    setDirty(true);
    setError(null);
  }

  function requestClose() {
    if (dirty && !confirm("Discard unsaved Story Hook changes?")) return;
    onClose();
  }

  async function save() {
    setSaving(true);
    setError(null);
    try {
      const savedVisuals = normalizeStoryHookVisualAssetKeys(visuals);
      const story_hook = {
        title: title.trim(),
        body: body.trim(),
        teacher_intent: intent.trim(),
        visuals: savedVisuals,
      };
      await updateCurriculumConcept(token, conceptId, {
        topic_source: topicSource,
        story_hook,
      });
      const saved: StoryHookDraft = {
        title: story_hook.title,
        body: story_hook.body,
        teacher_intent: story_hook.teacher_intent,
        visuals: savedVisuals,
      };
      setTitle(saved.title);
      setBody(saved.body);
      setIntent(saved.teacher_intent);
      setVisuals(saved.visuals);
      setDirty(false);
      onNotify?.("Story Hook saved");
      await onSaved(saved);
      onClose();
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Save failed";
      setError(msg);
      onNotify?.(msg, "err");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/50 p-4 backdrop-blur-[1px]"
      role="dialog"
      aria-modal="true"
      aria-label="Story Hook"
      onClick={requestClose}
    >
      <div
        className="flex max-h-[92vh] w-full max-w-3xl flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl dark:border-slate-700 dark:bg-slate-950"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex shrink-0 items-start justify-between gap-3 border-b border-slate-200 px-5 py-4 dark:border-slate-700 sm:px-6">
          <div className="min-w-0">
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
              Story Hook
            </p>
            <h2 className="truncate text-xl font-semibold text-slate-900 dark:text-slate-50">
              {conceptLabel || "Concept"}
            </h2>
            <p className="mt-1 max-w-xl text-sm text-slate-600 dark:text-slate-400">
              Author the narrative seed and supporting images. The tutor expands the seed
              using the VTSE template as its factual source.
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

        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-5 py-4 sm:px-6">
          {error ? (
            <p className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800 dark:border-rose-900 dark:bg-rose-950/40 dark:text-rose-200">
              {error}
            </p>
          ) : null}

          <label className="block text-xs font-medium text-slate-600 dark:text-slate-400">
            Title
            <input
              value={title}
              onChange={(e) => {
                setTitle(e.target.value);
                markDirty();
              }}
              disabled={saving}
              className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm dark:border-slate-600 dark:bg-slate-950"
              placeholder="Short hook title"
            />
          </label>

          <label className="block text-xs font-medium text-slate-600 dark:text-slate-400">
            Seed
            <textarea
              value={body}
              onChange={(e) => {
                setBody(e.target.value);
                markDirty();
              }}
              rows={5}
              disabled={saving}
              className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm dark:border-slate-600 dark:bg-slate-950"
              placeholder="The analogy or narrative direction to build from…"
            />
          </label>
          <p className="-mt-2 text-xs text-slate-500 dark:text-slate-400">
            This is a seed, not final narration.
          </p>

          <label className="block text-xs font-medium text-slate-600 dark:text-slate-400">
            Teaching intent (optional)
            <textarea
              value={intent}
              onChange={(e) => {
                setIntent(e.target.value);
                markDirty();
              }}
              rows={2}
              disabled={saving}
              className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm dark:border-slate-600 dark:bg-slate-950"
              placeholder="What should this hook emphasise?"
            />
          </label>

          <StoryHookVisualsEditor
            conceptId={conceptId}
            topicSource={topicSource}
            token={token}
            busy={saving}
            visuals={visuals}
            committedAssetKeys={new Set(
              initial.visuals.map((v) => v.asset_key).filter(Boolean)
            )}
            onChange={(next) => {
              setVisuals(next);
              markDirty();
            }}
            onNotify={onNotify}
          />
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

function StoryHookVisualsEditor({
  conceptId,
  topicSource,
  token,
  busy,
  visuals,
  committedAssetKeys,
  onChange,
  onNotify,
}: {
  conceptId: string;
  topicSource: CurriculumTopicSource;
  token: string;
  busy: boolean;
  visuals: StoryHookVisualInput[];
  /** Asset keys already on the saved concept — safe for authenticated GET. */
  committedAssetKeys: Set<string>;
  onChange: (next: StoryHookVisualInput[]) => void;
  onNotify?: (msg: string, variant?: "ok" | "err") => void;
}) {
  const [uploading, setUploading] = useState(false);

  async function addFiles(files: FileList | null) {
    if (!files || files.length === 0) return;
    setUploading(true);
    try {
      const added: StoryHookVisualInput[] = [];
      for (const file of Array.from(files)) {
        const up = await uploadStoryHookVisual(token, conceptId, topicSource, file);
        added.push({
          id: up.id,
          asset_key: up.asset_key,
          storage_key: up.storage_key,
          description: "",
          teaching_purpose: "",
          mime_type: up.mime_type,
        });
      }
      onChange([...visuals, ...added]);
      onNotify?.(
        `${added.length} visual${added.length === 1 ? "" : "s"} uploaded — save Story Hook to attach.`
      );
    } catch (e) {
      onNotify?.(e instanceof Error ? e.message : "Upload failed", "err");
    } finally {
      setUploading(false);
    }
  }

  function patch(index: number, patchValue: Partial<StoryHookVisualInput>) {
    onChange(visuals.map((v, i) => (i === index ? { ...v, ...patchValue } : v)));
  }

  return (
    <div className="space-y-3 rounded-xl border border-slate-200 p-3 dark:border-slate-700">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
          Supporting visuals
        </p>
        <label
          className={cn(
            "inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 dark:border-slate-600 dark:text-slate-200 dark:hover:bg-slate-800",
            (busy || uploading) && "pointer-events-none opacity-50"
          )}
        >
          {uploading ? (
            <Loader2 className="size-3.5 animate-spin" />
          ) : (
            <Plus className="size-3.5" />
          )}
          Add image
          <input
            type="file"
            accept="image/jpeg,image/png,image/webp"
            multiple
            className="hidden"
            disabled={busy || uploading}
            onChange={(e) => {
              void addFiles(e.target.files);
              e.target.value = "";
            }}
          />
        </label>
      </div>
      <p className="text-xs text-slate-500 dark:text-slate-400">
        Every attached visual is used exactly once in the story. Describe each one — the
        tutor decides where it belongs from these descriptions, not the filename. JPEG,
        PNG or WebP up to 5 MB.
      </p>
      {visuals.length === 0 ? (
        <p className="text-xs text-slate-500 dark:text-slate-400">No visuals attached.</p>
      ) : (
        <ul className="max-h-[40vh] space-y-3 overflow-y-auto pr-1">
          {visuals.map((visual, index) => {
            const canPreview = committedAssetKeys.has(visual.asset_key);
            return (
              <li
                key={visual.id ?? visual.storage_key}
                className="flex gap-3 rounded-md border border-slate-100 bg-slate-50 p-2 dark:border-slate-700 dark:bg-slate-900"
              >
                {canPreview ? (
                  <AuthImage
                    src={storyHookVisualUrl(conceptId, visual.asset_key)}
                    alt={visual.description || visual.asset_key}
                    className="size-20 shrink-0 rounded object-cover"
                  />
                ) : (
                  <div
                    className="flex size-20 shrink-0 items-center justify-center rounded bg-slate-200/80 text-center text-[10px] leading-tight text-slate-500 dark:bg-slate-800 dark:text-slate-400"
                    title="Save Story Hook to attach and preview"
                  >
                    Pending
                    <br />
                    save
                  </div>
                )}
                <div className="min-w-0 flex-1 space-y-1.5">
                  <input
                    value={visual.asset_key}
                    onChange={(e) => patch(index, { asset_key: e.target.value })}
                    disabled={busy}
                    placeholder="asset key, e.g. stomata_surface"
                    className="w-full rounded border border-slate-200 px-2 py-1 font-mono text-xs dark:border-slate-600 dark:bg-slate-950"
                  />
                  <textarea
                    value={visual.description ?? ""}
                    onChange={(e) => patch(index, { description: e.target.value })}
                    rows={2}
                    disabled={busy}
                    placeholder="What the image shows"
                    className="w-full rounded border border-slate-200 px-2 py-1 text-xs dark:border-slate-600 dark:bg-slate-950"
                  />
                  <input
                    value={visual.teaching_purpose ?? ""}
                    onChange={(e) => patch(index, { teaching_purpose: e.target.value })}
                    disabled={busy}
                    placeholder="Why it helps the student"
                    className="w-full rounded border border-slate-200 px-2 py-1 text-xs dark:border-slate-600 dark:bg-slate-950"
                  />
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={busy}
                  onClick={() => onChange(visuals.filter((_, i) => i !== index))}
                  aria-label={`Remove ${visual.asset_key}`}
                >
                  <Trash2 className="size-4" />
                </Button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
