import type { CommitRecord, RollbackRecord, RuntimeValidationError } from "@/lib/instruction-timeline-v3/types";
import { createFailure } from "@/lib/instruction-timeline-v3/failures";
import {
  assertCommitHistoryContinuity,
  assertSceneHashContinuity,
} from "@/lib/instruction-timeline-v3/invariants";

export class CommitJournal {
  private commits: CommitRecord[] = [];
  private rollbacks: RollbackRecord[] = [];

  public appendCommit(record: Omit<CommitRecord, "sequence">): CommitRecord {
    const sealed = Object.freeze({
      ...record,
      sequence: this.commits.length,
    }) as CommitRecord;
    this.commits = [...this.commits, sealed];
    return sealed;
  }

  public appendRollback(record: Omit<RollbackRecord, "sequence">): RollbackRecord {
    const sealed = Object.freeze({
      ...record,
      sequence: this.rollbacks.length,
    }) as RollbackRecord;
    this.rollbacks = [...this.rollbacks, sealed];
    return sealed;
  }

  public getCommits(): CommitRecord[] {
    return [...this.commits];
  }

  public getRollbacks(): RollbackRecord[] {
    return [...this.rollbacks];
  }

  public hasCommitted(opId: string): boolean {
    return this.commits.some((c) => c.operation_id === opId);
  }

  public size(): number {
    return this.commits.length + this.rollbacks.length;
  }

  public latestCommit(): CommitRecord | undefined {
    return this.commits.at(-1);
  }

  public verifyIntegrity(): RuntimeValidationError[] {
    const errors: RuntimeValidationError[] = [];
    errors.push(...assertCommitHistoryContinuity(this.commits));
    errors.push(...assertSceneHashContinuity(this.commits));

    const seenOps = new Set<string>();
    this.commits.forEach((c) => {
      if (seenOps.has(c.operation_id)) {
        errors.push(
          createFailure("INTEGRITY_FAILURE", "Duplicate operation in commit journal", undefined, {
            operation_id: c.operation_id,
          }),
        );
      }
      seenOps.add(c.operation_id);
    });
    return errors;
  }
}
