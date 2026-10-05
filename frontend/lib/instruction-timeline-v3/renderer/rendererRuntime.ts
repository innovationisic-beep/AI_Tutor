import type { RuntimeEventBus } from "@/lib/instruction-timeline-v3/eventBus";
import type { SceneStoreSnapshot } from "@/lib/instruction-timeline-v3/types";
import { SceneProjectionEngine } from "@/lib/instruction-timeline-v3/renderer/projection";
import { computeProjectionDiff } from "@/lib/instruction-timeline-v3/renderer/projectionDiff";
import type { ProjectionDiff, ProjectionSnapshot, RenderProjection, ViewportState } from "@/lib/instruction-timeline-v3/renderer/projectionTypes";
import { RENDER_LAYER_ORDER, type RenderLayer } from "@/lib/instruction-timeline-v3/renderer/renderLayers";
import { defaultViewport, viewportHash } from "@/lib/instruction-timeline-v3/renderer/viewport";

export interface RendererFrame {
  snapshot: ProjectionSnapshot;
  diff: ProjectionDiff;
  by_layer: Record<RenderLayer, RenderProjection[]>;
}

function groupByLayer(projections: RenderProjection[]): Record<RenderLayer, RenderProjection[]> {
  const grouped: Record<RenderLayer, RenderProjection[]> = {
    background: [],
    edges: [],
    nodes: [],
    labels: [],
    annotations: [],
    highlights: [],
    overlays: [],
    pointer: [],
    debug: [],
  };
  projections.forEach((p) => {
    grouped[p.layer].push(p);
  });
  return grouped;
}

export class MinimalRendererRuntime {
  private readonly projectionEngine: SceneProjectionEngine;
  private readonly eventBus?: RuntimeEventBus;
  private viewport: ViewportState;
  private previousSnapshot: ProjectionSnapshot | null = null;

  public constructor(params?: {
    viewport?: ViewportState;
    projectionEngine?: SceneProjectionEngine;
    eventBus?: RuntimeEventBus;
  }) {
    this.eventBus = params?.eventBus;
    this.viewport = params?.viewport ?? defaultViewport();
    this.projectionEngine = params?.projectionEngine ?? new SceneProjectionEngine({ eventBus: this.eventBus });
  }

  public setViewport(nextViewport: ViewportState, at: string): void {
    this.viewport = nextViewport;
    this.eventBus?.emit({
      type: "viewport_changed",
      viewport_hash: viewportHash(nextViewport),
      at,
    });
  }

  public render(scene: SceneStoreSnapshot, at: string): RendererFrame {
    const snapshot = this.projectionEngine.project({
      scene,
      viewport: this.viewport,
      at,
    });
    const diff = computeProjectionDiff(this.previousSnapshot, snapshot, this.eventBus);
    const byLayer = groupByLayer(snapshot.projections);
    RENDER_LAYER_ORDER.forEach((layer) => {
      this.eventBus?.emit({
        type: "render_layer_updated",
        layer,
        count: byLayer[layer].length,
        at,
      });
    });
    this.previousSnapshot = snapshot;
    return {
      snapshot,
      diff,
      by_layer: byLayer,
    };
  }
}
