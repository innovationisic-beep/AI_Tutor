import assert from "node:assert/strict";
import test from "node:test";

import type { RenderProjection } from "@/lib/instruction-timeline-v3/renderer/projectionTypes";
import {
  layoutProcessStoryboardRows,
  measureProcessExplanationHeight,
  measureProcessNodeHeight,
  PROCESS_STORYBOARD,
  processNodeLabelWrapChars,
  processStoryboardWrapChars,
  wrapProcessExplanationLines,
  wrapProcessNodeLabelLines,
} from "@/lib/instruction-timeline-v3/teaching/processStoryboardLayout";

test("measureProcessExplanationHeight fits long digestion copy", () => {
  const explW = 420;
  const text =
    "Digestion begins in the mouth. Teeth chew the food into smaller pieces while saliva mixes with the food. "
    + "Saliva contains enzymes that start breaking down starch into simple sugars. The tongue helps push food toward the throat.";
  const h = measureProcessExplanationHeight(text, explW);
  const lines = wrapProcessExplanationLines(text, explW);
  assert.ok(h >= lines.length * 21);
  assert.ok(processStoryboardWrapChars(explW) > 38, "wide cards use more chars per line than legacy 38");
});

test("short process node labels keep min height (unchanged look)", () => {
  const label = "Mouth";
  const lines = wrapProcessNodeLabelLines(label);
  assert.equal(lines.length, 1);
  assert.equal(lines[0], "Mouth");
  assert.equal(measureProcessNodeHeight(label), PROCESS_STORYBOARD.centerNodeH);
});

test("long process node labels wrap and grow height without horizontal overflow", () => {
  const label = "Blood returns via pulmonary veins";
  const lines = wrapProcessNodeLabelLines(label);
  assert.ok(lines.length >= 2, `expected wrap for long label, got ${lines.join(" | ")}`);
  const maxChars = processNodeLabelWrapChars();
  for (const line of lines) {
    assert.ok(line.length <= maxChars, `line "${line}" exceeds wrap budget ${maxChars}`);
  }
  assert.ok(Math.max(...lines.map((l) => l.length)) < label.length);
  const h = measureProcessNodeHeight(label);
  assert.ok(h > PROCESS_STORYBOARD.centerNodeH, "node grows taller for wrapped text");
  assert.equal(PROCESS_STORYBOARD.centerNodeW, 196, "lane width stays fixed");
});

test("layoutProcessStoryboardRows grows node box for long identity labels", () => {
  const long = "Blood returns via pulmonary veins";
  const nodeProj = {
    projection_kind: "node" as const,
    projection_id: "p1",
    source_entity_id: "n1",
    label: long,
    teaching_hints: { process_identity: long },
    viewport_box: { x: 0, y: 0, w: 196, h: 52 },
  } as Extract<RenderProjection, { projection_kind: "node" }>;
  const shortProj = {
    projection_kind: "node" as const,
    projection_id: "p2",
    source_entity_id: "n2",
    label: "Mouth",
    teaching_hints: { process_identity: "Mouth" },
    viewport_box: { x: 0, y: 0, w: 196, h: 52 },
  } as Extract<RenderProjection, { projection_kind: "node" }>;
  const byId = new Map([
    ["n1", nodeProj],
    ["n2", shortProj],
  ]);
  const rows = layoutProcessStoryboardRows(["n1", "n2"], [], 960, byId);
  assert.ok(rows[0]!.nodeBox.h > PROCESS_STORYBOARD.centerNodeH);
  assert.equal(rows[0]!.nodeBox.w, PROCESS_STORYBOARD.centerNodeW);
  assert.equal(rows[1]!.nodeBox.h, PROCESS_STORYBOARD.centerNodeH);
  assert.ok(
    rows[1]!.nodeBox.y >= rows[0]!.nodeBox.y + rows[0]!.nodeBox.h,
    "second row stays below grown first node",
  );
});

test("layoutProcessStoryboardRows stacks rows without overlap", () => {
  const long =
    "Digestion begins in the mouth. Teeth chew the food into smaller pieces while saliva mixes with the food. "
    + "Saliva contains enzymes that start breaking down starch into simple sugars.";
  const rows = layoutProcessStoryboardRows(
    ["n1", "n2"],
    [
      { target_id: "n1", text: long },
      { target_id: "n2", text: "After swallowing, food moves through the esophagus." },
    ],
    960,
    new Map(),
  );
  assert.equal(rows.length, 2);
  const r0 = rows[0];
  const r1 = rows[1];
  assert.ok(r0.explanationBox);
  const r0Bottom = r0.explanationBox.y + r0.explanationBox.h;
  assert.ok(r1.nodeBox.y >= r0Bottom, "second row must start below first explanation card");
  assert.equal(r0.explanationBox.y, r0.nodeBox.y, "explanation top-aligned with identity node");
});
