import type { InstructionTimelineV3 } from "@/lib/instruction-timeline-v3/types";

/** Minimal board item fields required for production visual gating (avoids AIWhiteboard import cycle). */
export type ProductionVisualBoardItem = {
  id: string;
  instruction_timeline_v3?: InstructionTimelineV3 | null;
  visual?: { svg?: string | null } | null;
  teaching_payload?: unknown;
};
import { validateTimelineSchema } from "@/lib/instruction-timeline-v3/validation";
import { isTimelinePresentationKillSwitchActive } from "@/lib/learning/zone1InstructionDisplay";

export type ProductionVisualRendererId =
  | "timeline_v3"
  | "segmented_tse"
  | "multibeat_svg"
  | "legacy_prose";

export type TimelineValidationState = "passed" | "failed" | "skipped" | "not_applicable";

export type ProductionVisualRendererDecision = {
  activeRenderer: ProductionVisualRendererId;
  /** Validated timeline when `activeRenderer === "timeline_v3"`. */
  timeline: InstructionTimelineV3 | null;
  validationState: TimelineValidationState;
  validationErrorCount: number;
  timelineRuntimeEnabled: boolean;
  /** Hide inline `item.visual.svg` and legacy teaching surfaces. */
  suppressLegacySvg: boolean;
  suppressLegacyTeachingPayload: boolean;
  suppressLegacyProse: boolean;
  fallbackReason: string | null;
};

export type ResolveProductionVisualOptions = {
  useInstructionBoard?: boolean;
};

function productionVisualDebugEnabled(): boolean {
  return (
    process.env.NEXT_PUBLIC_V3_DEBUG === "1" ||
    process.env.NEXT_PUBLIC_CIR_INSTRUCTION_DEBUG === "1" ||
    process.env.NEXT_PUBLIC_VISUAL_RENDERER_DEBUG === "1"
  );
}

export function logProductionVisualRenderer(
  itemId: string,
  decision: ProductionVisualRendererDecision,
): void {
  if (!productionVisualDebugEnabled()) return;
  // eslint-disable-next-line no-console
  console.info(
    "[PRODUCTION_VISUAL]",
    JSON.stringify({
      item_id: itemId,
      active_renderer: decision.activeRenderer,
      validation_state: decision.validationState,
      validation_errors: decision.validationErrorCount,
      timeline_runtime_enabled: decision.timelineRuntimeEnabled,
      suppress_legacy_svg: decision.suppressLegacySvg,
      suppress_legacy_teaching_payload: decision.suppressLegacyTeachingPayload,
      suppress_legacy_prose: decision.suppressLegacyProse,
      fallback_reason: decision.fallbackReason,
      timeline_id: decision.timeline?.timeline_id ?? null,
    }),
  );
}

function forceLegacyVisualOverrideActive(): boolean {
  return process.env.NEXT_PUBLIC_FORCE_LEGACY_VISUAL === "1";
}

/** When "1", production gate also requires Zod schema pass (stricter than structural-only). */
function strictProductionGateActive(): boolean {
  return process.env.NEXT_PUBLIC_V3_STRICT_PRODUCTION_GATE === "1";
}

function timelineStructurallyPresent(item: ProductionVisualBoardItem): boolean {
  const t = item.instruction_timeline_v3;
  return Boolean(t && Array.isArray(t.beats) && t.beats.length > 0);
}

/**
 * Single production gate: Timeline V3 is the sole visual when present, valid, and enabled.
 * Legacy SVG / TSE / prose paths remain for fallback and debug overrides only.
 */
export function resolveProductionVisualRenderer(
  item: ProductionVisualBoardItem,
  options: ResolveProductionVisualOptions = {},
): ProductionVisualRendererDecision {
  const useInstructionBoard = options.useInstructionBoard !== false;

  const baseLegacy: ProductionVisualRendererDecision = {
    activeRenderer: "legacy_prose",
    timeline: null,
    validationState: "not_applicable",
    validationErrorCount: 0,
    timelineRuntimeEnabled: false,
    suppressLegacySvg: false,
    suppressLegacyTeachingPayload: false,
    suppressLegacyProse: false,
    fallbackReason: null,
  };

  if (forceLegacyVisualOverrideActive()) {
    return {
      ...baseLegacy,
      fallbackReason: "force_legacy_visual_override",
    };
  }

  if (!timelineStructurallyPresent(item)) {
    return { ...baseLegacy, validationState: "not_applicable" };
  }

  const rawTimeline = item.instruction_timeline_v3 as InstructionTimelineV3;

  if (isTimelinePresentationKillSwitchActive()) {
    return {
      ...baseLegacy,
      validationState: "skipped",
      fallbackReason: "timeline_v3_kill_switch",
    };
  }

  if (!useInstructionBoard) {
    return {
      ...baseLegacy,
      validationState: "skipped",
      fallbackReason: "instruction_board_disabled",
    };
  }

  let timelineForRuntime: InstructionTimelineV3 = rawTimeline;
  let validationState: TimelineValidationState = "passed";
  let validationErrorCount = 0;

  if (strictProductionGateActive()) {
    const schema = validateTimelineSchema(rawTimeline);
    if (!schema.ok || !schema.data) {
      return {
        ...baseLegacy,
        validationState: "failed",
        validationErrorCount: schema.errors?.length ?? 1,
        fallbackReason: "timeline_schema_invalid",
      };
    }
    timelineForRuntime = schema.data;
    validationState = "passed";
  } else {
    // Structural gate: beats present. Full validateTimeline still runs in
    // ProductionTimelineRuntimeView before the runtime commits ops.
    validationState = "skipped";
  }

  return {
    activeRenderer: "timeline_v3",
    timeline: timelineForRuntime,
    validationState,
    validationErrorCount: 0,
    timelineRuntimeEnabled: true,
    suppressLegacySvg: true,
    suppressLegacyTeachingPayload: true,
    suppressLegacyProse: true,
    fallbackReason: null,
  };
}

export function itemUsesTimelineV3Production(
  item: ProductionVisualBoardItem,
  options?: ResolveProductionVisualOptions,
): boolean {
  return resolveProductionVisualRenderer(item, options).activeRenderer === "timeline_v3";
}
