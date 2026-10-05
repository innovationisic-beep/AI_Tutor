export const RENDER_LAYER_ORDER = [
  "background",
  "edges",
  "nodes",
  "labels",
  "annotations",
  "highlights",
  "overlays",
  "pointer",
  "debug",
] as const;

export type RenderLayer = (typeof RENDER_LAYER_ORDER)[number];

export const RENDER_LAYER_Z_INDEX: Record<RenderLayer, number> = {
  background: 0,
  edges: 100,
  nodes: 200,
  labels: 300,
  annotations: 400,
  highlights: 500,
  overlays: 600,
  pointer: 700,
  debug: 800,
};

export function sortLayersDeterministically<T extends { layer: RenderLayer; z_index: number; projection_id: string }>(
  items: T[],
): T[] {
  return [...items].sort((a, b) => {
    const layerDelta = RENDER_LAYER_Z_INDEX[a.layer] - RENDER_LAYER_Z_INDEX[b.layer];
    if (layerDelta !== 0) return layerDelta;
    if (a.z_index !== b.z_index) return a.z_index - b.z_index;
    return a.projection_id.localeCompare(b.projection_id);
  });
}
