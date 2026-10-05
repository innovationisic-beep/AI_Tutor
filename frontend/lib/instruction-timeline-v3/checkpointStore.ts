import type { CheckpointRecord, SceneStoreSnapshot } from "@/lib/instruction-timeline-v3/types";

export class CheckpointStore {
  private checkpoints: CheckpointRecord[] = [];

  public create(params: {
    timeline_id: string;
    commit_sequence: number;
    op_cursor: number;
    beat_cursor: number;
    snapshot: SceneStoreSnapshot;
    reason: CheckpointRecord["reason"];
    at: string;
  }): CheckpointRecord {
    const checkpoint: CheckpointRecord = Object.freeze({
      checkpoint_id: `chk_${params.commit_sequence}_${params.op_cursor}`,
      timeline_id: params.timeline_id,
      commit_sequence: params.commit_sequence,
      op_cursor: params.op_cursor,
      beat_cursor: params.beat_cursor,
      scene_hash: params.snapshot.scene_hash,
      created_at: params.at,
      reason: params.reason,
      scene_state: {
        entities_by_id: structuredClone(params.snapshot.entities_by_id),
        root_order: [...params.snapshot.root_order],
      },
    });
    this.checkpoints = [...this.checkpoints, checkpoint];
    return checkpoint;
  }

  public prune(retainRecent: number): void {
    if (this.checkpoints.length <= retainRecent) return;
    this.checkpoints = this.checkpoints.slice(this.checkpoints.length - retainRecent);
  }

  public latest(): CheckpointRecord | undefined {
    return this.checkpoints.at(-1);
  }

  public list(): CheckpointRecord[] {
    return [...this.checkpoints];
  }

  public nearestAtOrBefore(commitSequence: number): CheckpointRecord | undefined {
    let winner: CheckpointRecord | undefined;
    for (const c of this.checkpoints) {
      if (c.commit_sequence <= commitSequence) winner = c;
    }
    return winner;
  }
}
