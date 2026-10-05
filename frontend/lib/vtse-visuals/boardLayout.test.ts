/**
 * VTSE visual width: only a timeline with a package leaves the centered column.
 * Run: npx tsx --test lib/vtse-visuals/boardLayout.test.ts
 */
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import {
  VTSE_VISUAL_BOARD_PERCENT,
  VTSE_VISUAL_PANE_PERCENT,
  VTSE_VISUAL_SPLIT_MIN_PX,
  VTSE_VISUAL_WIDE_CLASS,
  WHITEBOARD_CONTENT_COLUMN_CLASS,
  timelineHasVtseVisualPackage,
  vtseVisualFlowMode,
  vtseVisualWidthMode,
} from "./boardLayout";

const here = dirname(fileURLToPath(import.meta.url));
const frontendRoot = join(here, "..", "..");

function source(rel: string): string {
  return readFileSync(join(frontendRoot, rel), "utf8");
}

test("no package and empty images stay on the centered column", () => {
  assert.equal(timelineHasVtseVisualPackage(null), false);
  assert.equal(timelineHasVtseVisualPackage({}), false);
  assert.equal(timelineHasVtseVisualPackage({ metadata: {} }), false);
  assert.equal(
    timelineHasVtseVisualPackage({ metadata: { vtse_visual_package: { images: [] } } }),
    false
  );
  assert.equal(
    vtseVisualWidthMode({ hasPackage: false, showVisuals: true }),
    "column"
  );
  assert.equal(
    vtseVisualFlowMode({ hasPackage: false, showVisuals: true, containerWidth: 1600 }),
    "board"
  );
});

test("a package opts into the wide item, including on a wide container", () => {
  assert.equal(
    timelineHasVtseVisualPackage({
      metadata: { vtse_visual_package: { images: [{ asset_key: "a" }] } },
    }),
    true
  );
  assert.equal(vtseVisualWidthMode({ hasPackage: true, showVisuals: true }), "wide");
  assert.equal(
    vtseVisualFlowMode({ hasPackage: true, showVisuals: true, containerWidth: 1400 }),
    "split"
  );
  assert.equal(VTSE_VISUAL_BOARD_PERCENT + VTSE_VISUAL_PANE_PERCENT, 100);
  assert.equal(VTSE_VISUAL_BOARD_PERCENT, 70);
  assert.equal(VTSE_VISUAL_PANE_PERCENT, 30);
});

test("reteach and a failed image keep the single board", () => {
  assert.equal(
    vtseVisualWidthMode({ hasPackage: true, showVisuals: false }),
    "column"
  );
  assert.equal(
    vtseVisualFlowMode({
      hasPackage: true,
      showVisuals: false,
      containerWidth: 1600,
    }),
    "board"
  );
  assert.equal(
    vtseVisualFlowMode({
      hasPackage: true,
      showVisuals: true,
      containerWidth: 1600,
      imageUnavailable: true,
    }),
    "board"
  );
});

test("narrow container stacks instead of a tiny side column", () => {
  assert.equal(
    vtseVisualFlowMode({
      hasPackage: true,
      showVisuals: true,
      containerWidth: VTSE_VISUAL_SPLIT_MIN_PX - 1,
    }),
    "stack"
  );
  assert.equal(
    vtseVisualFlowMode({
      hasPackage: true,
      showVisuals: true,
      containerWidth: VTSE_VISUAL_SPLIT_MIN_PX,
    }),
    "split"
  );
});

test("FlowCheckpoint does not change the width mode", () => {
  const open = vtseVisualWidthMode({ hasPackage: true, showVisuals: true });
  const held = vtseVisualWidthMode({ hasPackage: true, showVisuals: true });
  assert.equal(open, held);
  assert.equal(open, "wide");
  const view = source("components/ai/timeline-v3/ProductionTimelineRuntimeView.tsx");
  const gate = view.indexOf("const vtseVisualBesideBoard");
  assert.ok(gate > 0);
  const block = view.slice(gate, view.indexOf("const outerShellClass"));
  assert.match(block, /vtseHasVisualPackage/);
  assert.match(view, /timelineHasVtseVisualPackage\(timeline\)/);
  assert.doesNotMatch(block, /flowCheckpoint/);
});

test("whiteboard width is per item, and only VTSE-with-visuals leaves the column", () => {
  const board = source("components/ai/AIWhiteboard.tsx");
  assert.match(board, /className="w-full min-w-0"/);
  assert.doesNotMatch(board, /className="mx-auto max-w-6xl"/);
  assert.match(board, /WHITEBOARD_CONTENT_COLUMN_CLASS/);
  assert.match(board, /VTSE_VISUAL_WIDE_CLASS/);
  assert.match(board, /timelineHasVtseVisualPackage\(decision\.timeline\)/);
  assert.match(board, /showVtseVisuals &&/);
  const story = board.indexOf('segment.kind === "story_hook_run"');
  const visual = board.indexOf('segment.kind === "visual_teaching_scene"');
  const wide = board.indexOf("const wideVtseVisual");
  assert.ok(story > 0 && visual > story && wide > visual);
  const storyBlock = board.slice(story, visual);
  const visualBlock = board.slice(visual, wide);
  assert.match(storyBlock, /WHITEBOARD_CONTENT_COLUMN_CLASS/);
  assert.doesNotMatch(storyBlock, /VTSE_VISUAL_WIDE_CLASS/);
  assert.match(visualBlock, /WHITEBOARD_CONTENT_COLUMN_CLASS/);
  assert.doesNotMatch(visualBlock, /VTSE_VISUAL_WIDE_CLASS/);
  assert.match(board, /data-whiteboard-width="column"/);
  assert.match(board, /data-whiteboard-width=\{wideVtseVisual \? "vtse-visual" : "column"\}/);
  assert.equal(WHITEBOARD_CONTENT_COLUMN_CLASS.includes("max-w-6xl"), true);
  assert.equal(VTSE_VISUAL_WIDE_CLASS.includes("max-w-6xl"), false);
  assert.equal(VTSE_VISUAL_WIDE_CLASS.includes("w-full"), true);
});

test("the companion is a grid cell beside the board, and the board cannot cover it", () => {
  const companion = source("components/ai/timeline-v3/VtseVisualCompanion.tsx");
  assert.doesNotMatch(companion, /absolute bottom-3 right-3/);
  assert.doesNotMatch(companion, /h-40 w-56/);
  assert.doesNotMatch(companion, /position:\s*sticky/);
  assert.match(companion, /data-testid="vtse-visual-companion"/);
  const view = source("components/ai/timeline-v3/ProductionTimelineRuntimeView.tsx");
  assert.match(view, /minmax\(0, 7fr\) minmax\(20rem, 3fr\)/);
  assert.match(view, /overflow: "hidden"/);
  assert.match(view, /zIndex: 1/);
  assert.doesNotMatch(view, /position:\s*sticky/);
  assert.match(view, /className="relative"/);
  assert.equal(VTSE_VISUAL_SPLIT_MIN_PX >= 1080, true);
});
