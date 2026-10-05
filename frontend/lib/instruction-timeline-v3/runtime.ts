import { OperationExecutor } from "@/lib/instruction-timeline-v3/executor";
import { createDefaultOperationRegistry } from "@/lib/instruction-timeline-v3/operationRegistry";
import { DagScheduler } from "@/lib/instruction-timeline-v3/scheduler";
import { SceneStore } from "@/lib/instruction-timeline-v3/sceneStore";
import { CommitJournal } from "@/lib/instruction-timeline-v3/commitJournal";
import { RuntimeEventBus } from "@/lib/instruction-timeline-v3/eventBus";
import { createFailure, toFailure } from "@/lib/instruction-timeline-v3/failures";
import {
  assertCommitHistoryContinuity,
  assertOperationOrdering,
  assertSceneHashContinuity,
} from "@/lib/instruction-timeline-v3/invariants";
import { verifyReplayDeterminism } from "@/lib/instruction-timeline-v3/replayVerifier";
import { verifySceneIntegrity } from "@/lib/instruction-timeline-v3/integrity";
import { DEFAULT_RUNTIME_POLICY, shouldHaltOnFailure, shouldRunIntegrityCheck } from "@/lib/instruction-timeline-v3/policy";
import { RuntimeTelemetryCollector } from "@/lib/instruction-timeline-v3/telemetry";
import { CheckpointStore } from "@/lib/instruction-timeline-v3/checkpointStore";
import { RealRuntimeClock, type RuntimeClock } from "@/lib/instruction-timeline-v3/clock";
import type {
  InstructionTimelineV3,
  RuntimeKernelPolicy,
  RuntimeEvent,
  SceneStoreSnapshot,
  TimelineRuntimeState,
} from "@/lib/instruction-timeline-v3/types";
import { validateTimeline } from "@/lib/instruction-timeline-v3/validation";

export interface RuntimeRunResult {
  state: TimelineRuntimeState;
  events: RuntimeEvent[];
}

export interface RuntimeRunOptions {
  eventBus?: RuntimeEventBus;
  onOperationCommitted?: (payload: {
    timeline_id: string;
    beat_id: string;
    operation_id: string;
    scene: SceneStoreSnapshot;
    at: string;
  }) => void;
}

export class MinimalTimelineRuntime {
  private readonly scheduler = new DagScheduler();
  private readonly executor = new OperationExecutor();
  private readonly registry = createDefaultOperationRegistry();
  private readonly policy: RuntimeKernelPolicy;
  private readonly clock: RuntimeClock;

  public constructor(params?: {
    policy?: Partial<RuntimeKernelPolicy>;
    clock?: RuntimeClock;
  }) {
    this.policy = {
      ...DEFAULT_RUNTIME_POLICY,
      ...params?.policy,
      integrity_policy: {
        ...DEFAULT_RUNTIME_POLICY.integrity_policy,
        ...params?.policy?.integrity_policy,
      },
      resource_policy: {
        ...DEFAULT_RUNTIME_POLICY.resource_policy,
        ...params?.policy?.resource_policy,
      },
      checkpoint_policy: {
        ...DEFAULT_RUNTIME_POLICY.checkpoint_policy,
        ...params?.policy?.checkpoint_policy,
      },
      replay_policy: {
        ...DEFAULT_RUNTIME_POLICY.replay_policy,
        ...params?.policy?.replay_policy,
      },
    };
    this.clock = params?.clock ?? new RealRuntimeClock();
  }

  public run(input: unknown, options?: RuntimeRunOptions): RuntimeRunResult {
    const v3DebugEnabled = process.env.NEXT_PUBLIC_V3_DEBUG === "1";
    const eventBus = options?.eventBus ?? new RuntimeEventBus();
    const journal = new CommitJournal();
    const checkpoints = new CheckpointStore();
    const telemetry = new RuntimeTelemetryCollector();
    const skipValidation = process.env.NEXT_PUBLIC_V3_SKIP_VALIDATION === "1";
    const validated = skipValidation
      ? { ok: true as const, data: input as InstructionTimelineV3, errors: [] as const }
      : validateTimeline(input);
    if (skipValidation) {
      // eslint-disable-next-line no-console
      console.warn(
        "[V3_DEBUG] NEXT_PUBLIC_V3_SKIP_VALIDATION=1 — validateTimeline skipped inside MinimalTimelineRuntime.run (diagnostic only)",
      );
    }
    if (!validated.ok || !validated.data) {
      // eslint-disable-next-line no-console
      console.error("[V3_DEBUG] runtime_validation_failed", JSON.stringify(validated.errors, null, 2));
      if (v3DebugEnabled) {
        // eslint-disable-next-line no-console
        console.error("[V3_DEBUG] runtime_validation_failed_parsed", validated.errors);
      }
      return {
        state: {
          timeline_id: "invalid",
          status: "failed",
          beat_cursor: 0,
          completed_beats: [],
          committed_ops: new Set<string>(),
          commit_history: journal.getCommits(),
          rollback_history: journal.getRollbacks(),
          current_scene_hash: "sha256:invalid",
          error:
            (validated.errors[0] && toFailure(validated.errors[0])) ??
            createFailure("SCHEMA_FAILURE", "Unknown validation failure"),
          metrics: telemetry.metrics(),
        },
        events: eventBus.getEvents(),
      };
    }
    if (v3DebugEnabled) {
      // eslint-disable-next-line no-console
      console.info("[V3_DEBUG] runtime_validation_success");
    }

    const timeline: InstructionTimelineV3 = validated.data;
    const sceneStore = new SceneStore(
      timeline.scene_bootstrap.entities,
      timeline.scene_bootstrap.root_order,
    );
    const initialSnapshot = sceneStore.snapshot();

    const state: TimelineRuntimeState = {
      timeline_id: timeline.timeline_id,
      status: "running",
      beat_cursor: 0,
      completed_beats: [],
      committed_ops: new Set<string>(),
      commit_history: journal.getCommits(),
      rollback_history: journal.getRollbacks(),
      current_scene_hash: initialSnapshot.scene_hash,
      metrics: telemetry.metrics(),
    };

    eventBus.emit({
      type: "timeline_started",
      timeline_id: timeline.timeline_id,
      at: new Date().toISOString(),
    });

    const totalOpsPlanned = timeline.beats.reduce((acc, beat) => acc + beat.operations.length, 0);
    if (totalOpsPlanned > this.policy.resource_policy.max_operations_per_timeline) {
      state.status = "failed";
      state.error = createFailure("INTEGRITY_FAILURE", "Operation count exceeds policy limit", undefined, {
        totalOpsPlanned,
        limit: this.policy.resource_policy.max_operations_per_timeline,
      });
      eventBus.emit({
        type: "resource_limit_hit",
        resource: "max_operations_per_timeline",
        current: totalOpsPlanned,
        limit: this.policy.resource_policy.max_operations_per_timeline,
        at: this.clock.nowIso(),
      });
      eventBus.emit({
        type: "timeline_failed",
        timeline_id: timeline.timeline_id,
        error: state.error,
        at: this.clock.nowIso(),
      });
      state.metrics = telemetry.metrics();
      return { state, events: eventBus.getEvents() };
    }

    let operationCount = 0;
    const runtimeStartedMs = this.clock.nowMs();
    const sortedBeats = [...timeline.beats].sort((a, b) => a.index - b.index);
    for (const beat of sortedBeats) {
      state.beat_cursor = beat.index;
      eventBus.emit({ type: "beat_started", beat_id: beat.beat_id, at: new Date().toISOString() });

      const init = this.scheduler.init(beat, state.committed_ops);
      if (!init.ok || !init.state) {
        state.status = "failed";
        state.error =
          (init.errors[0] && toFailure(init.errors[0])) ??
          createFailure("DEPENDENCY_FAILURE", "Scheduler initialization failed");
        eventBus.emit({
          type: "timeline_failed",
          timeline_id: timeline.timeline_id,
          error: state.error,
          at: new Date().toISOString(),
        });
        return { state, events: eventBus.getEvents() };
      }

      const schedulerState = init.state;
      const opMap = DagScheduler.toOperationMap(beat);
      let nextOpId = this.scheduler.nextReady(schedulerState);

      while (nextOpId) {
        const operation = opMap.get(nextOpId);
        if (!operation) {
          state.status = "failed";
          state.error = createFailure("UNKNOWN_OPERATION", "Operation not found in map", undefined, {
            operation_id: nextOpId,
          });
          eventBus.emit({
            type: "timeline_failed",
            timeline_id: timeline.timeline_id,
            error: state.error,
            at: new Date().toISOString(),
          });
          return { state, events: eventBus.getEvents() };
        }

        this.scheduler.markRunning(schedulerState, operation.operation_id);
        const opStartMs = this.clock.nowMs();
        const result = this.executor.execute({
          timeline_id: timeline.timeline_id,
          beat_id: beat.beat_id,
          operation,
          sceneStore,
          registry: this.registry,
          committedOps: state.committed_ops,
          journal,
          eventBus,
        });

        if (!result.ok || !result.snapshot || !result.commit) {
          state.status = "failed";
          state.error =
            result.errors[0] ?? createFailure("INTEGRITY_FAILURE", "Unknown execution failure");
          if (result.rollback) telemetry.recordRollback();
          eventBus.emit({
            type: "timeline_failed",
            timeline_id: timeline.timeline_id,
            error: state.error,
            at: this.clock.nowIso(),
          });
          state.metrics = telemetry.metrics();
          return { state, events: eventBus.getEvents() };
        }
        if (v3DebugEnabled && operationCount === 0) {
          // eslint-disable-next-line no-console
          console.info("[V3_DEBUG] runtime_first_committed_op", operation.operation_id);
        }

        operationCount += 1;
        telemetry.recordOperationLatency(this.clock.nowMs() - opStartMs);
        const opDurationMs = this.clock.nowMs() - opStartMs;
        if (opDurationMs > this.policy.resource_policy.operation_timeout_ms) {
          state.status = "failed";
          state.error = createFailure("INTEGRITY_FAILURE", "Operation timeout exceeded", undefined, {
            operation_id: operation.operation_id,
            duration_ms: opDurationMs,
            limit_ms: this.policy.resource_policy.operation_timeout_ms,
          });
          eventBus.emit({
            type: "resource_limit_hit",
            resource: "operation_timeout_ms",
            current: opDurationMs,
            limit: this.policy.resource_policy.operation_timeout_ms,
            at: this.clock.nowIso(),
          });
          eventBus.emit({
            type: "timeline_failed",
            timeline_id: timeline.timeline_id,
            error: state.error,
            at: this.clock.nowIso(),
          });
          state.metrics = telemetry.metrics();
          return { state, events: eventBus.getEvents() };
        }
        telemetry.recordJournalSize(journal.size());
        state.commit_history = journal.getCommits();
        state.rollback_history = journal.getRollbacks();
        state.current_scene_hash = result.snapshot.scene_hash;
        eventBus.emit({
          type: "op_committed",
          operation_id: operation.operation_id,
          scene_hash: result.snapshot.scene_hash,
          at: this.clock.nowIso(),
        });
        options?.onOperationCommitted?.({
          timeline_id: timeline.timeline_id,
          beat_id: beat.beat_id,
          operation_id: operation.operation_id,
          scene: result.snapshot,
          at: this.clock.nowIso(),
        });
        this.scheduler.markCommitted(schedulerState, beat.operations, operation.operation_id);

        const checkpointInterval = this.policy.checkpoint_policy.checkpoint_interval_ops;
        if (operationCount % Math.max(1, checkpointInterval) === 0) {
          const cp = checkpoints.create({
            timeline_id: timeline.timeline_id,
            commit_sequence: result.commit.sequence,
            op_cursor: operationCount,
            beat_cursor: beat.index,
            snapshot: result.snapshot,
            reason: "interval",
            at: this.clock.nowIso(),
          });
          telemetry.recordCheckpointCount(checkpoints.list().length);
          eventBus.emit({
            type: "checkpoint_created",
            beat_id: beat.beat_id,
            scene_hash: cp.scene_hash,
            at: this.clock.nowIso(),
          });
          checkpoints.prune(this.policy.checkpoint_policy.retain_recent_checkpoints);
        }

        const integrityNeeded = shouldRunIntegrityCheck(
          this.policy.integrity_policy.mode,
          operationCount,
          false,
          this.policy.integrity_policy.interval_operations,
        );
        if (integrityNeeded) {
          const t0 = this.clock.nowMs();
          const report = verifySceneIntegrity(result.snapshot);
          telemetry.recordIntegrityTiming(this.clock.nowMs() - t0);
          if (!report.ok) {
            state.status = "failed";
            state.error = toFailure(report.errors[0]);
            eventBus.emit({
              type: "integrity_check_failed",
              scope: `op:${operation.operation_id}`,
              error: state.error,
              at: this.clock.nowIso(),
            });
            const halt = shouldHaltOnFailure(this.policy.failure_policy, state.error);
            eventBus.emit({
              type: "policy_decision",
              policy: this.policy.failure_policy,
              action: halt ? "halt" : "continue",
              at: this.clock.nowIso(),
            });
            if (halt) {
              eventBus.emit({
                type: "timeline_failed",
                timeline_id: timeline.timeline_id,
                error: state.error,
                at: this.clock.nowIso(),
              });
              state.metrics = telemetry.metrics();
              return { state, events: eventBus.getEvents() };
            }
          }
        }

        nextOpId = this.scheduler.nextReady(schedulerState);
      }

      if (!this.scheduler.isBeatComplete(schedulerState, beat)) {
        state.status = "failed";
        state.error = createFailure("INVARIANT_FAILURE", "Beat ended with incomplete operations", undefined, {
          beat_id: beat.beat_id,
        });
        eventBus.emit({
          type: "timeline_failed",
          timeline_id: timeline.timeline_id,
          error: state.error,
          at: this.clock.nowIso(),
        });
        state.metrics = telemetry.metrics();
        return { state, events: eventBus.getEvents() };
      }

      const runBeatIntegrity = shouldRunIntegrityCheck(
        this.policy.integrity_policy.mode,
        operationCount,
        true,
        this.policy.integrity_policy.interval_operations,
      );
      if (runBeatIntegrity) {
        const t0 = this.clock.nowMs();
        const integrityReport = verifySceneIntegrity(sceneStore.snapshot());
        telemetry.recordIntegrityTiming(this.clock.nowMs() - t0);
        if (!integrityReport.ok) {
          state.status = "failed";
          state.error = toFailure(integrityReport.errors[0]);
          eventBus.emit({
            type: "integrity_check_failed",
            scope: beat.beat_id,
            error: state.error,
            at: this.clock.nowIso(),
          });
          eventBus.emit({
            type: "timeline_failed",
            timeline_id: timeline.timeline_id,
            error: state.error,
            at: this.clock.nowIso(),
          });
          state.metrics = telemetry.metrics();
          return { state, events: eventBus.getEvents() };
        }
      }

      const beatSnapshot = sceneStore.snapshot();
      const beatCheckpoint = checkpoints.create({
        timeline_id: timeline.timeline_id,
        commit_sequence: journal.latestCommit()?.sequence ?? 0,
        op_cursor: operationCount,
        beat_cursor: beat.index,
        snapshot: beatSnapshot,
        reason: "beat_boundary",
        at: this.clock.nowIso(),
      });
      telemetry.recordCheckpointCount(checkpoints.list().length);
      checkpoints.prune(this.policy.checkpoint_policy.retain_recent_checkpoints);
      if (checkpoints.list().length > this.policy.resource_policy.max_checkpoint_count) {
        state.status = "failed";
        state.error = createFailure("INTEGRITY_FAILURE", "Checkpoint count exceeds resource policy", undefined, {
          count: checkpoints.list().length,
          limit: this.policy.resource_policy.max_checkpoint_count,
        });
        eventBus.emit({
          type: "resource_limit_hit",
          resource: "max_checkpoint_count",
          current: checkpoints.list().length,
          limit: this.policy.resource_policy.max_checkpoint_count,
          at: this.clock.nowIso(),
        });
        eventBus.emit({
          type: "timeline_failed",
          timeline_id: timeline.timeline_id,
          error: state.error,
          at: this.clock.nowIso(),
        });
        state.metrics = telemetry.metrics();
        return { state, events: eventBus.getEvents() };
      }

      state.completed_beats.push(beat.beat_id);
      eventBus.emit({ type: "beat_completed", beat_id: beat.beat_id, at: this.clock.nowIso() });
      eventBus.emit({
        type: "checkpoint_created",
        beat_id: beat.beat_id,
        scene_hash: beatCheckpoint.scene_hash,
        at: this.clock.nowIso(),
      });
    }

    const continuityErrors = [
      ...assertCommitHistoryContinuity(journal.getCommits()),
      ...assertSceneHashContinuity(journal.getCommits()),
      ...assertOperationOrdering(
        journal.getCommits(),
        sortedBeats.flatMap((beat) => beat.operations),
      ),
      ...journal.verifyIntegrity(),
    ];
    if (continuityErrors.length > 0) {
      state.status = "failed";
      state.error = toFailure(continuityErrors[0]);
      eventBus.emit({
        type: "integrity_check_failed",
        scope: "commit_journal",
        error: state.error,
        at: this.clock.nowIso(),
      });
      eventBus.emit({
        type: "timeline_failed",
        timeline_id: timeline.timeline_id,
        error: state.error,
        at: this.clock.nowIso(),
      });
      state.metrics = telemetry.metrics();
      return { state, events: eventBus.getEvents() };
    }

    const replayStartMs = this.clock.nowMs();
    const replay = verifyReplayDeterminism(
      timeline,
      journal.getCommits(),
      checkpoints.latest(),
      this.policy.resource_policy.max_replay_depth,
    );
    telemetry.recordReplayTiming(this.clock.nowMs() - replayStartMs);
    const replayDurationMs = this.clock.nowMs() - replayStartMs;
    if (replayDurationMs > this.policy.resource_policy.replay_timeout_ms) {
      state.status = "failed";
      state.error = createFailure("INTEGRITY_FAILURE", "Replay timeout exceeded", undefined, {
        duration_ms: replayDurationMs,
        limit_ms: this.policy.resource_policy.replay_timeout_ms,
      });
      eventBus.emit({
        type: "resource_limit_hit",
        resource: "replay_timeout_ms",
        current: replayDurationMs,
        limit: this.policy.resource_policy.replay_timeout_ms,
        at: this.clock.nowIso(),
      });
      eventBus.emit({
        type: "timeline_failed",
        timeline_id: timeline.timeline_id,
        error: state.error,
        at: this.clock.nowIso(),
      });
      state.metrics = telemetry.metrics();
      return { state, events: eventBus.getEvents() };
    }
    if (!replay.ok && this.policy.replay_policy.verify_on_completion) {
      state.status = "failed";
      state.error = toFailure(replay.errors[0]);
      eventBus.emit({
        type: "timeline_failed",
        timeline_id: timeline.timeline_id,
        error: state.error,
        at: this.clock.nowIso(),
      });
      state.metrics = telemetry.metrics();
      return { state, events: eventBus.getEvents() };
    }
    eventBus.emit({
      type: "replay_verified",
      timeline_id: timeline.timeline_id,
      at: this.clock.nowIso(),
    });

    const elapsedMs = Math.max(1, this.clock.nowMs() - runtimeStartedMs);
    telemetry.recordSchedulerThroughput((operationCount * 1000) / elapsedMs);
    state.status = "completed";
    eventBus.emit({
      type: "timeline_completed",
      timeline_id: timeline.timeline_id,
      at: this.clock.nowIso(),
    });
    state.commit_history = journal.getCommits();
    state.rollback_history = journal.getRollbacks();
    state.metrics = telemetry.metrics();

    return { state, events: eventBus.getEvents() };
  }
}
