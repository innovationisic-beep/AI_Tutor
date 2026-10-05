import type {
  CommitRecord,
  RollbackRecord,
  RuntimeFailure,
  SceneOperation,
  SceneStoreSnapshot,
} from "@/lib/instruction-timeline-v3/types";
import { OperationRegistry } from "@/lib/instruction-timeline-v3/operationRegistry";
import { SceneStore } from "@/lib/instruction-timeline-v3/sceneStore";
import { RuntimeEventBus } from "@/lib/instruction-timeline-v3/eventBus";
import { CommitJournal } from "@/lib/instruction-timeline-v3/commitJournal";
import { createFailure, toFailure } from "@/lib/instruction-timeline-v3/failures";
import { verifySceneIntegrity } from "@/lib/instruction-timeline-v3/integrity";

export interface ExecuteOperationInput {
  timeline_id: string;
  beat_id: string;
  operation: SceneOperation;
  sceneStore: SceneStore;
  registry: OperationRegistry;
  committedOps: Set<string>;
  journal: CommitJournal;
  eventBus?: RuntimeEventBus;
}

export interface ExecuteOperationResult {
  ok: boolean;
  snapshot?: SceneStoreSnapshot;
  commit?: CommitRecord;
  rollback?: RollbackRecord;
  errors: RuntimeFailure[];
}

export class OperationExecutor {
  public execute(input: ExecuteOperationInput): ExecuteOperationResult {
    const { timeline_id, beat_id, operation, sceneStore, registry, committedOps, journal, eventBus } =
      input;

    if (committedOps.has(operation.operation_id) || journal.hasCommitted(operation.operation_id)) {
      return {
        ok: false,
        errors: [
          createFailure("INVARIANT_FAILURE", "Operation already committed", undefined, {
            operation_id: operation.operation_id,
          }),
        ],
      };
    }

    const unmetDeps = operation.depends_on.filter((dep) => !committedOps.has(dep));
    if (unmetDeps.length > 0) {
      if (process.env.NEXT_PUBLIC_V3_DEBUG === "1") {
        const sorted = [...committedOps].sort();
        // eslint-disable-next-line no-console
        console.info(
          "[V3_DEBUG] executor_unmet_dependencies",
          JSON.stringify({
            operation_id: operation.operation_id,
            beat_id,
            depends_on: operation.depends_on,
            unmetDeps,
            committed_ops_count: committedOps.size,
            committed_ops: sorted,
          }),
        );
      }
      return {
        ok: false,
        errors: [
          createFailure("DEPENDENCY_FAILURE", "Operation dependencies are not committed", undefined, {
            unmetDeps,
          }),
        ],
      };
    }

    const handler = registry.get(operation.op_type);
    if (!handler) {
      return {
        ok: false,
        errors: [
          createFailure("UNKNOWN_OPERATION", "Operation handler not found", undefined, {
            op_type: operation.op_type,
          }),
        ],
      };
    }

    const transactionId = `${timeline_id}:${operation.operation_id}`;
    const sceneHashBefore = sceneStore.snapshot().scene_hash;
    const txSnapshot = sceneStore.exportState();
    const startedAt = Date.now();
    eventBus?.emit({
      type: "op_started",
      operation_id: operation.operation_id,
      beat_id,
      at: new Date().toISOString(),
    });

    const context = { sceneStore, committedOps };
    const preErrors = handler.validate(operation as never, context);
    if (preErrors.length > 0) {
      const errors = preErrors.map(toFailure);
      eventBus?.emit({
        type: "op_failed",
        operation_id: operation.operation_id,
        error: errors[0],
        at: new Date().toISOString(),
      });
      return { ok: false, errors };
    }

    const execErrors = handler.execute(operation as never, context);
    if (execErrors.length > 0) {
      return this.rollbackFromFailure({
        timeline_id,
        beat_id,
        operation,
        sceneStore,
        txSnapshot,
        sceneHashBefore,
        reason: "handler_execute_failed",
        baseErrors: execErrors.map(toFailure),
        eventBus,
        journal,
      });
    }

    const postErrors = handler.postValidate(operation as never, context);
    if (postErrors.length > 0) {
      return this.rollbackFromFailure({
        timeline_id,
        beat_id,
        operation,
        sceneStore,
        txSnapshot,
        sceneHashBefore,
        reason: "handler_postvalidate_failed",
        baseErrors: postErrors.map(toFailure),
        eventBus,
        journal,
      });
    }

    const snapshot = sceneStore.snapshot();
    const integrity = verifySceneIntegrity(snapshot);
    if (!integrity.ok) {
      return this.rollbackFromFailure({
        timeline_id,
        beat_id,
        operation,
        sceneStore,
        txSnapshot,
        sceneHashBefore,
        reason: "scene_integrity_failed",
        baseErrors: integrity.errors.map(toFailure),
        eventBus,
        journal,
      });
    }

    const commit = journal.appendCommit({
      timeline_id,
      beat_id,
      operation_id: operation.operation_id,
      op_type: operation.op_type,
      scene_hash_before: sceneHashBefore,
      scene_hash_after: snapshot.scene_hash,
      duration_ms: Date.now() - startedAt,
      transaction_id: transactionId,
      committed_at: new Date().toISOString(),
    });

    committedOps.add(operation.operation_id);

    return {
      ok: true,
      snapshot,
      commit,
      errors: [],
    };
  }

  private rollbackFromFailure(params: {
    timeline_id: string;
    beat_id: string;
    operation: SceneOperation;
    sceneStore: SceneStore;
    txSnapshot: unknown;
    sceneHashBefore: `sha256:${string}`;
    reason: string;
    baseErrors: RuntimeFailure[];
    eventBus?: RuntimeEventBus;
    journal: CommitJournal;
  }): ExecuteOperationResult {
    const {
      timeline_id,
      beat_id,
      operation,
      sceneStore,
      txSnapshot,
      sceneHashBefore,
      reason,
      baseErrors,
      eventBus,
      journal,
    } = params;
    try {
      eventBus?.emit({
        type: "rollback_started",
        operation_id: operation.operation_id,
        at: new Date().toISOString(),
      });
      const restored = sceneStore.restoreState(txSnapshot as never);
      const rollback = journal.appendRollback({
        timeline_id,
        beat_id,
        operation_id: operation.operation_id,
        reason,
        scene_hash_before: sceneHashBefore,
        scene_hash_restored: restored.scene_hash,
        rolled_back_at: new Date().toISOString(),
      });
      eventBus?.emit({
        type: "rollback_completed",
        operation_id: operation.operation_id,
        scene_hash: restored.scene_hash,
        at: new Date().toISOString(),
      });
      eventBus?.emit({
        type: "op_failed",
        operation_id: operation.operation_id,
        error: baseErrors[0],
        at: new Date().toISOString(),
      });
      return {
        ok: false,
        rollback,
        errors: baseErrors,
      };
    } catch (rollbackErr) {
      const fatal = createFailure("ROLLBACK_FAILURE", "Rollback failed", undefined, {
        operation_id: operation.operation_id,
        reason,
        rollback_error: String(rollbackErr),
      });
      eventBus?.emit({
        type: "op_failed",
        operation_id: operation.operation_id,
        error: fatal,
        at: new Date().toISOString(),
      });
      return { ok: false, errors: [...baseErrors, fatal] };
    }
  }
}
