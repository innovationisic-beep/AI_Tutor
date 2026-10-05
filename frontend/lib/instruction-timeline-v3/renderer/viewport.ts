import { computeSceneHash } from "@/lib/instruction-timeline-v3/hash";
import type { ViewportState } from "@/lib/instruction-timeline-v3/renderer/projectionTypes";

export function defaultViewport(width = 1280, height = 720): ViewportState {
  return {
    width,
    height,
    pan_x: 0,
    pan_y: 0,
    scale: 1,
  };
}

export function toViewportCoordinates(
  logical: { x: number; y: number; w: number; h: number },
  viewport: ViewportState,
): { x: number; y: number; w: number; h: number } {
  return {
    x: (logical.x - viewport.pan_x) * viewport.scale,
    y: (logical.y - viewport.pan_y) * viewport.scale,
    w: logical.w * viewport.scale,
    h: logical.h * viewport.scale,
  };
}

export function withPan(viewport: ViewportState, panX: number, panY: number): ViewportState {
  return {
    ...viewport,
    pan_x: panX,
    pan_y: panY,
  };
}

export function withScale(viewport: ViewportState, scale: number): ViewportState {
  return {
    ...viewport,
    scale: Math.max(0.1, scale),
  };
}

export function viewportHash(viewport: ViewportState): `sha256:${string}` {
  return computeSceneHash(viewport);
}
