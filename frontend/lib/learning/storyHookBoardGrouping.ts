import type { BoardItem } from "@/components/ai/AIWhiteboard";
import {
  parseConceptStoryHookCard,
  type ConceptStoryHookCardData,
} from "@/components/learning/ConceptStoryHookCard";
import {
  parseConceptVisualTeachingCard,
  type ConceptVisualTeachingCardData,
} from "@/components/learning/ConceptVisualTeachingCard";
// BoardItem is type-only — avoids a runtime cycle with AIWhiteboard.

/** One authored Story Hook step as rendered inside a shared card shell. */
export type StoryHookBoardStep = ConceptStoryHookCardData & {
  /** Stable board-item id — used as React key and for dedupe. */
  id: string;
};

/** One Visual Teaching beat inside a single-scene run (shared base image). */
export type VisualTeachingBeatStep = ConceptVisualTeachingCardData & {
  id: string;
  streamStaticMode?: boolean;
  ownsCompletion?: boolean;
};

/**
 * Whiteboard segments after collapsing consecutive Story Hook / Visual Teaching runs.
 *
 * Story Hook: consecutive `concept_story_hook` items → one card shell.
 * Visual Teaching: consecutive `concept_visual_teaching` items with the same
 * `scene_index` (fallback: `asset_key`) → one persistent image + overlay updates.
 */
export type WhiteboardSegment =
  | { kind: "item"; item: BoardItem }
  | { kind: "story_hook_run"; items: BoardItem[]; steps: StoryHookBoardStep[] }
  | {
      kind: "visual_teaching_scene";
      items: BoardItem[];
      beats: VisualTeachingBeatStep[];
    };

export function isStoryHookBoardVisual(visual: unknown): boolean {
  if (!visual || typeof visual !== "object") return false;
  return (visual as { type?: unknown }).type === "concept_story_hook";
}

export function isStoryHookBoardItem(item: BoardItem): boolean {
  return isStoryHookBoardVisual(item.visual);
}

export function isVisualTeachingBoardVisual(visual: unknown): boolean {
  if (!visual || typeof visual !== "object") return false;
  return (visual as { type?: unknown }).type === "concept_visual_teaching";
}

export function isVisualTeachingBoardItem(item: BoardItem): boolean {
  return isVisualTeachingBoardVisual(item.visual);
}

/** Scene identity for grouping — prefer scene_index, else asset_key. */
export function visualTeachingSceneKey(visual: unknown): string {
  if (!visual || typeof visual !== "object") return "";
  const v = visual as Record<string, unknown>;
  if (v.done === true) return "__done__";
  const si = Number(v.scene_index);
  if (Number.isFinite(si) && si >= 0) return `scene:${Math.floor(si)}`;
  const asset = typeof v.asset_key === "string" ? v.asset_key.trim() : "";
  return asset ? `asset:${asset}` : "scene:unknown";
}

/**
 * Build ordered step views for a consecutive Story Hook run.
 * Skips items that fail card parse (should not happen for valid payloads).
 * Dedupes by board item id so React remounts / refreshes stay stable.
 */
export function storyHookStepsFromItems(items: BoardItem[]): StoryHookBoardStep[] {
  const seen = new Set<string>();
  const steps: StoryHookBoardStep[] = [];
  for (const item of items) {
    if (seen.has(item.id)) continue;
    const card = parseConceptStoryHookCard(item.visual);
    if (!card) continue;
    seen.add(item.id);
    steps.push({ id: item.id, ...card });
  }
  return steps;
}

export function visualTeachingBeatsFromItems(
  items: BoardItem[]
): VisualTeachingBeatStep[] {
  const seen = new Set<string>();
  const beats: VisualTeachingBeatStep[] = [];
  for (const item of items) {
    if (seen.has(item.id)) continue;
    const card = parseConceptVisualTeachingCard(item.visual);
    if (!card) continue;
    seen.add(item.id);
    beats.push({ id: item.id, ...card });
  }
  return beats;
}

/**
 * Collapse consecutive Story Hook board items into one segment each.
 * Collapse consecutive Visual Teaching beats of the same scene into one segment.
 * Other items stay as single-item segments (VTSE, pedagogy, prose, …).
 */
export function groupWhiteboardSegments(items: BoardItem[]): WhiteboardSegment[] {
  const segments: WhiteboardSegment[] = [];
  let i = 0;
  while (i < items.length) {
    const item = items[i];
    if (isStoryHookBoardItem(item)) {
      const run: BoardItem[] = [];
      while (i < items.length && isStoryHookBoardItem(items[i])) {
        run.push(items[i]);
        i += 1;
      }
      segments.push({
        kind: "story_hook_run",
        items: run,
        steps: storyHookStepsFromItems(run),
      });
      continue;
    }
    if (isVisualTeachingBoardItem(item)) {
      const sceneKey = visualTeachingSceneKey(item.visual);
      const run: BoardItem[] = [];
      while (
        i < items.length &&
        isVisualTeachingBoardItem(items[i]) &&
        visualTeachingSceneKey(items[i].visual) === sceneKey
      ) {
        run.push(items[i]);
        i += 1;
      }
      segments.push({
        kind: "visual_teaching_scene",
        items: run,
        beats: visualTeachingBeatsFromItems(run),
      });
      continue;
    }
    segments.push({ kind: "item", item });
    i += 1;
  }
  return segments;
}

/** Header title for a run — first non-empty title in chronological order. */
export function storyHookRunTitle(steps: StoryHookBoardStep[]): string {
  for (const step of steps) {
    const t = step.title?.trim();
    if (t) return t;
  }
  return "Story Hook";
}

export function storyHookRunHeading(steps: StoryHookBoardStep[]): string {
  for (const step of steps) {
    const h = step.heading?.trim();
    if (h) return h;
  }
  return "STORY HOOK";
}

export type StoryHookStreamAttachOpts = {
  lastBoardItemId: string | null;
  /** Board item ids that should render in restore/static mode (no TTS). */
  staticRestoreByItemId?: Record<string, number>;
};

export type StoryHookStreamedStep = StoryHookBoardStep & {
  streamText: string;
  /** Visible writing for WSS; undefined = legacy reveal of streamText. */
  displayText?: string;
  /** Sentence-anchored writes when present. */
  boardWrites?: Array<{ sentenceIndex: number; text: string }>;
  streamStaticMode: boolean;
  /** True when this step should own onLastItemComplete (caller wires the callback). */
  ownsCompletion: boolean;
};

/**
 * Attach WordSyncedStreaming props for a Story Hook run.
 *
 * - `streamText` comes from the board item content (spoken TTS source).
 * - `displayText` from card note/body rules when writing_mode is notes.
 * - `boardWrites` from card writes when present (preferred reveal path).
 * - `streamStaticMode` is restore-only — never set merely because a step is no
 *   longer last (flipping it would remount the effect and cancelSpeech).
 * - Only the global last board item owns completion / advance.
 */
export function attachStoryHookStepStreaming(
  steps: StoryHookBoardStep[],
  runItems: BoardItem[],
  opts: StoryHookStreamAttachOpts
): StoryHookStreamedStep[] {
  const byId = new Map(runItems.map((it) => [it.id, it]));
  return steps.map((step) => {
    const item = byId.get(step.id);
    const itemRestoreMode =
      item != null && opts.staticRestoreByItemId?.[item.id] !== undefined;
    const isGlobalLast = item?.id === opts.lastBoardItemId;
    const spoken =
      item?.content?.trim() ||
      step.spokenText?.trim() ||
      step.body ||
      "\u00a0";
    const streamText = spoken;
    const mode = step.writingMode;
    let displayText: string | undefined;
    let boardWrites: Array<{ sentenceIndex: number; text: string }> | undefined;
    if (mode === "notes") {
      // Notes mode: visible = body (already resolved note or "" on server).
      // Empty body → speak-only (displayText "") unless boardWrites present.
      displayText = step.body ?? "";
      if (step.boardWrites && step.boardWrites.length) {
        boardWrites = step.boardWrites;
      }
    } else {
      // Legacy / unspecified: reveal spoken text (omit displayText).
      displayText = undefined;
    }
    return {
      ...step,
      streamText,
      displayText,
      ...(boardWrites ? { boardWrites } : {}),
      streamStaticMode: itemRestoreMode,
      ownsCompletion: Boolean(isGlobalLast && !itemRestoreMode),
    };
  });
}

export type VisualTeachingStreamAttachOpts = {
  lastBoardItemId: string | null;
  staticRestoreByItemId?: Record<string, number>;
};

/**
 * Attach streaming flags for a Visual Teaching scene run.
 * Only the latest beat speaks live; prior beats contribute static board ink.
 *
 * Note: prior beats get streamStaticMode=true when a newer beat arrives. That is
 * intentional for VT (unlike Story Hook) because we only mount the latest WSS
 * for speech — prior ink is rendered statically, not via flipped live WSS.
 *
 * Restore: the active (last) beat always owns completion and resumes live TTS
 * from the persisted sentence cursor so mid-beat / uncommitted-advance restores
 * cannot become dead ends (static with no future callback).
 */
export function attachVisualTeachingBeatStreaming(
  beats: VisualTeachingBeatStep[],
  runItems: BoardItem[],
  opts: VisualTeachingStreamAttachOpts
): VisualTeachingBeatStep[] {
  const byId = new Map(runItems.map((it) => [it.id, it]));
  return beats.map((beat, index) => {
    const item = byId.get(beat.id);
    const itemRestoreMode =
      item != null && opts.staticRestoreByItemId?.[item.id] !== undefined;
    const isGlobalLast = item?.id === opts.lastBoardItemId;
    const isLatestInScene = index === beats.length - 1;
    const isActiveBeat = Boolean(isGlobalLast && isLatestInScene);
    return {
      ...beat,
      // Prior restored beats stay static; the active beat always resumes live.
      streamStaticMode: Boolean(itemRestoreMode && !isActiveBeat),
      ownsCompletion: isActiveBeat,
    };
  });
}
