import { instructionLifecycleDebugEnabled } from "@/lib/learning/instructionLifecycle";
import type { RenderProjection } from "@/lib/instruction-timeline-v3/renderer/projectionTypes";

export function logProjectionState(
  projections: RenderProjection[],
  detail?: Record<string, unknown>,
): void {
  if (!instructionLifecycleDebugEnabled()) return;
  const nodes = projections.filter((p) => p.projection_kind === "node");
  const edges = projections.filter((p) => p.projection_kind === "edge");
  const annotations = projections.filter((p) => p.projection_kind === "annotation");
  // eslint-disable-next-line no-console
  console.info(
    `[PROJECTION_STATE] entity_count=${nodes.length} edge_count=${edges.length} annotation_count=${annotations.length} projection_ids=${projections.map((p) => p.projection_id).join(",")}${detail ? ` ${JSON.stringify(detail)}` : ""}`,
  );
}

export function logVisibleRender(projections: RenderProjection[]): void {
  if (!instructionLifecycleDebugEnabled()) return;
  const visible = projections.filter((p) => p.visible);
  const nodes = visible.filter((p) => p.projection_kind === "node");
  const edges = visible.filter((p) => p.projection_kind === "edge");
  const annotations = visible.filter((p) => p.projection_kind === "annotation");
  const hidden = projections.length - visible.length;
  // eslint-disable-next-line no-console
  console.info(
    `[VISIBLE_RENDER] visible_entities=${nodes.length} visible_edges=${edges.length} visible_annotations=${annotations.length} hidden=${hidden}`,
  );
}

export function logSvgRender(payload: {
  viewBox: string;
  scale: number | null;
  translate: { tx: number; ty: number } | null;
  svg_bounds: { width: number; height: number };
}): void {
  if (!instructionLifecycleDebugEnabled()) return;
  // eslint-disable-next-line no-console
  console.info(`[SVG_RENDER] ${JSON.stringify(payload)}`);
}

export function logEntityRender(
  projection: RenderProjection,
  box: { x: number; y: number; w: number; h: number },
  opts: { opacity: number; painted: boolean },
): void {
  if (!instructionLifecycleDebugEnabled()) return;
  // eslint-disable-next-line no-console
  console.info(
    `[ENTITY_RENDER] id=${projection.projection_id} kind=${projection.projection_kind} x=${Math.round(box.x)} y=${Math.round(box.y)} width=${Math.round(box.w)} height=${Math.round(box.h)} opacity=${opts.opacity} visible=${projection.visible} painted=${opts.painted}`,
  );
}
