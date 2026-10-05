import type { RenderProjection } from "@/lib/instruction-timeline-v3/renderer/projectionTypes";
import type { AnnotateEntityOp, AnnotationEntity, SceneEntity } from "@/lib/instruction-timeline-v3/types";

/** Attention hierarchy — annotations remain in scene; only presentation emphasis changes. */
export type AnnotationPhase = "active" | "passive" | "compressed" | "transient";

export type AnnotationKind = "pedagogical" | "incremental";

export const ANNOTATION_PHASE_ACTIVE: AnnotationPhase = "active";
export const ANNOTATION_PHASE_PASSIVE: AnnotationPhase = "passive";
export const ANNOTATION_PHASE_COMPRESSED: AnnotationPhase = "compressed";
export const ANNOTATION_PHASE_TRANSIENT: AnnotationPhase = "transient";

export function isAnnotationEntity(entity: SceneEntity): entity is AnnotationEntity {
  return entity.entity_type === "Annotation";
}

export function annotationPhase(entity: AnnotationEntity): AnnotationPhase {
  const raw = entity.semantic?.payload?.annotation_phase;
  if (
    raw === ANNOTATION_PHASE_PASSIVE ||
    raw === ANNOTATION_PHASE_COMPRESSED ||
    raw === ANNOTATION_PHASE_TRANSIENT
  ) {
    return raw;
  }
  return ANNOTATION_PHASE_ACTIVE;
}

export function annotationKind(entity: AnnotationEntity): AnnotationKind {
  const raw = entity.semantic?.payload?.annotation_kind;
  return raw === "incremental" ? "incremental" : "pedagogical";
}

export function inferAnnotationKind(annotationId: string): AnnotationKind {
  return annotationId.startsWith("ann_inc_") ? "incremental" : "pedagogical";
}

function withAnnotationPayload(
  entity: AnnotationEntity,
  patch: Record<string, unknown>,
): AnnotationEntity {
  return {
    ...entity,
    semantic: {
      ...entity.semantic,
      payload: {
        ...(entity.semantic.payload ?? {}),
        ...patch,
      },
    },
  };
}

/**
 * Demote prior annotations before a new pedagogical note lands.
 * Same-target replacements compress; other targets soften to passive.
 */
export function supersedeAnnotationsForNewOp(
  entitiesById: Record<string, SceneEntity>,
  targetId: string,
  supersededByOp: string,
): void {
  for (const [entityId, entity] of Object.entries(entitiesById)) {
    if (!isAnnotationEntity(entity)) continue;
    if (entity.lifecycle.state !== "active") continue;

    const phase = annotationPhase(entity);
    const kind = annotationKind(entity);
    const sameTarget = entity.target_id === targetId;

    if (phase === ANNOTATION_PHASE_ACTIVE) {
      let next: AnnotationPhase = ANNOTATION_PHASE_PASSIVE;
      if (sameTarget) {
        next = kind === "incremental" ? ANNOTATION_PHASE_TRANSIENT : ANNOTATION_PHASE_COMPRESSED;
      }
      entitiesById[entityId] = withAnnotationPayload(entity, {
        annotation_phase: next,
        superseded_by_op: supersededByOp,
      });
      continue;
    }

    if (sameTarget && phase === ANNOTATION_PHASE_PASSIVE) {
      const next: AnnotationPhase =
        kind === "incremental" ? ANNOTATION_PHASE_TRANSIENT : ANNOTATION_PHASE_COMPRESSED;
      entitiesById[entityId] = withAnnotationPayload(entity, {
        annotation_phase: next,
        superseded_by_op: supersededByOp,
      });
    }
  }
}

export function buildAnnotationEntity(op: AnnotateEntityOp): AnnotationEntity {
  const kind = inferAnnotationKind(op.payload.annotation_id);
  return {
    entity_id: op.payload.annotation_id,
    entity_type: "Annotation",
    kind: "primitive",
    version: 1,
    spatial: { x: 0, y: 0, w: 0, h: 0 },
    semantic: {
      role: "teacher_note",
      payload: {
        annotation_phase: ANNOTATION_PHASE_ACTIVE,
        annotation_kind: kind,
      },
    },
    render: { layer: 50, style_token: op.payload.style_token ?? "concept-annotation" },
    lifecycle: {
      state: "active",
      created_by_op: op.operation_id,
    },
    text: op.payload.text,
    target_id: op.payload.target_id,
  };
}

export type AnnotationLifecycleSummary = {
  active_annotation_count: number;
  passive_annotation_count: number;
  compressed_annotation_count: number;
  transient_annotation_count: number;
  superseded_annotation_ids: string[];
  annotation_phase_by_id: Record<string, AnnotationPhase>;
};

export function summarizeAnnotationLifecycle(
  entitiesById: Record<string, SceneEntity>,
): AnnotationLifecycleSummary {
  let active = 0;
  let passive = 0;
  let compressed = 0;
  let transient = 0;
  const superseded_annotation_ids: string[] = [];
  const annotation_phase_by_id: Record<string, AnnotationPhase> = {};

  for (const entity of Object.values(entitiesById)) {
    if (!isAnnotationEntity(entity)) continue;
    const phase = annotationPhase(entity);
    annotation_phase_by_id[entity.entity_id] = phase;
    if (phase === ANNOTATION_PHASE_ACTIVE) active += 1;
    else if (phase === ANNOTATION_PHASE_PASSIVE) passive += 1;
    else if (phase === ANNOTATION_PHASE_COMPRESSED) compressed += 1;
    else transient += 1;

    const supersededBy = entity.semantic?.payload?.superseded_by_op;
    if (typeof supersededBy === "string" && supersededBy.length > 0 && phase !== ANNOTATION_PHASE_ACTIVE) {
      superseded_annotation_ids.push(entity.entity_id);
    }
  }

  return {
    active_annotation_count: active,
    passive_annotation_count: passive,
    compressed_annotation_count: compressed,
    transient_annotation_count: transient,
    superseded_annotation_ids,
    annotation_phase_by_id,
  };
}

export function findAnnotateOpForOperationId(
  beats: Array<{ operations?: Array<{ operation_id: string; op_type: string; payload?: unknown }> }>,
  operationId: string,
): AnnotateEntityOp | null {
  for (const beat of beats) {
    for (const op of beat.operations ?? []) {
      if (op.operation_id !== operationId || op.op_type !== "annotate_entity") continue;
      return op as AnnotateEntityOp;
    }
  }
  return null;
}

export function summarizeAnnotationProjections(
  projections: RenderProjection[],
): AnnotationLifecycleSummary {
  let active = 0;
  let passive = 0;
  let compressed = 0;
  let transient = 0;
  const superseded_annotation_ids: string[] = [];
  const annotation_phase_by_id: Record<string, AnnotationPhase> = {};

  for (const p of projections) {
    if (p.projection_kind !== "annotation" || !p.visible) continue;
    const phase = p.annotation_phase;
    annotation_phase_by_id[p.source_entity_id] = phase;
    if (phase === ANNOTATION_PHASE_ACTIVE) active += 1;
    else if (phase === ANNOTATION_PHASE_PASSIVE) passive += 1;
    else if (phase === ANNOTATION_PHASE_COMPRESSED) compressed += 1;
    else transient += 1;
    if (phase !== ANNOTATION_PHASE_ACTIVE) {
      superseded_annotation_ids.push(p.source_entity_id);
    }
  }

  return {
    active_annotation_count: active,
    passive_annotation_count: passive,
    compressed_annotation_count: compressed,
    transient_annotation_count: transient,
    superseded_annotation_ids,
    annotation_phase_by_id,
  };
}

/** Display text for compressed / transient annotations (history preserved via title + entity). */
export function compressedAnnotationDisplayText(text: string, phase: AnnotationPhase): string {
  const trimmed = text.trim();
  if (phase === ANNOTATION_PHASE_TRANSIENT) {
    const oneLine = trimmed.replace(/\s+/g, " ");
    return oneLine.length > 42 ? `${oneLine.slice(0, 41)}…` : oneLine;
  }
  if (phase === ANNOTATION_PHASE_COMPRESSED) {
    const oneLine = trimmed.replace(/\s+/g, " ");
    return oneLine.length > 56 ? `${oneLine.slice(0, 55)}…` : oneLine;
  }
  return trimmed;
}
