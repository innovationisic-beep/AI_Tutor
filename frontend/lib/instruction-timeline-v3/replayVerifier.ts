import { createDefaultOperationRegistry } from "@/lib/instruction-timeline-v3/operationRegistry";
import { OperationExecutor } from "@/lib/instruction-timeline-v3/executor";
import { SceneStore } from "@/lib/instruction-timeline-v3/sceneStore";
import type {
  CheckpointRecord,
  CommitRecord,
  InstructionTimelineV3,
  RuntimeValidationError,
} from "@/lib/instruction-timeline-v3/types";
import { createFailure } from "@/lib/instruction-timeline-v3/failures";
import { CommitJournal } from "@/lib/instruction-timeline-v3/commitJournal";

export interface ReplayVerificationResult {
  ok: boolean;
  errors: RuntimeValidationError[];
  reconstructed_hash?: `sha256:${string}`;
}

export function verifyReplayDeterminism(
  timeline: InstructionTimelineV3,
  commits: CommitRecord[],
  checkpoint?: CheckpointRecord,
  maxReplayDepth = Number.MAX_SAFE_INTEGER,
): ReplayVerificationResult {
  const registry = createDefaultOperationRegistry();
  const executor = new OperationExecutor();
  const sceneStore = checkpoint
    ? new SceneStore(checkpoint.scene_state.entities_by_id, checkpoint.scene_state.root_order)
    : new SceneStore(timeline.scene_bootstrap.entities, timeline.scene_bootstrap.root_order);
  const journal = new CommitJournal();
  const committedSet = new Set<string>();

  const allOps = [...timeline.beats]
    .sort((a, b) => a.index - b.index)
    .flatMap((b) => b.operations);
  const opMap = new Map(allOps.map((op) => [op.operation_id, op]));

  const startSequence = checkpoint?.commit_sequence ?? -1;
  let replayed = 0;
  for (const commit of commits) {
    if (commit.sequence <= startSequence) continue;
    replayed += 1;
    if (replayed > maxReplayDepth) {
      return {
        ok: false,
        errors: [
          createFailure("REPLAY_MISMATCH", "Replay depth exceeds configured maximum", undefined, {
            replayed,
            maxReplayDepth,
          }),
        ],
      };
    }
    const op = opMap.get(commit.operation_id);
    if (!op) {
      return {
        ok: false,
        errors: [
          createFailure("REPLAY_MISMATCH", "Commit references unknown operation", undefined, {
            operation_id: commit.operation_id,
          }),
        ],
      };
    }

    const result = executor.execute({
      timeline_id: timeline.timeline_id,
      beat_id: commit.beat_id,
      operation: op,
      sceneStore,
      registry,
      committedOps: committedSet,
      journal,
    });
    if (!result.ok || !result.snapshot || !result.commit) {
      return {
        ok: false,
        errors: result.errors.map((e) => createFailure("REPLAY_MISMATCH", e.message, e.path, e.details)),
      };
    }

    if (result.snapshot.scene_hash !== commit.scene_hash_after) {
      return {
        ok: false,
        errors: [
          createFailure("REPLAY_MISMATCH", "Scene hash divergence detected", undefined, {
            operation_id: commit.operation_id,
            expected: commit.scene_hash_after,
            actual: result.snapshot.scene_hash,
          }),
        ],
      };
    }
  }

  const finalHash = sceneStore.snapshot().scene_hash;
  return {
    ok: true,
    errors: [],
    reconstructed_hash: finalHash,
  };
}
