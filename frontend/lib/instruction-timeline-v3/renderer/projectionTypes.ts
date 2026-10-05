import type { RenderLayer } from "@/lib/instruction-timeline-v3/renderer/renderLayers";

export interface ViewportState {
  width: number;
  height: number;
  pan_x: number;
  pan_y: number;
  scale: number;
}

export interface ProjectionBase {
  projection_id: string;
  source_entity_id: string;
  projection_kind:
    | "node"
    | "edge"
    | "label"
    | "highlight"
    | "annotation"
    | "container";
  projection_version: "1.0.0";
  layer: RenderLayer;
  z_index: number;
  visible: boolean;
  viewport_box: {
    x: number;
    y: number;
    w: number;
    h: number;
  };
  render_meta: {
    style_token?: string;
    debug_tags?: string[];
  };
  projection_hash: `sha256:${string}`;
}

export interface ComparisonNodeTeachingHints {
  comparison_side?: "left" | "right";
  comparison_tier?: "header" | "row";
  process_tier?: "step";
  sequence_index?: number;
  step_display_label?: string;
  process_identity?: string;
  hierarchy_identity?: string;
  hierarchy_tier?: "root" | "branch";
  pair_index?: number;
  semantic_role?: string;
  comparison_dimension?: string;
}

export interface RenderNodeProjection extends ProjectionBase {
  projection_kind: "node";
  label: string;
  /** Full comparison row prose — rendered inside integrated row cards. */
  row_detail?: string;
  /** CIR comparison semantics forwarded for instructional layout (presentation-only). */
  teaching_hints?: ComparisonNodeTeachingHints;
}

export interface RenderEdgeProjection extends ProjectionBase {
  projection_kind: "edge";
  from_id: string;
  to_id: string;
}

export interface RenderLabelProjection extends ProjectionBase {
  projection_kind: "label";
  text: string;
}

export type HighlightEmphasisPhase = "active" | "retired";

export interface RenderHighlightProjection extends ProjectionBase {
  projection_kind: "highlight";
  target_ids: string[];
  /** Pedagogical emphasis — only `active` overlays pulse; retired overlays are not painted. */
  emphasis_phase: HighlightEmphasisPhase;
}

export type AnnotationPhase = "active" | "passive" | "compressed" | "transient";

export interface RenderAnnotationProjection extends ProjectionBase {
  projection_kind: "annotation";
  text: string;
  target_id?: string;
  annotation_phase: AnnotationPhase;
  annotation_kind: "pedagogical" | "incremental";
  /** Runtime layout hint — set during cycle cloud composition only. */
  teaching_hints?: {
    cycle_cloud_placement?: "above" | "below" | "outside_left" | "outside_right";
  };
}

export interface RenderContainerProjection extends ProjectionBase {
  projection_kind: "container";
}

export type RenderProjection =
  | RenderNodeProjection
  | RenderEdgeProjection
  | RenderLabelProjection
  | RenderHighlightProjection
  | RenderAnnotationProjection
  | RenderContainerProjection;

export interface ProjectionSnapshot {
  generated_at: string;
  viewport: ViewportState;
  projections: RenderProjection[];
  projection_hash: `sha256:${string}`;
}

export interface ProjectionDiff {
  added: RenderProjection[];
  removed: RenderProjection[];
  updated: RenderProjection[];
  unchanged: RenderProjection[];
}
