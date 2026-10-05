export type SchemaVersion = `3.${number}.${number}`;

export type PacingMode =
  | "deliver"
  | "reinforce"
  | "visualize"
  | "reflect"
  | "question"
  | "close";

export type TimelineKind =
  | "opening_arc"
  | "micro_exchange"
  | "re_explain"
  | "checkpoint_repair"
  | "quiz_transition"
  | "teachback_transition"
  | "recovery";

export type ClockMode = "speech_authoritative" | "hybrid" | "timer_only";

export interface PlannerMetadata {
  planner_version: string;
  planner_model?: string;
  planner_config_hash: `sha256:${string}`;
}

export interface DeterminismMetadata {
  layout_seed: number;
  initial_scene_hash: `sha256:${string}`;
  expected_final_scene_hash: `sha256:${string}`;
}

export interface GlobalSyncPolicy {
  clock_mode: ClockMode;
  fallback_clock_mode: "min_delay" | "immediate_step" | "timer_only";
  min_delay_ms: number;
  max_silence_before_fallback_ms: number;
}

export interface LayoutMetadata {
  layout_profile:
    | "flow_horizontal"
    | "flow_vertical"
    | "comparison_grid"
    | "derivation_rail"
    | "hybrid"
    /** CIR v1 compile / spatial hints (must match backend ``TimelinePlannerV3``). */
    | "grouped_clusters"
    | "comparison_columns"
    | "comparison_split"
    | "cycle_radial"
    | "cycle_ring"
    | "hierarchy_root_only"
    | "hierarchy_root_children"
    | "flow_progression"
    | "vertical_process_phaseA"
    | "empty";
  viewport: {
    min_width: number;
    min_height: number;
  };
  spacing_tokens?: {
    node_gap?: number;
    section_gap?: number;
  };
  constraints_hash: `sha256:${string}`;
  /** Optional CIR compile token (same as ``metadata.cir_layout_mode`` when present). */
  layout_mode?: string;
}

export interface ReplayMetadata {
  snapshot_interval_ops: number;
  record_event_log: boolean;
  hash_algorithm: "sha256";
  replay_mode_default: "exact_timing" | "normalized_timing";
}

export interface InteractionGate {
  type:
    | "none"
    | "student_reflection_wait"
    | "student_answer_wait"
    | "quiz_wait"
    | "teachback_wait";
  required: boolean;
  max_wait_ms?: number;
  resume_policy: "continue_same_timeline" | "fork_on_input" | "abort";
  metadata?: Record<string, unknown>;
}

export interface NarrationSegment {
  segment_id: string;
  beat_id: string;
  text: string;
  speech: {
    required: boolean;
    voice_profile?: string;
    interruptible: boolean;
  };
  timing: {
    mode: ClockMode;
    min_visible_ms: number;
    fallback_delay_ms?: number;
  };
  anchor: "before_ops" | "during_ops" | "after_ops";
  /**
   * Optional presentation hints (deterministic). Prefer keys such as `pause_after_ms`,
   * `reveal_offset_ms`, `reveal_after_speech`, `reveal_during_speech` — see teaching/narrationSync types.
   */
  metadata?: Record<string, unknown>;
}

export interface NarrationOperationBinding {
  binding_id: string;
  segment_id: string;
  operation_id: string;
  relation:
    | "before_segment"
    | "on_segment_start"
    | "during_segment"
    | "on_segment_end"
    | "after_segment";
}

export interface Beat {
  beat_id: string;
  index: number;
  pacing_mode: PacingMode;
  pedagogy: {
    zone: number;
    goal: string;
    difficulty_profile?: "low" | "medium" | "high";
    interaction_expected: boolean;
  };
  sync: {
    completion_policy:
      | "all_ops_done"
      | "all_ops_and_narration_done"
      | "narration_only";
    allow_parallel_ops: boolean;
    barrier_after_beat: boolean;
  };
  preconditions?: {
    required_entity_ids?: string[];
    required_beat_ids_completed?: string[];
  };
  operations: SceneOperation[];
  narration_segments: NarrationSegment[];
  bindings: NarrationOperationBinding[];
  interaction_gate: InteractionGate;
  timeouts?: {
    hard_timeout_ms?: number;
    on_timeout_action?: "emit_prompt_nudge" | "auto_advance" | "interrupt";
  };
  metadata?: Record<string, unknown>;
}

export interface SceneBootstrap {
  entities: Record<string, SceneEntity>;
  root_order: string[];
}

export interface InstructionTimelineV3 {
  schema_version: SchemaVersion;
  timeline_id: string;
  session_id: string;
  topic_id?: string;
  concept_id?: string;
  cluster_id?: string;
  timeline_kind: TimelineKind;
  created_at: string;
  planner: PlannerMetadata;
  determinism: DeterminismMetadata;
  global_sync_policy: GlobalSyncPolicy;
  scene_bootstrap: SceneBootstrap;
  beats: Beat[];
  layout_metadata: LayoutMetadata;
  replay_metadata: ReplayMetadata;
  compatibility?: {
    source_pipeline: "native_v3" | "adapted_tpv2" | "adapted_svg";
    legacy_payload_ref?: string | null;
    legacy_svg_ref?: string | null;
  };
  metadata?: Record<string, unknown>;
}

export interface BaseEntity {
  entity_id: string;
  entity_type:
    | "Node"
    | "Edge"
    | "Label"
    | "Highlight"
    | "Annotation"
    | "StrokePath"
    | "Container"
    | "ComparisonTable"
    | "DerivationTrack"
    | "EquationBlock"
    | "FocusRegion";
  kind: "primitive" | "composite";
  version: number;
  spatial: {
    x: number;
    y: number;
    w: number;
    h: number;
    anchor_points?: Record<string, { x: number; y: number }>;
  };
  semantic: {
    role: string;
    tags?: string[];
    payload?: Record<string, unknown>;
  };
  render: {
    layer: number;
    style_token?: string;
    visible?: boolean;
  };
  animation?: {
    default_enter?: string;
    default_update?: string;
    default_exit?: string;
  };
  relations?: {
    parent_id?: string | null;
    child_ids?: string[];
  };
  lifecycle: {
    state: "active" | "inactive";
    created_by_op: string;
    deleted_by_op?: string | null;
  };
}

export interface NodeEntity extends BaseEntity {
  entity_type: "Node";
  kind: "primitive";
  label: string;
}

export interface EdgeEntity extends BaseEntity {
  entity_type: "Edge";
  kind: "primitive";
  from_id: string;
  to_id: string;
}

export interface LabelEntity extends BaseEntity {
  entity_type: "Label";
  kind: "primitive";
  text: string;
  target_id?: string;
}

export interface HighlightEntity extends BaseEntity {
  entity_type: "Highlight";
  kind: "primitive";
  target_ids: string[];
}

export interface AnnotationEntity extends BaseEntity {
  entity_type: "Annotation";
  kind: "primitive";
  text: string;
  target_id?: string;
}

export interface StrokePathEntity extends BaseEntity {
  entity_type: "StrokePath";
  kind: "primitive";
  points: Array<{ x: number; y: number }>;
}

export interface ContainerEntity extends BaseEntity {
  entity_type: "Container";
  kind: "composite";
}

export interface ComparisonTableEntity extends BaseEntity {
  entity_type: "ComparisonTable";
  kind: "composite";
  columns: string[];
  rows: Array<{ row_id: string; cells: string[]; visible?: boolean }>;
}

export interface DerivationTrackEntity extends BaseEntity {
  entity_type: "DerivationTrack";
  kind: "composite";
  step_ids: string[];
}

export interface EquationBlockEntity extends BaseEntity {
  entity_type: "EquationBlock";
  kind: "composite";
  expression: string;
}

export interface FocusRegionEntity extends BaseEntity {
  entity_type: "FocusRegion";
  kind: "composite";
  target_ids: string[];
}

export type SceneEntity =
  | NodeEntity
  | EdgeEntity
  | LabelEntity
  | HighlightEntity
  | AnnotationEntity
  | StrokePathEntity
  | ContainerEntity
  | ComparisonTableEntity
  | DerivationTrackEntity
  | EquationBlockEntity
  | FocusRegionEntity;

export interface OperationBase<TType extends string, TPayload> {
  operation_id: string;
  op_type: TType;
  beat_id: string;
  depends_on: string[];
  targets?: string[];
  payload: TPayload;
  sync: {
    execution_mode: "instant_commit" | "animated_commit";
    binding_mode: "independent" | "on_segment_start" | "on_segment_end";
  };
  animation?: {
    profile?: string;
    duration_ms?: number;
    easing?: string;
  };
  reversibility: {
    reversible: boolean;
    inverse_op_type?: string | null;
  };
  preconditions: string[];
  postconditions: string[];
  determinism_key: `sha256:${string}`;
  metadata?: Record<string, unknown>;
}

export type AddEntityOp = OperationBase<"add_entity", { entity: SceneEntity }>;
export type RemoveEntityOp = OperationBase<"remove_entity", { entity_id: string }>;
export type CirEdgeRelation = "causes" | "part_of" | "leads_to" | "requires";

export type ConnectEntitiesOp = OperationBase<
  "connect_entities",
  {
    edge_id: string;
    from_id: string;
    to_id: string;
    style_token?: string;
    relation?: CirEdgeRelation;
    edge_source?: "cir" | "synthesized";
  }
>;
export type AnnotateEntityOp = OperationBase<
  "annotate_entity",
  { annotation_id: string; target_id: string; text: string; style_token?: string }
>;
export type HighlightEntityOp = OperationBase<
  "highlight_entity",
  { highlight_id: string; target_ids: string[]; style_token?: string; ttl_ms?: number }
>;

export type SceneOperation =
  | AddEntityOp
  | RemoveEntityOp
  | ConnectEntitiesOp
  | AnnotateEntityOp
  | HighlightEntityOp;

export interface SceneStoreSnapshot {
  entities_by_id: Record<string, SceneEntity>;
  root_order: string[];
  indexes: {
    edges_by_node: Record<string, string[]>;
    children_by_parent: Record<string, string[]>;
    by_type: Record<string, string[]>;
  };
  scene_hash: `sha256:${string}`;
}

export interface CommitRecord {
  sequence: number;
  timeline_id: string;
  beat_id: string;
  operation_id: string;
  op_type: SceneOperation["op_type"];
  scene_hash_before: `sha256:${string}`;
  scene_hash_after: `sha256:${string}`;
  duration_ms?: number;
  transaction_id?: string;
  committed_at: string;
}

export interface RollbackRecord {
  sequence: number;
  timeline_id: string;
  beat_id: string;
  operation_id: string;
  reason: string;
  scene_hash_before: `sha256:${string}`;
  scene_hash_restored: `sha256:${string}`;
  rolled_back_at: string;
}

export interface CheckpointRecord {
  checkpoint_id: string;
  timeline_id: string;
  commit_sequence: number;
  op_cursor: number;
  beat_cursor: number;
  scene_hash: `sha256:${string}`;
  created_at: string;
  reason: "interval" | "beat_boundary" | "manual" | "compaction";
  scene_state: {
    entities_by_id: Record<string, SceneEntity>;
    root_order: string[];
  };
}

export type RuntimeStatus =
  | "idle"
  | "running"
  | "paused_gate"
  | "interrupted"
  | "completed"
  | "failed";

export interface TimelineRuntimeState {
  timeline_id: string;
  status: RuntimeStatus;
  beat_cursor: number;
  completed_beats: string[];
  committed_ops: Set<string>;
  commit_history: CommitRecord[];
  rollback_history?: RollbackRecord[];
  current_scene_hash: `sha256:${string}`;
  error?: RuntimeFailure;
  metrics?: RuntimeMetrics;
}

export interface SchedulerState {
  beat_id: string;
  /** Ops already committed in earlier beats (or bootstrap); used with per-beat completed_ops for global DAG semantics. */
  committed_before_beat: string[];
  ready_queue: string[];
  waiting_ops: Record<string, string[]>;
  running_ops: string[];
  completed_ops: string[];
}

export type RuntimeEvent =
  | { type: "timeline_started"; timeline_id: string; at: string }
  | { type: "beat_started"; beat_id: string; at: string }
  | { type: "op_started"; operation_id: string; beat_id: string; at: string }
  | { type: "op_committed"; operation_id: string; scene_hash: `sha256:${string}`; at: string }
  | { type: "op_failed"; operation_id: string; error: RuntimeFailure; at: string }
  | { type: "rollback_started"; operation_id: string; at: string }
  | { type: "rollback_completed"; operation_id: string; scene_hash: `sha256:${string}`; at: string }
  | { type: "integrity_check_failed"; scope: string; error: RuntimeFailure; at: string }
  | { type: "replay_verified"; timeline_id: string; at: string }
  | { type: "projection_generated"; projection_hash: `sha256:${string}`; at: string }
  | { type: "projection_invalidated"; reason: string; at: string }
  | { type: "projection_snapshot_created"; stream_version: number; projection_hash: `sha256:${string}`; at: string }
  | { type: "projection_diff_applied"; stream_version: number; at: string }
  | { type: "projection_stream_checkpointed"; stream_version: number; at: string }
  | { type: "projection_stream_replayed"; from_version: number; to_version: number; at: string }
  | {
      type: "projection_diff_computed";
      added: number;
      removed: number;
      updated: number;
      unchanged: number;
      at: string;
    }
  | { type: "viewport_changed"; viewport_hash: `sha256:${string}`; at: string }
  | { type: "render_layer_updated"; layer: string; count: number; at: string }
  | { type: "beat_completed"; beat_id: string; at: string }
  | { type: "checkpoint_created"; beat_id: string; scene_hash: `sha256:${string}`; at: string }
  | { type: "checkpoint_compacted"; checkpoint_id: string; at: string }
  | { type: "policy_decision"; policy: string; action: string; at: string }
  | { type: "resource_limit_hit"; resource: string; current: number; limit: number; at: string }
  | { type: "timeline_completed"; timeline_id: string; at: string }
  | { type: "timeline_failed"; timeline_id: string; error: RuntimeFailure; at: string };

export type RuntimeFailureCode =
  | "SCHEMA_INVALID"
  | "SEMANTIC_INVALID"
  | "INVARIANT_INVALID"
  | "DAG_INVALID"
  | "PRECONDITION_FAILED"
  | "POSTCONDITION_FAILED"
  | "EXECUTION_FAILED"
  | "SCHEMA_FAILURE"
  | "INVARIANT_FAILURE"
  | "DEPENDENCY_FAILURE"
  | "ROLLBACK_FAILURE"
  | "REPLAY_MISMATCH"
  | "CORRUPTION_DETECTED"
  | "UNKNOWN_OPERATION"
  | "INTEGRITY_FAILURE";

export type RuntimeFailureSeverity = "fatal" | "recoverable" | "warning";

export interface RuntimeValidationError {
  code: RuntimeFailureCode;
  message: string;
  path?: string;
  details?: Record<string, unknown>;
}

export interface RuntimeFailure extends RuntimeValidationError {
  category:
    | "schema_failure"
    | "invariant_failure"
    | "dependency_failure"
    | "rollback_failure"
    | "replay_mismatch"
    | "corruption_detected"
    | "unknown_operation"
    | "integrity_failure";
  severity: RuntimeFailureSeverity;
  recommendation?: string;
}

export type IntegrityCadencePolicyName =
  | "per_operation"
  | "per_beat"
  | "interval_based"
  | "debug_strict"
  | "production_balanced";

export type RuntimeFailurePolicyName =
  | "strict_fail_fast"
  | "recoverable_continue"
  | "degraded_mode"
  | "adapter_fallback"
  | "replay_validation_only";

export type RuntimeClockMode = "real" | "simulated";

export interface RuntimeResourcePolicy {
  max_operations_per_timeline: number;
  max_replay_depth: number;
  max_checkpoint_count: number;
  max_journal_size: number;
  operation_timeout_ms: number;
  replay_timeout_ms: number;
}

export interface RuntimeKernelPolicy {
  integrity_policy: {
    mode: IntegrityCadencePolicyName;
    interval_operations: number;
  };
  failure_policy: RuntimeFailurePolicyName;
  resource_policy: RuntimeResourcePolicy;
  checkpoint_policy: {
    checkpoint_interval_ops: number;
    retain_recent_checkpoints: number;
    compaction_window_ops: number;
  };
  replay_policy: {
    use_checkpoint_bootstrap: boolean;
    verify_on_completion: boolean;
    seek_window_ops: number;
  };
}

export interface RuntimeTelemetry {
  operation_latency_ms: number[];
  integrity_check_ms: number[];
  replay_verification_ms: number[];
  rollback_count: number;
  scheduler_ops_per_second: number[];
  journal_size_samples: number[];
  checkpoint_count_samples: number[];
}

export interface RuntimeMetrics {
  operation_count: number;
  integrity_check_count: number;
  replay_verification_count: number;
  rollback_count: number;
  latest_journal_size: number;
  latest_checkpoint_count: number;
}
