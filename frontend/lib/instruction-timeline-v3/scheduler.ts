import type {
  Beat,
  RuntimeValidationError,
  SceneOperation,
  SchedulerState,
} from "@/lib/instruction-timeline-v3/types";

function mkErr(
  code: RuntimeValidationError["code"],
  message: string,
  details?: Record<string, unknown>,
): RuntimeValidationError {
  return { code, message, details };
}

export interface SchedulerInitResult {
  ok: boolean;
  state?: SchedulerState;
  errors: RuntimeValidationError[];
}

export class DagScheduler {
  /**
   * @param committedBeforeThisBeat — timeline-global committed op ids before this beat starts
   *   (must align with validateGlobalOperationDag). Per-beat validateOperationDag is insufficient
   *   when ops depend on prior beats.
   */
  public init(beat: Beat, committedBeforeThisBeat: ReadonlySet<string>): SchedulerInitResult {
    const opIdsInBeat = new Set(beat.operations.map((o) => o.operation_id));
    const errors: RuntimeValidationError[] = [];

    for (const op of beat.operations) {
      for (const dep of op.depends_on) {
        if (!committedBeforeThisBeat.has(dep) && !opIdsInBeat.has(dep)) {
          errors.push(
            mkErr(
              "DAG_INVALID",
              `Missing dependency '${dep}' for op '${op.operation_id}' (scheduler: unresolved before beat)`,
              { beat_id: beat.beat_id, operation_id: op.operation_id, missing_dependency: dep },
            ),
          );
        }
      }
    }

    if (errors.length > 0) {
      return { ok: false, errors };
    }

    const committedBeforeSorted = [...committedBeforeThisBeat].sort((a, b) => a.localeCompare(b));

    const waiting: Record<string, string[]> = {};
    beat.operations.forEach((op) => {
      waiting[op.operation_id] = [...op.depends_on].sort();
    });

    const readyQueue = beat.operations
      .filter((op) => op.depends_on.every((dep) => committedBeforeThisBeat.has(dep)))
      .map((op) => op.operation_id)
      .sort((a, b) => a.localeCompare(b));

    if (process.env.NEXT_PUBLIC_V3_DEBUG === "1") {
      // eslint-disable-next-line no-console
      console.info(
        "[V3_DEBUG] scheduler_init",
        JSON.stringify({
          beat_id: beat.beat_id,
          committed_before_beat_count: committedBeforeThisBeat.size,
          committed_before_beat: committedBeforeSorted,
          ready_queue: readyQueue,
          op_count: beat.operations.length,
        }),
      );
    }

    return {
      ok: true,
      state: {
        beat_id: beat.beat_id,
        committed_before_beat: committedBeforeSorted,
        ready_queue: readyQueue,
        waiting_ops: waiting,
        running_ops: [],
        completed_ops: [],
      },
      errors: [],
    };
  }

  public nextReady(state: SchedulerState): string | null {
    return state.ready_queue[0] ?? null;
  }

  public markRunning(state: SchedulerState, opId: string): void {
    state.ready_queue = state.ready_queue.filter((id) => id !== opId);
    if (!state.running_ops.includes(opId)) {
      state.running_ops.push(opId);
      state.running_ops.sort();
    }
  }

  public markCommitted(state: SchedulerState, operations: SceneOperation[], opId: string): void {
    state.running_ops = state.running_ops.filter((id) => id !== opId);
    if (!state.completed_ops.includes(opId)) {
      state.completed_ops.push(opId);
      state.completed_ops.sort();
    }

    const completedSet = new Set([...state.committed_before_beat, ...state.completed_ops]);
    const candidateReady = operations
      .filter((op) => !completedSet.has(op.operation_id) && !state.running_ops.includes(op.operation_id))
      .filter((op) => op.depends_on.every((dep) => completedSet.has(dep)))
      .map((op) => op.operation_id)
      .sort((a, b) => a.localeCompare(b));

    if (process.env.NEXT_PUBLIC_V3_DEBUG === "1") {
      // eslint-disable-next-line no-console
      console.info(
        "[V3_DEBUG] scheduler_mark_committed",
        JSON.stringify({
          beat_id: state.beat_id,
          committed_op: opId,
          resolved_deps_union_size: completedSet.size,
          completed_in_beat: [...state.completed_ops],
          committed_before_beat_count: state.committed_before_beat.length,
          candidate_ready: candidateReady,
        }),
      );
    }

    const merged = new Set([...state.ready_queue, ...candidateReady]);
    state.ready_queue = [...merged].sort((a, b) => a.localeCompare(b));
  }

  public isBeatComplete(state: SchedulerState, beat: Beat): boolean {
    return state.completed_ops.length === beat.operations.length;
  }

  public static toOperationMap(beat: Beat): Map<string, SceneOperation> {
    const map = new Map<string, SceneOperation>();
    beat.operations.forEach((op) => {
      if (map.has(op.operation_id)) {
        throw mkErr("DAG_INVALID", "Duplicate operation_id in beat", { operation_id: op.operation_id });
      }
      map.set(op.operation_id, op);
    });
    return map;
  }
}
