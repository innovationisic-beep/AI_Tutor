import type {
  RuntimeFailure,
  RuntimeFailureCode,
  RuntimeFailureSeverity,
  RuntimeValidationError,
} from "@/lib/instruction-timeline-v3/types";

const categoryByCode: Record<
  RuntimeFailureCode,
  RuntimeFailure["category"]
> = {
  SCHEMA_INVALID: "schema_failure",
  SEMANTIC_INVALID: "schema_failure",
  INVARIANT_INVALID: "invariant_failure",
  DAG_INVALID: "dependency_failure",
  PRECONDITION_FAILED: "dependency_failure",
  POSTCONDITION_FAILED: "invariant_failure",
  EXECUTION_FAILED: "integrity_failure",
  SCHEMA_FAILURE: "schema_failure",
  INVARIANT_FAILURE: "invariant_failure",
  DEPENDENCY_FAILURE: "dependency_failure",
  ROLLBACK_FAILURE: "rollback_failure",
  REPLAY_MISMATCH: "replay_mismatch",
  CORRUPTION_DETECTED: "corruption_detected",
  UNKNOWN_OPERATION: "unknown_operation",
  INTEGRITY_FAILURE: "integrity_failure",
};

const severityByCode: Record<RuntimeFailureCode, RuntimeFailureSeverity> = {
  SCHEMA_INVALID: "fatal",
  SEMANTIC_INVALID: "fatal",
  INVARIANT_INVALID: "fatal",
  DAG_INVALID: "fatal",
  PRECONDITION_FAILED: "recoverable",
  POSTCONDITION_FAILED: "fatal",
  EXECUTION_FAILED: "fatal",
  SCHEMA_FAILURE: "fatal",
  INVARIANT_FAILURE: "fatal",
  DEPENDENCY_FAILURE: "recoverable",
  ROLLBACK_FAILURE: "fatal",
  REPLAY_MISMATCH: "fatal",
  CORRUPTION_DETECTED: "fatal",
  UNKNOWN_OPERATION: "fatal",
  INTEGRITY_FAILURE: "fatal",
};

const recommendationByCode: Record<RuntimeFailureCode, string> = {
  SCHEMA_INVALID: "Reject timeline and request replanning.",
  SEMANTIC_INVALID: "Reject timeline and run semantic validation diagnostics.",
  INVARIANT_INVALID: "Stop runtime and inspect deterministic invariants.",
  DAG_INVALID: "Reject beat and regenerate dependency graph.",
  PRECONDITION_FAILED: "Skip op only if policy allows; otherwise halt beat.",
  POSTCONDITION_FAILED: "Rollback operation and halt runtime.",
  EXECUTION_FAILED: "Rollback and escalate as fatal integrity failure.",
  SCHEMA_FAILURE: "Fallback to compatibility adapter timeline.",
  INVARIANT_FAILURE: "Halt runtime and run integrity verifier.",
  DEPENDENCY_FAILURE: "Re-evaluate scheduler state; no out-of-order execution.",
  ROLLBACK_FAILURE: "Mark scene unsafe and terminate execution.",
  REPLAY_MISMATCH: "Mark timeline as non-deterministic and quarantine.",
  CORRUPTION_DETECTED: "Halt and restore from trusted checkpoint.",
  UNKNOWN_OPERATION: "Reject timeline version or unsupported registry operation.",
  INTEGRITY_FAILURE: "Stop runtime and require operator intervention.",
};

export function createFailure(
  code: RuntimeFailureCode,
  message: string,
  path?: string,
  details?: Record<string, unknown>,
): RuntimeFailure {
  return {
    code,
    message,
    path,
    details,
    category: categoryByCode[code],
    severity: severityByCode[code],
    recommendation: recommendationByCode[code],
  };
}

export function toFailure(error: RuntimeValidationError): RuntimeFailure {
  return createFailure(error.code, error.message, error.path, error.details);
}
