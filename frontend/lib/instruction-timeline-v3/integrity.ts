import type { RuntimeValidationError, SceneStoreSnapshot } from "@/lib/instruction-timeline-v3/types";
import {
  assertEdgeEndpoints,
  assertEntityUniqueness,
  assertLifecycleCorrectness,
  assertParentChildConsistency,
} from "@/lib/instruction-timeline-v3/invariants";
import { createFailure } from "@/lib/instruction-timeline-v3/failures";

export interface SceneIntegrityReport {
  ok: boolean;
  checked_at: string;
  scene_hash: `sha256:${string}`;
  errors: RuntimeValidationError[];
  diagnostics: {
    entity_count: number;
    root_order_count: number;
    index_edge_keys: number;
    index_parent_keys: number;
    index_type_keys: number;
  };
}

function verifyDerivedIndexes(snapshot: SceneStoreSnapshot): RuntimeValidationError[] {
  const errors: RuntimeValidationError[] = [];
  Object.entries(snapshot.indexes.by_type).forEach(([entityType, ids]) => {
    ids.forEach((id) => {
      const entity = snapshot.entities_by_id[id];
      if (!entity || entity.entity_type !== entityType) {
        errors.push(
          createFailure("INTEGRITY_FAILURE", "by_type index mismatch", undefined, {
            entityType,
            id,
          }),
        );
      }
    });
  });
  return errors;
}

function verifyRootOrdering(snapshot: SceneStoreSnapshot): RuntimeValidationError[] {
  const errors: RuntimeValidationError[] = [];
  const sorted = [...snapshot.root_order].sort((a, b) => a.localeCompare(b));
  if (sorted.join("|") !== snapshot.root_order.join("|")) {
    errors.push(createFailure("INTEGRITY_FAILURE", "root_order must be lexical sorted"));
  }
  snapshot.root_order.forEach((id) => {
    if (!snapshot.entities_by_id[id]) {
      errors.push(createFailure("INTEGRITY_FAILURE", "root_order contains unknown entity", undefined, { id }));
    }
  });
  return errors;
}

export function verifySceneIntegrity(snapshot: SceneStoreSnapshot): SceneIntegrityReport {
  const errors = [
    ...assertEntityUniqueness(snapshot),
    ...assertEdgeEndpoints(snapshot),
    ...assertParentChildConsistency(snapshot),
    ...assertLifecycleCorrectness(snapshot),
    ...verifyRootOrdering(snapshot),
    ...verifyDerivedIndexes(snapshot),
  ];

  return {
    ok: errors.length === 0,
    checked_at: new Date().toISOString(),
    scene_hash: snapshot.scene_hash,
    errors,
    diagnostics: {
      entity_count: Object.keys(snapshot.entities_by_id).length,
      root_order_count: snapshot.root_order.length,
      index_edge_keys: Object.keys(snapshot.indexes.edges_by_node).length,
      index_parent_keys: Object.keys(snapshot.indexes.children_by_parent).length,
      index_type_keys: Object.keys(snapshot.indexes.by_type).length,
    },
  };
}
