import { z } from "zod";

import type {
  Beat,
  InstructionTimelineV3,
  RuntimeValidationError,
  SceneOperation,
} from "@/lib/instruction-timeline-v3/types";

/** Human-readable path like `beats[0].operations[1].depends_on` for logs and UI. */
export function formatInstructionTimelineSchemaPath(path: readonly (string | number)[]): string {
  if (!path.length) return "(root)";
  let out = "";
  for (const seg of path) {
    if (typeof seg === "number") out += `[${seg}]`;
    else out += out ? `.${String(seg)}` : String(seg);
  }
  return out;
}

/** Compact timeline fingerprint for validation / compile logs (not a full dump). */
export function compactTimelineSummaryForLog(
  timeline: InstructionTimelineV3 | Record<string, unknown>,
): Record<string, unknown> {
  const t = timeline as Record<string, unknown>;
  const beatsRaw = t.beats;
  const beats = Array.isArray(beatsRaw) ? beatsRaw : [];
  const meta =
    t.metadata != null && typeof t.metadata === "object"
      ? (t.metadata as Record<string, unknown>)
      : {};
  let opCount = 0;
  for (const b of beats) {
    if (b != null && typeof b === "object" && Array.isArray((b as { operations?: unknown }).operations)) {
      opCount += (b as { operations: unknown[] }).operations.length;
    }
  }
  const tid = t.timeline_id;
  return {
    timeline_id: typeof tid === "string" ? tid.slice(0, 36) : null,
    schema_version: t.schema_version ?? null,
    created_at_kind: typeof t.created_at,
    beats: beats.length,
    ops: opCount,
    representation_type: meta.representation_type ?? null,
    cir_layout_mode: meta.cir_layout_mode ?? null,
  };
}

const sha256 = z.string().regex(/^sha256:.+$/);

const baseEntitySchema = z.object({
  entity_id: z.string().min(1),
  entity_type: z.enum([
    "Node",
    "Edge",
    "Label",
    "Highlight",
    "Annotation",
    "StrokePath",
    "Container",
    "ComparisonTable",
    "DerivationTrack",
    "EquationBlock",
    "FocusRegion",
  ]),
  kind: z.enum(["primitive", "composite"]),
  version: z.number().int().min(1),
  spatial: z.object({
    x: z.number(),
    y: z.number(),
    w: z.number().nonnegative(),
    h: z.number().nonnegative(),
    anchor_points: z.record(z.string(), z.object({ x: z.number(), y: z.number() })).optional(),
  }),
  semantic: z.object({
    role: z.string(),
    tags: z.array(z.string()).optional(),
    payload: z.record(z.string(), z.unknown()).optional(),
  }),
  render: z.object({
    layer: z.number().int(),
    style_token: z.string().optional(),
    visible: z.boolean().optional(),
  }),
  animation: z
    .object({
      default_enter: z.string().optional(),
      default_update: z.string().optional(),
      default_exit: z.string().optional(),
    })
    .optional(),
  relations: z
    .object({
      parent_id: z.string().nullable().optional(),
      child_ids: z.array(z.string()).optional(),
    })
    .optional(),
  lifecycle: z.object({
    state: z.enum(["active", "inactive"]),
    created_by_op: z.string().min(1),
    deleted_by_op: z.string().nullable().optional(),
  }),
});

const nodeEntitySchema = baseEntitySchema.extend({
  entity_type: z.literal("Node"),
  kind: z.literal("primitive"),
  label: z.string().min(1),
});

const edgeEntitySchema = baseEntitySchema.extend({
  entity_type: z.literal("Edge"),
  kind: z.literal("primitive"),
  from_id: z.string().min(1),
  to_id: z.string().min(1),
});

const labelEntitySchema = baseEntitySchema.extend({
  entity_type: z.literal("Label"),
  kind: z.literal("primitive"),
  text: z.string().min(1),
  target_id: z.string().optional(),
});

const highlightEntitySchema = baseEntitySchema.extend({
  entity_type: z.literal("Highlight"),
  kind: z.literal("primitive"),
  target_ids: z.array(z.string().min(1)).min(1),
});

const annotationEntitySchema = baseEntitySchema.extend({
  entity_type: z.literal("Annotation"),
  kind: z.literal("primitive"),
  text: z.string().min(1),
  target_id: z.string().optional(),
});

const strokePathEntitySchema = baseEntitySchema.extend({
  entity_type: z.literal("StrokePath"),
  kind: z.literal("primitive"),
  points: z.array(z.object({ x: z.number(), y: z.number() })).min(2),
});

const containerEntitySchema = baseEntitySchema.extend({
  entity_type: z.literal("Container"),
  kind: z.literal("composite"),
});

const comparisonEntitySchema = baseEntitySchema.extend({
  entity_type: z.literal("ComparisonTable"),
  kind: z.literal("composite"),
  columns: z.array(z.string()).min(1),
  rows: z.array(
    z.object({
      row_id: z.string().min(1),
      cells: z.array(z.string()),
      visible: z.boolean().optional(),
    }),
  ),
});

const derivationEntitySchema = baseEntitySchema.extend({
  entity_type: z.literal("DerivationTrack"),
  kind: z.literal("composite"),
  step_ids: z.array(z.string()).min(1),
});

const equationEntitySchema = baseEntitySchema.extend({
  entity_type: z.literal("EquationBlock"),
  kind: z.literal("composite"),
  expression: z.string().min(1),
});

const focusEntitySchema = baseEntitySchema.extend({
  entity_type: z.literal("FocusRegion"),
  kind: z.literal("composite"),
  target_ids: z.array(z.string()).min(1),
});

export const sceneEntitySchema = z.discriminatedUnion("entity_type", [
  nodeEntitySchema,
  edgeEntitySchema,
  labelEntitySchema,
  highlightEntitySchema,
  annotationEntitySchema,
  strokePathEntitySchema,
  containerEntitySchema,
  comparisonEntitySchema,
  derivationEntitySchema,
  equationEntitySchema,
  focusEntitySchema,
]);

const operationBaseSchema = z.object({
  operation_id: z.string().regex(/^op_[0-9]{6}$/),
  beat_id: z.string().min(1),
  depends_on: z.array(z.string()).default([]),
  targets: z.array(z.string()).optional(),
  sync: z.object({
    execution_mode: z.enum(["instant_commit", "animated_commit"]),
    binding_mode: z.enum(["independent", "on_segment_start", "on_segment_end"]),
  }),
  animation: z
    .object({
      profile: z.string().optional(),
      duration_ms: z.number().int().min(0).optional(),
      easing: z.string().optional(),
    })
    .optional(),
  reversibility: z.object({
    reversible: z.boolean(),
    inverse_op_type: z.string().nullable().optional(),
  }),
  preconditions: z.array(z.string()).default([]),
  postconditions: z.array(z.string()).default([]),
  determinism_key: sha256,
  metadata: z.record(z.string(), z.unknown()).optional(),
});

const addEntityOpSchema = operationBaseSchema.extend({
  op_type: z.literal("add_entity"),
  payload: z.object({ entity: sceneEntitySchema }),
});

const removeEntityOpSchema = operationBaseSchema.extend({
  op_type: z.literal("remove_entity"),
  payload: z.object({ entity_id: z.string().min(1) }),
});

const cirEdgeRelationSchema = z.enum(["causes", "part_of", "leads_to", "requires"]);

const connectEntitiesOpSchema = operationBaseSchema.extend({
  op_type: z.literal("connect_entities"),
  payload: z.object({
    edge_id: z.string().min(1),
    from_id: z.string().min(1),
    to_id: z.string().min(1),
    style_token: z.string().optional(),
    relation: cirEdgeRelationSchema.optional(),
    edge_source: z.enum(["cir", "synthesized"]).optional(),
  }),
});

const annotateEntityOpSchema = operationBaseSchema.extend({
  op_type: z.literal("annotate_entity"),
  payload: z.object({
    annotation_id: z.string().min(1),
    target_id: z.string().min(1),
    text: z.string().min(1),
    style_token: z.string().optional(),
  }),
});

const highlightEntityOpSchema = operationBaseSchema.extend({
  op_type: z.literal("highlight_entity"),
  payload: z.object({
    highlight_id: z.string().min(1),
    target_ids: z.array(z.string().min(1)).min(1),
    style_token: z.string().optional(),
    ttl_ms: z.number().int().min(1).optional(),
  }),
});

export const sceneOperationSchema = z.discriminatedUnion("op_type", [
  addEntityOpSchema,
  removeEntityOpSchema,
  connectEntitiesOpSchema,
  annotateEntityOpSchema,
  highlightEntityOpSchema,
]);

const beatSchema = z.object({
  beat_id: z.string().regex(/^beat_[0-9]{4}$/),
  index: z.number().int().min(0),
  pacing_mode: z.enum([
    "deliver",
    "reinforce",
    "visualize",
    "reflect",
    "question",
    "close",
  ]),
  pedagogy: z.object({
    zone: z.number().int().min(0).max(4),
    goal: z.string().min(1),
    difficulty_profile: z.enum(["low", "medium", "high"]).optional(),
    interaction_expected: z.boolean(),
  }),
  sync: z.object({
    completion_policy: z.enum([
      "all_ops_done",
      "all_ops_and_narration_done",
      "narration_only",
    ]),
    allow_parallel_ops: z.boolean(),
    barrier_after_beat: z.boolean(),
  }),
  preconditions: z
    .object({
      required_entity_ids: z.array(z.string()).optional(),
      required_beat_ids_completed: z.array(z.string()).optional(),
    })
    .optional(),
  operations: z.array(sceneOperationSchema),
  narration_segments: z.array(
    z.object({
      segment_id: z.string().min(1),
      beat_id: z.string().min(1),
      text: z.string().min(1),
      speech: z.object({
        required: z.boolean(),
        voice_profile: z.string().optional(),
        interruptible: z.boolean(),
      }),
      timing: z.object({
        mode: z.enum(["speech_authoritative", "hybrid", "timer_only"]),
        min_visible_ms: z.number().int().min(0),
        fallback_delay_ms: z.number().int().min(0).optional(),
      }),
      anchor: z.enum(["before_ops", "during_ops", "after_ops"]),
      metadata: z.record(z.string(), z.unknown()).optional(),
    }),
  ),
  bindings: z.array(
    z.object({
      binding_id: z.string().min(1),
      segment_id: z.string().min(1),
      operation_id: z.string().min(1),
      relation: z.enum([
        "before_segment",
        "on_segment_start",
        "during_segment",
        "on_segment_end",
        "after_segment",
      ]),
    }),
  ),
  interaction_gate: z.object({
    type: z.enum([
      "none",
      "student_reflection_wait",
      "student_answer_wait",
      "quiz_wait",
      "teachback_wait",
    ]),
    required: z.boolean(),
    max_wait_ms: z.number().int().min(1000).optional(),
    resume_policy: z.enum(["continue_same_timeline", "fork_on_input", "abort"]),
    metadata: z.record(z.string(), z.unknown()).optional(),
  }),
  timeouts: z
    .object({
      hard_timeout_ms: z.number().int().min(1000).optional(),
      on_timeout_action: z
        .enum(["emit_prompt_nudge", "auto_advance", "interrupt"])
        .optional(),
    })
    .optional(),
  metadata: z.record(z.string(), z.unknown()).optional(),
});

export const timelineSchema = z.object({
  schema_version: z.string().regex(/^3\.\d+\.\d+$/),
  timeline_id: z.string().regex(/^tlm_[A-Za-z0-9]+$/),
  session_id: z.string().min(1),
  /** Planner may emit ""; treat as absent so optional topic_id validates. */
  topic_id: z.preprocess(
    (v) => (v === "" || v === null ? undefined : v),
    z.string().min(1).optional(),
  ),
  concept_id: z.string().optional(),
  cluster_id: z.string().optional(),
  timeline_kind: z.enum([
    "opening_arc",
    "micro_exchange",
    "re_explain",
    "checkpoint_repair",
    "quiz_transition",
    "teachback_transition",
    "recovery",
  ]),
  /** Zod v4 datetime: trailing Z only; Python UTC isoformat uses +00:00 and fails. */
  created_at: z.string().datetime(),
  planner: z.object({
    planner_version: z.string().min(1),
    planner_model: z.string().optional(),
    planner_config_hash: sha256,
  }),
  determinism: z.object({
    layout_seed: z.number().int().min(0),
    initial_scene_hash: sha256,
    expected_final_scene_hash: sha256,
  }),
  global_sync_policy: z.object({
    clock_mode: z.enum(["speech_authoritative", "hybrid", "timer_only"]),
    fallback_clock_mode: z.enum(["min_delay", "immediate_step", "timer_only"]),
    min_delay_ms: z.number().int().min(0).default(350),
    max_silence_before_fallback_ms: z.number().int().min(100).default(1500),
  }),
  scene_bootstrap: z.object({
    entities: z.record(z.string(), sceneEntitySchema),
    root_order: z.array(z.string()).default([]),
  }),
  beats: z.array(beatSchema).min(1),
  layout_metadata: z.object({
    layout_profile: z.enum([
      "flow_horizontal",
      "flow_vertical",
      "comparison_grid",
      "derivation_rail",
      "hybrid",
      "grouped_clusters",
      "comparison_columns",
      "comparison_split",
      "cycle_radial",
      "cycle_ring",
      "hierarchy_root_only",
      "hierarchy_root_children",
      "flow_progression",
      "vertical_process_phaseA",
      "empty",
    ]),
    viewport: z.object({
      min_width: z.number().int().min(320),
      min_height: z.number().int().min(240),
    }),
    spacing_tokens: z
      .object({
        node_gap: z.number().nonnegative().optional(),
        section_gap: z.number().nonnegative().optional(),
      })
      .optional(),
    constraints_hash: sha256,
    layout_mode: z.string().min(1).max(64).optional(),
  }),
  replay_metadata: z.object({
    snapshot_interval_ops: z.number().int().min(1).default(20),
    record_event_log: z.boolean().default(true),
    hash_algorithm: z.literal("sha256").default("sha256"),
    replay_mode_default: z
      .enum(["exact_timing", "normalized_timing"])
      .default("exact_timing"),
  }),
  compatibility: z
    .object({
      source_pipeline: z.enum(["native_v3", "adapted_tpv2", "adapted_svg"]),
      legacy_payload_ref: z.string().nullable().optional(),
      legacy_svg_ref: z.string().nullable().optional(),
    })
    .optional(),
  metadata: z.record(z.string(), z.unknown()).optional(),
});

function mkError(
  code: RuntimeValidationError["code"],
  message: string,
  path?: string,
  details?: Record<string, unknown>,
): RuntimeValidationError {
  return { code, message, path, details };
}

export interface ValidationResult<T> {
  ok: boolean;
  data?: T;
  errors: RuntimeValidationError[];
}

export function validateTimelineSchema(input: unknown): ValidationResult<InstructionTimelineV3> {
  const parsed = timelineSchema.safeParse(input);
  if (!parsed.success) {
    return {
      ok: false,
      errors: parsed.error.issues.map((issue) => {
        const validationPath = formatInstructionTimelineSchemaPath(issue.path);
        const details: Record<string, unknown> = {
          zod_code: issue.code,
          schema_path: validationPath,
        };
        const rec = (issue as { received?: unknown }).received;
        const exp = (issue as { expected?: unknown }).expected;
        if (rec !== undefined) details.invalid_value = rec;
        if (exp !== undefined) details.expected_value = exp;
        return mkError("SCHEMA_INVALID", issue.message, validationPath, details);
      }),
    };
  }

  return { ok: true, data: parsed.data as InstructionTimelineV3, errors: [] };
}

export function validateSemanticInvariants(timeline: InstructionTimelineV3): RuntimeValidationError[] {
  const errors: RuntimeValidationError[] = [];
  const seenBeats = new Set<string>();
  const seenOps = new Set<string>();
  const seenEntities = new Set<string>();

  const sortedBeats = [...timeline.beats].sort((a, b) => a.index - b.index);
  sortedBeats.forEach((beat, idx) => {
    if (beat.index !== idx) {
      errors.push(
        mkError("INVARIANT_INVALID", "Beat indexes must be contiguous and zero-based", `beats[${idx}].index`),
      );
    }
    if (seenBeats.has(beat.beat_id)) {
      errors.push(mkError("SEMANTIC_INVALID", "Duplicate beat_id", "beats"));
    }
    seenBeats.add(beat.beat_id);
  });

  Object.keys(timeline.scene_bootstrap.entities)
    .sort()
    .forEach((id) => {
      if (seenEntities.has(id)) {
        errors.push(mkError("SEMANTIC_INVALID", "Duplicate entity_id in bootstrap", "scene_bootstrap.entities"));
      }
      seenEntities.add(id);
    });

  timeline.beats.forEach((beat, beatIdx) => {
    beat.operations.forEach((op, opIdx) => {
      if (seenOps.has(op.operation_id)) {
        errors.push(
          mkError(
            "SEMANTIC_INVALID",
            "Duplicate operation_id",
            `beats[${beatIdx}].operations[${opIdx}].operation_id`,
          ),
        );
      }
      if (op.beat_id !== beat.beat_id) {
        errors.push(
          mkError(
            "SEMANTIC_INVALID",
            "Operation beat_id must equal parent beat_id",
            `beats[${beatIdx}].operations[${opIdx}].beat_id`,
          ),
        );
      }
      seenOps.add(op.operation_id);
    });
  });

  return errors;
}

export function validateOperationDag(operations: SceneOperation[]): RuntimeValidationError[] {
  const errors: RuntimeValidationError[] = [];
  const byId = new Map<string, SceneOperation>();
  const incoming = new Map<string, number>();
  const outgoing = new Map<string, string[]>();

  operations.forEach((op) => {
    byId.set(op.operation_id, op);
    incoming.set(op.operation_id, 0);
    outgoing.set(op.operation_id, []);
  });

  for (const op of operations) {
    for (const dep of op.depends_on) {
      if (!byId.has(dep)) {
        errors.push(
          mkError("DAG_INVALID", `Missing dependency '${dep}' for op '${op.operation_id}'`, "depends_on"),
        );
        continue;
      }
      incoming.set(op.operation_id, (incoming.get(op.operation_id) ?? 0) + 1);
      const edges = outgoing.get(dep) ?? [];
      edges.push(op.operation_id);
      outgoing.set(dep, edges);
    }
  }

  if (errors.length > 0) return errors;

  const queue = [...operations]
    .filter((op) => (incoming.get(op.operation_id) ?? 0) === 0)
    .map((op) => op.operation_id)
    .sort();
  let visited = 0;

  while (queue.length > 0) {
    const id = queue.shift();
    if (!id) break;
    visited += 1;
    const nextIds = outgoing.get(id) ?? [];
    for (const nextId of nextIds) {
      const count = (incoming.get(nextId) ?? 0) - 1;
      incoming.set(nextId, count);
      if (count === 0) {
        queue.push(nextId);
        queue.sort();
      }
    }
  }

  if (visited !== operations.length) {
    errors.push(mkError("DAG_INVALID", "Cycle detected in operation dependencies", "operations"));
  }

  return errors;
}

/**
 * Validates operation dependencies across the entire timeline (all beats), in beat-index order.
 * Per-beat-only DAG validation incorrectly rejects legal cross-beat edges (e.g. highlight chaining).
 */
export function validateGlobalOperationDag(beats: Beat[]): RuntimeValidationError[] {
  const errors: RuntimeValidationError[] = [];
  const sortedBeats = [...beats].sort((a, b) => a.index - b.index);
  const operations: SceneOperation[] = [];
  for (const beat of sortedBeats) {
    operations.push(...beat.operations);
  }

  const byId = new Map<string, SceneOperation>();
  const incoming = new Map<string, number>();
  const outgoing = new Map<string, string[]>();

  for (const op of operations) {
    byId.set(op.operation_id, op);
    incoming.set(op.operation_id, 0);
    outgoing.set(op.operation_id, []);
  }

  for (const op of operations) {
    for (const dep of op.depends_on) {
      if (!byId.has(dep)) {
        errors.push(
          mkError(
            "DAG_INVALID",
            `Missing dependency '${dep}' for op '${op.operation_id}' (global DAG)`,
            `operations:${op.operation_id}:depends_on`,
            {
              invariant: "global_operation_dag",
              dependent_op: op.operation_id,
              dependent_beat_id: op.beat_id,
              missing_dependency: dep,
            },
          ),
        );
        continue;
      }
      incoming.set(op.operation_id, (incoming.get(op.operation_id) ?? 0) + 1);
      const edges = outgoing.get(dep) ?? [];
      edges.push(op.operation_id);
      outgoing.set(dep, edges);
    }
  }

  if (errors.length > 0) return errors;

  const queue = [...operations]
    .filter((op) => (incoming.get(op.operation_id) ?? 0) === 0)
    .map((op) => op.operation_id)
    .sort();
  let visited = 0;

  while (queue.length > 0) {
    const id = queue.shift();
    if (!id) break;
    visited += 1;
    const nextIds = outgoing.get(id) ?? [];
    for (const nextId of nextIds) {
      const count = (incoming.get(nextId) ?? 0) - 1;
      incoming.set(nextId, count);
      if (count === 0) {
        queue.push(nextId);
        queue.sort();
      }
    }
  }

  if (visited !== operations.length) {
    errors.push(
      mkError(
        "DAG_INVALID",
        "Cycle detected in operation dependencies (global timeline)",
        "operations",
        { invariant: "global_operation_dag_acyclic" },
      ),
    );
  }

  return errors;
}

const BEATS_OPS_PATH = /^beats\.(\d+)\.operations\.(\d+)(?:\.|$)/;

export type FailingOperationSnapshot = {
  beat_id: string;
  operation_id: string;
  op_type: string;
  op: SceneOperation;
};

/** Stable JSON for console / UI (full operation payloads). */
export function stringifyValidationErrorsDeep(errors: RuntimeValidationError[]): string {
  return JSON.stringify(errors, null, 2);
}

/**
 * For each validation error, attach any operations implicated by Zod paths or DAG details.
 */
export function collectFailingOperationSnapshots(
  timeline: InstructionTimelineV3,
  errors: RuntimeValidationError[],
): FailingOperationSnapshot[] {
  const out: FailingOperationSnapshot[] = [];
  const seen = new Set<string>();

  const pushFromIndices = (beatIdx: number, opIdx: number): void => {
    const beat = timeline.beats[beatIdx];
    if (!beat) return;
    const op = beat.operations[opIdx];
    if (!op) return;
    const key = op.operation_id;
    if (seen.has(key)) return;
    seen.add(key);
    out.push({ beat_id: beat.beat_id, operation_id: op.operation_id, op_type: op.op_type, op });
  };

  const pushByOpId = (operationId: string): void => {
    for (let bi = 0; bi < timeline.beats.length; bi += 1) {
      const oi = timeline.beats[bi].operations.findIndex((o) => o.operation_id === operationId);
      if (oi >= 0) {
        pushFromIndices(bi, oi);
        return;
      }
    }
  };

  for (const err of errors) {
    if (err.path) {
      const m = err.path.match(BEATS_OPS_PATH);
      if (m) {
        pushFromIndices(Number(m[1]), Number(m[2]));
      }
    }
    const d = err.details;
    if (d && typeof d === "object") {
      if ("dependent_op" in d && typeof (d as { dependent_op: unknown }).dependent_op === "string") {
        pushByOpId((d as { dependent_op: string }).dependent_op);
      }
    }
  }

  return out;
}

export function validateTimeline(input: unknown): ValidationResult<InstructionTimelineV3> {
  const schemaResult = validateTimelineSchema(input);
  if (!schemaResult.ok || !schemaResult.data) {
    return schemaResult;
  }

  const semanticErrors = validateSemanticInvariants(schemaResult.data);
  const dagErrors =
    semanticErrors.length > 0 ? [] : validateGlobalOperationDag(schemaResult.data.beats);

  const errors = [...semanticErrors, ...dagErrors];
  return {
    ok: errors.length === 0,
    data: schemaResult.data,
    errors,
  };
}
