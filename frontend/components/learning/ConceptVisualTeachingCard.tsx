"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { WordSyncedStreaming } from "@/components/ai/WordSyncedStreaming";
import { apiMediaUrl } from "@/lib/api/curriculumStructure";
import {
  applyVisualStatePatch,
  emptyVisualState,
  VisualTeachingStage,
  type SentenceVisualEvent,
  type VisualState,
  type VisualTeachingAnchor,
  type VisualTeachingConnection,
  type VisualTeachingRegion,
} from "@/lib/visual-teaching";
import { WHITEBOARD_TEXT_CLASS } from "@/lib/teachingTypography";
import { visualTeachingDisplayText } from "@/lib/visual-teaching/speakOnlyInk";
import { cn } from "@/lib/utils";

export type ConceptVisualTeachingCardData = {
  heading: string;
  title: string;
  speak: string;
  imagePath?: string;
  naturalWidth?: number;
  naturalHeight?: number;
  regions: VisualTeachingRegion[];
  anchors: VisualTeachingAnchor[];
  connections: VisualTeachingConnection[];
  visualState: VisualState;
  sentenceEvents: SentenceVisualEvent[];
  boardWrites?: Array<{ sentenceIndex: number; text: string }>;
  sceneIndex: number;
  beatIndex: number;
  sceneCount: number;
  beatCount: number;
  /** Restored/completed sentence cursor (-1 = beat start). */
  sentenceIndex: number;
  /** True when this is the last beat of the last scene. */
  isLastBeat: boolean;
};

export type ConceptVisualTeachingBeatView = ConceptVisualTeachingCardData & {
  id: string;
  streamStaticMode?: boolean;
  ownsCompletion?: boolean;
  onStreamComplete?: () => void;
};

export type ConceptVisualTeachingCardProps = {
  /** Single-beat legacy usage. */
  card?: ConceptVisualTeachingCardData;
  /**
   * Beats of one Visual Teaching scene. One base image is mounted once;
   * overlay + speech follow the latest beat.
   */
  beats?: ConceptVisualTeachingBeatView[];
  streamStaticMode?: boolean;
  onStreamComplete?: () => void;
  /**
   * Persist sentence progress to the session (idempotent silent background action).
   * Must include scene + beat identity so delayed callbacks cannot mutate a newer beat.
   */
  onSentencePersist?: (progress: {
    sceneIndex: number;
    beatIndex: number;
    sentenceIndex: number;
  }) => void;
};

function asRecord(v: unknown): Record<string, unknown> | null {
  return v && typeof v === "object" ? (v as Record<string, unknown>) : null;
}

function parseRegions(raw: unknown): VisualTeachingRegion[] {
  if (!Array.isArray(raw)) return [];
  const out: VisualTeachingRegion[] = [];
  for (const item of raw) {
    const r = asRecord(item);
    if (!r) continue;
    const region_id = typeof r.region_id === "string" ? r.region_id.trim() : "";
    if (!region_id) continue;
    const shapeRaw = typeof r.shape === "string" ? r.shape.trim().toLowerCase() : "rect";
    const shape =
      shapeRaw === "point" ||
      shapeRaw === "rect" ||
      shapeRaw === "ellipse" ||
      shapeRaw === "polygon"
        ? shapeRaw
        : "rect";
    out.push({
      region_id,
      label: typeof r.label === "string" ? r.label : "",
      teaching_purpose:
        typeof r.teaching_purpose === "string" ? r.teaching_purpose : "",
      sort_order: Number.isFinite(Number(r.sort_order))
        ? Math.floor(Number(r.sort_order))
        : out.length,
      shape,
      geometry:
        r.geometry && typeof r.geometry === "object"
          ? (r.geometry as VisualTeachingRegion["geometry"])
          : {},
      focus_point:
        r.focus_point && typeof r.focus_point === "object"
          ? (r.focus_point as { x: number; y: number })
          : null,
      label_box:
        r.label_box && typeof r.label_box === "object"
          ? (r.label_box as { x: number; y: number; w: number; h: number })
          : null,
      highlight_color:
        typeof r.highlight_color === "string" ? r.highlight_color : null,
      label_bg_color:
        typeof r.label_bg_color === "string" ? r.label_bg_color : null,
      label_text_color:
        typeof r.label_text_color === "string" ? r.label_text_color : null,
    });
  }
  return out;
}

function parseAnchors(raw: unknown): VisualTeachingAnchor[] {
  if (!Array.isArray(raw)) return [];
  const out: VisualTeachingAnchor[] = [];
  for (const item of raw) {
    const a = asRecord(item);
    if (!a) continue;
    const anchor_id = typeof a.anchor_id === "string" ? a.anchor_id.trim() : "";
    const point = asRecord(a.point);
    if (!anchor_id || !point) continue;
    out.push({
      anchor_id,
      label: typeof a.label === "string" ? a.label : "",
      point: { x: Number(point.x) || 0, y: Number(point.y) || 0 },
    });
  }
  return out;
}

function parseConnections(raw: unknown): VisualTeachingConnection[] {
  if (!Array.isArray(raw)) return [];
  const out: VisualTeachingConnection[] = [];
  for (const item of raw) {
    const c = asRecord(item);
    if (!c) continue;
    const connection_id =
      typeof c.connection_id === "string" ? c.connection_id.trim() : "";
    const from_anchor =
      typeof c.from_anchor === "string" ? c.from_anchor.trim() : "";
    const to_anchor = typeof c.to_anchor === "string" ? c.to_anchor.trim() : "";
    if (!connection_id || !from_anchor || !to_anchor) continue;
    const kindRaw = typeof c.kind === "string" ? c.kind.trim().toLowerCase() : "flow";
    const kind =
      kindRaw === "flow" || kindRaw === "compare" || kindRaw === "generic"
        ? kindRaw
        : "flow";
    out.push({
      connection_id,
      from_anchor,
      to_anchor,
      label: typeof c.label === "string" ? c.label : "",
      teaching_purpose:
        typeof c.teaching_purpose === "string" ? c.teaching_purpose : "",
      kind,
      color: typeof c.color === "string" ? c.color : null,
      label_bg_color:
        typeof c.label_bg_color === "string" ? c.label_bg_color : null,
      label_text_color:
        typeof c.label_text_color === "string" ? c.label_text_color : null,
      label_box: (() => {
        const lb = c.label_box;
        if (!lb || typeof lb !== "object") return null;
        const box = lb as Record<string, unknown>;
        const x = Number(box.x);
        const y = Number(box.y);
        const w = Number(box.w);
        const h = Number(box.h);
        if (![x, y, w, h].every((n) => Number.isFinite(n))) return null;
        return { x, y, w, h };
      })(),
    });
  }
  return out;
}

function parseVisualState(raw: unknown): VisualState {
  const base = emptyVisualState();
  const v = asRecord(raw);
  if (!v) return base;
  if (Array.isArray(v.highlights)) {
    base.highlights = v.highlights.filter((x): x is string => typeof x === "string");
  }
  if (Array.isArray(v.labels_visible)) {
    base.labels_visible = v.labels_visible.filter(
      (x): x is string => typeof x === "string"
    );
  }
  if (Array.isArray(v.arrows)) {
    base.arrows = v.arrows.filter((x): x is string => typeof x === "string");
  }
  if ("pointer" in v) {
    const p = v.pointer;
    base.pointer =
      p == null || (typeof p === "string" && !p.trim()) ? null : String(p);
  }
  if ("dim_others" in v) base.dim_others = Boolean(v.dim_others);
  if ("zoom" in v) {
    if (v.zoom == null) base.zoom = null;
    else {
      const z = asRecord(v.zoom);
      const rid = z && typeof z.region_id === "string" ? z.region_id.trim() : "";
      base.zoom = rid ? { region_id: rid } : null;
    }
  }
  return base;
}

export function parseConceptVisualTeachingCard(
  visual: unknown
): ConceptVisualTeachingCardData | null {
  const v = asRecord(visual);
  if (!v || v.type !== "concept_visual_teaching") return null;
  if (v.done === true) return null;

  const image = asRecord(v.image);
  const speak =
    typeof v.speak === "string"
      ? v.speak.trim()
      : typeof v.message === "string"
        ? v.message.trim()
        : "";
  const imagePath =
    typeof v.image_path === "string" ? v.image_path.trim() : "";
  const title =
    (image && typeof image.title === "string" && image.title.trim()) ||
    (typeof v.asset_key === "string" && v.asset_key.trim()) ||
    "Diagram";

  const sceneIndex = Math.max(0, Math.floor(Number(v.scene_index) || 0));
  const beatIndex = Math.max(0, Math.floor(Number(v.beat_index) || 0));
  const sceneCount = Math.max(1, Math.floor(Number(v.scene_count) || 1));
  const beatCount = Math.max(1, Math.floor(Number(v.beat_count) || 1));
  const rawSentence = Number(v.sentence_index);
  const sentenceIndex =
    Number.isFinite(rawSentence) && rawSentence >= 0
      ? Math.floor(rawSentence)
      : -1;
  const isLastBeat =
    sceneIndex >= sceneCount - 1 && beatIndex >= beatCount - 1;

  const boardWrites: Array<{ sentenceIndex: number; text: string }> = [];
  if (Array.isArray(v.writes)) {
    for (const item of v.writes) {
      const rec = asRecord(item);
      if (!rec) continue;
      const idx = Number(rec.sentence_index);
      const wtext = typeof rec.text === "string" ? rec.text.trim() : "";
      if (!Number.isFinite(idx) || idx < 0 || !wtext) continue;
      boardWrites.push({ sentenceIndex: Math.floor(idx), text: wtext });
    }
  }

  const sentenceEvents: SentenceVisualEvent[] = [];
  if (Array.isArray(v.sentence_events)) {
    for (const item of v.sentence_events) {
      const rec = asRecord(item);
      if (!rec) continue;
      const idx = Number(rec.sentence_index);
      if (!Number.isFinite(idx) || idx < 0) continue;
      const patch =
        rec.patch && typeof rec.patch === "object"
          ? (rec.patch as SentenceVisualEvent["patch"])
          : {};
      sentenceEvents.push({
        sentence_index: Math.floor(idx),
        patch,
      });
    }
  }

  if (!speak && !imagePath) return null;

  return {
    heading: "VISUAL TEACHING",
    title,
    speak,
    imagePath: imagePath || undefined,
    naturalWidth:
      image && Number.isFinite(Number(image.natural_width))
        ? Number(image.natural_width)
        : undefined,
    naturalHeight:
      image && Number.isFinite(Number(image.natural_height))
        ? Number(image.natural_height)
        : undefined,
    regions: parseRegions(v.regions),
    anchors: parseAnchors(v.anchors),
    connections: parseConnections(v.connections),
    visualState: parseVisualState(v.visual_state),
    sentenceEvents,
    boardWrites: boardWrites.length ? boardWrites : undefined,
    sceneIndex,
    beatIndex,
    sceneCount,
    beatCount,
    sentenceIndex,
    isLastBeat,
  };
}

/**
 * Student Visual Teaching scene: one base image for all beats in the scene.
 * Overlay + speech follow the latest beat; prior beat board ink accumulates.
 */
export function ConceptVisualTeachingCard({
  card,
  beats,
  streamStaticMode = false,
  onStreamComplete,
  onSentencePersist,
}: ConceptVisualTeachingCardProps) {
  const resolvedBeats: ConceptVisualTeachingBeatView[] =
    beats && beats.length > 0
      ? beats
      : card
        ? [
            {
              id: "single",
              ...card,
              streamStaticMode,
              ownsCompletion: Boolean(onStreamComplete),
              onStreamComplete,
            },
          ]
        : [];
  if (resolvedBeats.length === 0) return null;

  const latest = resolvedBeats[resolvedBeats.length - 1]!;
  const base = resolvedBeats[0]!;

  const [visualState, setVisualState] = useState<VisualState>(latest.visualState);
  const appliedUpToRef = useRef(latest.sentenceIndex);
  const persistRef = useRef(onSentencePersist);
  const beatIdentityRef = useRef({
    sceneIndex: latest.sceneIndex,
    beatIndex: latest.beatIndex,
  });
  useEffect(() => {
    persistRef.current = onSentencePersist;
  });
  useEffect(() => {
    beatIdentityRef.current = {
      sceneIndex: latest.sceneIndex,
      beatIndex: latest.beatIndex,
    };
  }, [latest.sceneIndex, latest.beatIndex, latest.id]);

  const eventsBySentence = useMemo(() => {
    const map = new Map<number, SentenceVisualEvent["patch"][]>();
    for (const ev of latest.sentenceEvents) {
      const list = map.get(ev.sentence_index) ?? [];
      list.push(ev.patch);
      map.set(ev.sentence_index, list);
    }
    return map;
  }, [latest.sentenceEvents]);

  useEffect(() => {
    setVisualState(latest.visualState);
    appliedUpToRef.current = latest.sentenceIndex;
  }, [
    latest.id,
    latest.visualState,
    latest.sceneIndex,
    latest.beatIndex,
    latest.imagePath,
    latest.sentenceIndex,
  ]);

  const onSentenceProgress = useCallback(
    (sentenceIndex: number) => {
      const { sceneIndex, beatIndex } = beatIdentityRef.current;
      if (sentenceIndex <= appliedUpToRef.current) {
        if (sentenceIndex === appliedUpToRef.current && sentenceIndex >= 0) {
          persistRef.current?.({ sceneIndex, beatIndex, sentenceIndex });
        }
        return;
      }
      setVisualState((prev) => {
        let next = prev;
        for (let si = appliedUpToRef.current + 1; si <= sentenceIndex; si++) {
          const patches = eventsBySentence.get(si);
          if (!patches) continue;
          for (const patch of patches) {
            next = applyVisualStatePatch(next, patch);
          }
        }
        return next;
      });
      appliedUpToRef.current = sentenceIndex;
      persistRef.current?.({ sceneIndex, beatIndex, sentenceIndex });
    },
    [eventsBySentence]
  );

  const priorInk = useMemo(() => {
    const lines: string[] = [];
    for (const beat of resolvedBeats.slice(0, -1)) {
      for (const w of beat.boardWrites ?? []) {
        if (w.text.trim()) lines.push(w.text.trim());
      }
    }
    return lines;
  }, [resolvedBeats]);

  const textForStream = latest.speak.trim() ? latest.speak : "\u00a0";
  const imagePath = latest.imagePath || base.imagePath;
  const hasImage = Boolean(imagePath);
  const complete =
    latest.onStreamComplete ??
    (latest.ownsCompletion ? onStreamComplete : undefined);

  return (
    <article
      className={cn(
        "mx-auto max-w-2xl rounded-2xl border-2 p-6 shadow-md md:p-8",
        "border-sky-300 bg-gradient-to-br from-sky-50 via-white to-cyan-50",
        "dark:border-sky-800 dark:from-sky-950/40 dark:via-slate-900 dark:to-cyan-950/20"
      )}
      aria-label={`${latest.heading}: ${latest.title}`}
      data-vt-scene={latest.sceneIndex}
      data-vt-beat-count={resolvedBeats.length}
    >
      <header className="border-b border-slate-200/80 pb-4 text-center dark:border-slate-700">
        <p className="text-xs font-semibold uppercase tracking-widest text-slate-500">
          {latest.heading}
        </p>
        <h3
          className={cn(
            WHITEBOARD_TEXT_CLASS,
            "mt-2 text-2xl font-bold text-slate-900 md:text-3xl dark:text-slate-50"
          )}
        >
          {latest.title}
        </h3>
        <p className="mt-1 text-[11px] text-slate-500">
          Scene {latest.sceneIndex + 1}/{latest.sceneCount} · Beat{" "}
          {latest.beatIndex + 1}/{latest.beatCount}
        </p>
      </header>

      <div className="mt-6 space-y-4">
        {hasImage ? (
          <VisualTeachingStage
            imageUrl={apiMediaUrl(imagePath!)}
            alt={latest.title}
            naturalWidth={latest.naturalWidth ?? base.naturalWidth}
            naturalHeight={latest.naturalHeight ?? base.naturalHeight}
            regions={latest.regions.length ? latest.regions : base.regions}
            anchors={latest.anchors.length ? latest.anchors : base.anchors}
            connections={
              latest.connections.length ? latest.connections : base.connections
            }
            visualState={visualState}
            svgIdScope={`scene-${latest.sceneIndex}`}
            className="aspect-[4/3] max-h-96 w-full rounded-xl"
          />
        ) : null}

        {priorInk.length > 0 ? (
          <ul className="space-y-1 text-sm text-slate-600 dark:text-slate-300">
            {priorInk.map((line, i) => (
              <li key={`prior-ink-${i}`}>{line}</li>
            ))}
          </ul>
        ) : null}

        <WordSyncedStreaming
          key={latest.id}
          text={textForStream}
          displayText={visualTeachingDisplayText(latest.boardWrites)}
          boardWrites={
            latest.boardWrites && latest.boardWrites.length
              ? latest.boardWrites
              : undefined
          }
          className={cn(WHITEBOARD_TEXT_CLASS, "text-slate-700 dark:text-slate-200")}
          staticMode={Boolean(latest.streamStaticMode ?? streamStaticMode)}
          initialSentenceIndex={latest.sentenceIndex}
          onSentenceProgress={onSentenceProgress}
          onComplete={complete}
        />
      </div>
    </article>
  );
}
