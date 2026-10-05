/**
 * TDSL v0.1 — mirrors backend TeachingPlan (observability / debug only in Phase 1).
 */

export const TDSL_VERSION = "0.1" as const;

export type RepresentationType = "hierarchy" | "flow" | "comparison" | "cycle";

export type PedagogicalRole =
  | "anchor"
  | "explain"
  | "reinforce"
  | "connect"
  | "emphasize"
  | "compare"
  | "reflect"
  | "checkpoint"
  | "recover"
  | "close";

export type VtseTimelineMetadata = {
  enabled?: boolean;
  tdsl_version?: string;
  strategy_id?: string;
  plan_id?: string;
  compiler_path?: string;
  compiler_version?: string;
  authoring_source?: string;
  plan_summary?: Record<string, unknown>;
};

/** Block on InstructionTimelineV3.metadata.vtse (VTSE shell / authoring observability). */
export type InstructionTimelineVtseMetadata = VtseTimelineMetadata;
