import type {
  CommitRecord,
  RuntimeValidationError,
  SceneOperation,
  SceneStoreSnapshot,
} from "@/lib/instruction-timeline-v3/types";
import { createFailure } from "@/lib/instruction-timeline-v3/failures";
import { validateOperationDag } from "@/lib/instruction-timeline-v3/validation";

function err(
  code: RuntimeValidationError["code"],
  message: string,
  details?: Record<string, unknown>,
): RuntimeValidationError {
  return createFailure(code, message, undefined, details);
}

export function assertEntityUniqueness(snapshot: SceneStoreSnapshot): RuntimeValidationError[] {
  const ids = Object.keys(snapshot.entities_by_id);
  const unique = new Set(ids);
  return unique.size === ids.length
    ? []
    : [err("INVARIANT_FAILURE", "Duplicate entity IDs detected")];
}

export function assertEdgeEndpoints(snapshot: SceneStoreSnapshot): RuntimeValidationError[] {
  const errors: RuntimeValidationError[] = [];
  Object.values(snapshot.entities_by_id).forEach((entity) => {
    if (entity.entity_type === "Edge") {
      if (!snapshot.entities_by_id[entity.from_id]) {
        errors.push(err("INTEGRITY_FAILURE", "Edge from_id missing", { edge_id: entity.entity_id }));
      }
      if (!snapshot.entities_by_id[entity.to_id]) {
        errors.push(err("INTEGRITY_FAILURE", "Edge to_id missing", { edge_id: entity.entity_id }));
      }
    }
  });
  return errors;
}

export function assertParentChildConsistency(snapshot: SceneStoreSnapshot): RuntimeValidationError[] {
  const errors: RuntimeValidationError[] = [];
  Object.values(snapshot.entities_by_id).forEach((entity) => {
    const parent = entity.relations?.parent_id;
    if (parent && !snapshot.entities_by_id[parent]) {
      errors.push(
        err("INTEGRITY_FAILURE", "Entity references missing parent", {
          entity_id: entity.entity_id,
          parent_id: parent,
        }),
      );
    }
  });
  return errors;
}

export function assertLifecycleCorrectness(snapshot: SceneStoreSnapshot): RuntimeValidationError[] {
  const errors: RuntimeValidationError[] = [];
  Object.values(snapshot.entities_by_id).forEach((entity) => {
    if (entity.lifecycle.state === "inactive" && !entity.lifecycle.deleted_by_op) {
      errors.push(
        err("INVARIANT_FAILURE", "Inactive entity missing deleted_by_op", {
          entity_id: entity.entity_id,
        }),
      );
    }
  });
  return errors;
}

export function assertDagIntegrity(operations: SceneOperation[]): RuntimeValidationError[] {
  return validateOperationDag(operations);
}

export function assertOperationOrdering(
  commitHistory: CommitRecord[],
  operations: SceneOperation[],
): RuntimeValidationError[] {
  const errors: RuntimeValidationError[] = [];
  const commits = new Map(commitHistory.map((c) => [c.operation_id, c]));
  operations.forEach((op) => {
    const commit = commits.get(op.operation_id);
    if (!commit) return;
    op.depends_on.forEach((dep) => {
      const depCommit = commits.get(dep);
      if (!depCommit) return;
      if (depCommit.sequence >= commit.sequence) {
        errors.push(
          err("INVARIANT_FAILURE", "Operation committed before dependency", {
            op: op.operation_id,
            dep,
          }),
        );
      }
    });
  });
  return errors;
}

export function assertSceneHashContinuity(commitHistory: CommitRecord[]): RuntimeValidationError[] {
  const errors: RuntimeValidationError[] = [];
  for (let i = 1; i < commitHistory.length; i += 1) {
    if (commitHistory[i - 1].scene_hash_after !== commitHistory[i].scene_hash_before) {
      errors.push(
        err("INVARIANT_FAILURE", "Scene hash chain discontinuity", {
          prev: commitHistory[i - 1].operation_id,
          next: commitHistory[i].operation_id,
        }),
      );
    }
  }
  return errors;
}

export function assertCommitHistoryContinuity(commitHistory: CommitRecord[]): RuntimeValidationError[] {
  const errors: RuntimeValidationError[] = [];
  commitHistory.forEach((record, index) => {
    if (record.sequence !== index) {
      errors.push(
        err("INVARIANT_FAILURE", "Commit sequence is not monotonic", {
          expected: index,
          actual: record.sequence,
        }),
      );
    }
  });
  return errors;
}
