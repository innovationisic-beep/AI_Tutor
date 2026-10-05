import { computeSceneHash } from "@/lib/instruction-timeline-v3/hash";
import type { RuntimeEventBus } from "@/lib/instruction-timeline-v3/eventBus";
import type { SceneStoreSnapshot } from "@/lib/instruction-timeline-v3/types";
import {
  createDefaultProjectionRegistry,
  type ProjectionRegistry,
} from "@/lib/instruction-timeline-v3/renderer/projectionRegistry";
import type { ProjectionSnapshot, ViewportState } from "@/lib/instruction-timeline-v3/renderer/projectionTypes";
import { sortLayersDeterministically } from "@/lib/instruction-timeline-v3/renderer/renderLayers";

export interface ProjectionEngineInput {
  scene: SceneStoreSnapshot;
  viewport: ViewportState;
  at: string;
}

export class SceneProjectionEngine {
  private readonly registry: ProjectionRegistry;
  private readonly eventBus?: RuntimeEventBus;
  private lastSceneHash?: `sha256:${string}`;
  private cache?: ProjectionSnapshot;

  public constructor(params?: { registry?: ProjectionRegistry; eventBus?: RuntimeEventBus }) {
    this.registry = params?.registry ?? createDefaultProjectionRegistry();
    this.eventBus = params?.eventBus;
  }

  public invalidate(reason: string, at: string): void {
    this.cache = undefined;
    this.lastSceneHash = undefined;
    this.eventBus?.emit({ type: "projection_invalidated", reason, at });
  }

  public project(input: ProjectionEngineInput): ProjectionSnapshot {
    if (this.cache && this.lastSceneHash === input.scene.scene_hash) {
      return this.cache;
    }

    const ctx = {
      viewport: input.viewport,
      entitiesById: input.scene.entities_by_id,
    };

    const projections = Object.entries(input.scene.entities_by_id)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([, entity]) => this.registry.build(entity, ctx))
      .filter((v): v is NonNullable<typeof v> => Boolean(v));

    const ordered = sortLayersDeterministically(projections);
    const projection_hash = computeSceneHash({
      viewport: input.viewport,
      projections: ordered.map((p) => ({ id: p.projection_id, hash: p.projection_hash })),
    });

    const snapshot: ProjectionSnapshot = {
      generated_at: input.at,
      viewport: input.viewport,
      projections: ordered,
      projection_hash,
    };
    this.cache = snapshot;
    this.lastSceneHash = input.scene.scene_hash;

    this.eventBus?.emit({
      type: "projection_generated",
      projection_hash,
      at: input.at,
    });
    return snapshot;
  }
}
