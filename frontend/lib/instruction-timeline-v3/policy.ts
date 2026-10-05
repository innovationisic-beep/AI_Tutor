import type {
  IntegrityCadencePolicyName,
  RuntimeFailure,
  RuntimeFailurePolicyName,
  RuntimeKernelPolicy,
} from "@/lib/instruction-timeline-v3/types";

export const DEFAULT_RUNTIME_POLICY: RuntimeKernelPolicy = {
  integrity_policy: {
    mode: "production_balanced",
    interval_operations: 10,
  },
  failure_policy: "strict_fail_fast",
  resource_policy: {
    max_operations_per_timeline: 500,
    max_replay_depth: 2000,
    max_checkpoint_count: 64,
    max_journal_size: 5000,
    operation_timeout_ms: 10_000,
    replay_timeout_ms: 20_000,
  },
  checkpoint_policy: {
    checkpoint_interval_ops: 10,
    retain_recent_checkpoints: 16,
    compaction_window_ops: 50,
  },
  replay_policy: {
    use_checkpoint_bootstrap: true,
    verify_on_completion: true,
    seek_window_ops: 50,
  },
};

export function shouldRunIntegrityCheck(
  mode: IntegrityCadencePolicyName,
  opCount: number,
  isBeatBoundary: boolean,
  interval: number,
): boolean {
  switch (mode) {
    case "per_operation":
      return true;
    case "per_beat":
      return isBeatBoundary;
    case "interval_based":
      return opCount > 0 && opCount % Math.max(1, interval) === 0;
    case "debug_strict":
      return true;
    case "production_balanced":
      return isBeatBoundary || (opCount > 0 && opCount % Math.max(1, interval) === 0);
    default:
      return isBeatBoundary;
  }
}

export function shouldHaltOnFailure(
  policy: RuntimeFailurePolicyName,
  failure: RuntimeFailure,
): boolean {
  if (policy === "strict_fail_fast") return true;
  if (policy === "replay_validation_only") return false;
  if (policy === "recoverable_continue") return failure.severity === "fatal";
  if (policy === "degraded_mode") {
    return failure.category === "corruption_detected" || failure.category === "rollback_failure";
  }
  if (policy === "adapter_fallback") {
    return failure.category !== "schema_failure";
  }
  return true;
}
