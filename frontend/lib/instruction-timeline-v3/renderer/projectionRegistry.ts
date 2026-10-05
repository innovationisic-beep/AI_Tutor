import { computeSceneHash } from "@/lib/instruction-timeline-v3/hash";
import {
  annotationKind,
  annotationPhase,
  isAnnotationEntity,
} from "@/lib/instruction-timeline-v3/annotationLifecycle";
import {
  HIGHLIGHT_EMPHASIS_ACTIVE,
  highlightEmphasis,
  isHighlightEntity,
} from "@/lib/instruction-timeline-v3/highlightLifecycle";
import type { SceneEntity } from "@/lib/instruction-timeline-v3/types";
import type {
  RenderAnnotationProjection,
  RenderContainerProjection,
  RenderEdgeProjection,
  RenderHighlightProjection,
  RenderLabelProjection,
  RenderNodeProjection,
  RenderProjection,
  ViewportState,
} from "@/lib/instruction-timeline-v3/renderer/projectionTypes";
import { RENDER_LAYER_Z_INDEX, type RenderLayer } from "@/lib/instruction-timeline-v3/renderer/renderLayers";
import { toViewportCoordinates } from "@/lib/instruction-timeline-v3/renderer/viewport";

export interface ProjectionBuildContext {
  viewport: ViewportState;
  entitiesById: Record<string, SceneEntity>;
}

export type ProjectionBuilder<T extends SceneEntity = SceneEntity> = (
  entity: T,
  ctx: ProjectionBuildContext,
) => RenderProjection | null;

function mkBase(
  entity: SceneEntity,
  layer: RenderLayer,
  ctx: ProjectionBuildContext,
) {
  return {
    projection_id: `prj:${entity.entity_id}`,
    source_entity_id: entity.entity_id,
    projection_version: "1.0.0" as const,
    layer,
    z_index: RENDER_LAYER_Z_INDEX[layer] + entity.render.layer,
    visible: entity.lifecycle.state === "active" && (entity.render.visible ?? true),
    viewport_box: toViewportCoordinates(
      {
        x: entity.spatial.x,
        y: entity.spatial.y,
        w: entity.spatial.w,
        h: entity.spatial.h,
      },
      ctx.viewport,
    ),
    render_meta: {
      style_token: entity.render.style_token,
    },
  };
}

function withHash<T extends Record<string, unknown>>(
  projection: T,
): T & { projection_hash: `sha256:${string}` } {
  return {
    ...projection,
    projection_hash: computeSceneHash(projection),
  } as T & { projection_hash: `sha256:${string}` };
}

export class ProjectionRegistry {
  private readonly builders = new Map<SceneEntity["entity_type"], ProjectionBuilder>();

  public register<T extends SceneEntity["entity_type"]>(
    entityType: T,
    builder: ProjectionBuilder<Extract<SceneEntity, { entity_type: T }>>,
  ): void {
    this.builders.set(entityType, builder as ProjectionBuilder);
  }

  public build(entity: SceneEntity, ctx: ProjectionBuildContext): RenderProjection | null {
    const builder = this.builders.get(entity.entity_type);
    if (!builder) return null;
    return builder(entity, ctx);
  }
}

export function createDefaultProjectionRegistry(): ProjectionRegistry {
  const registry = new ProjectionRegistry();

  registry.register("Node", (entity, ctx) => {
    const payload = entity.semantic?.payload as Record<string, unknown> | undefined;
    const role = entity.semantic?.role;
    const isProcessStep = payload?.process_tier === "step";
    const row_detail = isProcessStep
      ? undefined
      : typeof payload?.row_detail === "string" && payload.row_detail.trim()
        ? payload.row_detail.trim()
        : undefined;
    const comparison_dimension =
      typeof payload?.comparison_dimension === "string" && payload.comparison_dimension.trim()
        ? payload.comparison_dimension.trim()
        : undefined;
    const teaching_hints =
      payload &&
      (payload.comparison_side != null ||
        payload.comparison_tier != null ||
        payload.process_tier != null ||
        payload.hierarchy_tier != null ||
        payload.hierarchy_identity != null ||
        payload.sequence_index != null ||
        payload.step_display_label != null ||
        payload.pair_index != null ||
        comparison_dimension ||
        role)
        ? {
            comparison_side:
              payload.comparison_side === "left" || payload.comparison_side === "right"
                ? payload.comparison_side
                : undefined,
            comparison_tier:
              payload.comparison_tier === "header" || payload.comparison_tier === "row"
                ? payload.comparison_tier
                : undefined,
            process_tier:
              payload.process_tier === "step" ? payload.process_tier : undefined,
            sequence_index:
              typeof payload.sequence_index === "number" ? payload.sequence_index : undefined,
            step_display_label:
              typeof payload.step_display_label === "string" ? payload.step_display_label : undefined,
            process_identity:
              typeof payload.process_identity === "string" ? payload.process_identity : undefined,
            hierarchy_identity:
              typeof payload.hierarchy_identity === "string"
                ? payload.hierarchy_identity
                : undefined,
            hierarchy_tier:
              payload.hierarchy_tier === "root" || payload.hierarchy_tier === "branch"
                ? payload.hierarchy_tier
                : undefined,
            pair_index:
              typeof payload.pair_index === "number" ? payload.pair_index : undefined,
            semantic_role: role,
            comparison_dimension,
          }
        : undefined;
    return withHash({
      ...mkBase(entity, "nodes", ctx),
      projection_kind: "node",
      label: entity.label,
      row_detail,
      teaching_hints,
    }) as RenderNodeProjection;
  });

  registry.register("Edge", (entity, ctx) =>
    withHash({
      ...mkBase(entity, "edges", ctx),
      projection_kind: "edge",
      from_id: entity.from_id,
      to_id: entity.to_id,
    }) as RenderEdgeProjection,
  );

  registry.register("Label", (entity, ctx) =>
    withHash({
      ...mkBase(entity, "labels", ctx),
      projection_kind: "label",
      text: entity.text,
    }) as RenderLabelProjection,
  );

  registry.register("Highlight", (entity, ctx) => {
    if (!isHighlightEntity(entity)) return null;
    const emphasis = highlightEmphasis(entity);
    const base = mkBase(entity, "highlights", ctx);
    return withHash({
      ...base,
      visible:
        entity.lifecycle.state === "active" &&
        emphasis === HIGHLIGHT_EMPHASIS_ACTIVE &&
        base.visible,
      projection_kind: "highlight",
      target_ids: entity.target_ids,
      emphasis_phase: emphasis,
    }) as RenderHighlightProjection;
  });

  registry.register("Annotation", (entity, ctx) => {
    if (!isAnnotationEntity(entity)) return null;
    return withHash({
      ...mkBase(entity, "annotations", ctx),
      projection_kind: "annotation",
      text: entity.text,
      target_id: entity.target_id,
      annotation_phase: annotationPhase(entity),
      annotation_kind: annotationKind(entity),
    }) as RenderAnnotationProjection;
  });

  registry.register("Container", (entity, ctx) =>
    withHash({
      ...mkBase(entity, "background", ctx),
      projection_kind: "container",
    }) as RenderContainerProjection,
  );

  return registry;
}
