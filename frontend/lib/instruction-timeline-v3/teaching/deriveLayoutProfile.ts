import type { InstructionTimelineV3 } from "@/lib/instruction-timeline-v3/types";

/**
 * Presentation-only layout kind. Deterministic; no AI.
 * Maps from timeline metadata + layout_metadata without changing the planner.
 */
export type InstructionalLayoutKind =
  | "hierarchy_root_children"
  | "flow_left_right"
  | "flow_vertical_process"
  | "comparison_split"
  | "grouped_cluster"
  | "cycle_ring";

export function deriveInstructionalLayoutKind(timeline: InstructionTimelineV3): InstructionalLayoutKind {
  const profile = timeline.layout_metadata.layout_profile;
  const mode = timeline.layout_metadata.layout_mode ?? "";
  const processRender = (
    timeline.layout_metadata as { process_render_mode?: string }
  ).process_render_mode;

  if (
    profile === "vertical_process_phaseA" ||
    mode === "vertical_process_phaseA" ||
    (processRender &&
      (processRender.includes("vertical_storyboard") ||
        processRender.includes("process_storyboard")))
  ) {
    return "flow_vertical_process";
  }

  switch (profile) {
    case "comparison_grid":
    case "comparison_columns":
    case "comparison_split":
      return "comparison_split";
    case "grouped_clusters":
      return "grouped_cluster";
    case "hierarchy_root_children":
    case "hierarchy_root_only":
      return "hierarchy_root_children";
    case "cycle_ring":
    case "cycle_radial":
      return "cycle_ring";
    case "flow_progression":
    case "empty":
    case "derivation_rail":
    case "hybrid":
      return "flow_left_right";
    case "flow_vertical":
      return "flow_vertical_process";
    case "flow_horizontal":
    default:
      return "flow_left_right";
  }
}
