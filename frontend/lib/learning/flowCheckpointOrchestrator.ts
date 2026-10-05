import { deriveInstructionalLayoutKind } from "@/lib/instruction-timeline-v3/teaching/deriveLayoutProfile";
import type { Beat, InstructionTimelineV3 } from "@/lib/instruction-timeline-v3/types";
import { cancelSpeech } from "@/lib/voice";

export const FLOW_CHECKPOINT_INTERVAL = 2;

export type FlowProcessNodeRef = {
  nodeId: string;
  label: string;
  beatId: string;
  beatIndex: number;
};

export type FlowCheckpointEvent = {
  completedNodeCount: number;
  checkpointIndex: number;
  stepLabels: string[];
  nodeIds: string[];
  resumeAfterBeatIndex: number;
  beatId: string;
};

export type FlowCheckpointGate = {
  onFlowNodeCompleted: (event: FlowCheckpointEvent) => Promise<void>;
};

function nodeLabelFromEntity(entity: {
  entity_id: string;
  label?: string;
  semantic?: { role?: string; process_identity?: string };
  teaching_hints?: { step_display_label?: string; process_identity?: string };
}): string {
  const hint =
    entity.teaching_hints?.process_identity?.trim() ||
    entity.teaching_hints?.step_display_label?.trim() ||
    entity.semantic?.process_identity?.trim();
  if (hint) return hint;
  const label = (entity.label ?? "").trim();
  return label || entity.entity_id;
}

/** Ordered flow process nodes derived from timeline beats (add_entity Node ops). */
export function orderedFlowProcessNodes(
  timeline: InstructionTimelineV3,
): FlowProcessNodeRef[] {
  const sorted = [...timeline.beats].sort((a, b) => a.index - b.index);
  const refs: FlowProcessNodeRef[] = [];
  const seen = new Set<string>();

  for (const beat of sorted) {
    for (const op of beat.operations) {
      if (op.op_type !== "add_entity") continue;
      const ent = op.payload.entity;
      if (ent.entity_type !== "Node") continue;
      const id = ent.entity_id;
      if (seen.has(id)) continue;
      seen.add(id);
      refs.push({
        nodeId: id,
        label: nodeLabelFromEntity(ent),
        beatId: beat.beat_id,
        beatIndex: beat.index,
      });
      break;
    }
  }

  return refs;
}

export function isFlowCheckpointEligible(timeline: InstructionTimelineV3): boolean {
  return deriveInstructionalLayoutKind(timeline) === "flow_vertical_process";
}

export function shouldTriggerFlowCheckpoint(completedNodeCount: number): boolean {
  return (
    completedNodeCount >= FLOW_CHECKPOINT_INTERVAL &&
    completedNodeCount % FLOW_CHECKPOINT_INTERVAL === 0
  );
}

/**
 * Classify a process-node checkpoint relative to the full linear_process timeline.
 * Intermediate checkpoints must never arm Concept Check / send stage_done.
 */
export function processFlowCheckpointKind(
  completedNodeCount: number,
  totalNodes: number,
): "none" | "intermediate" | "final" {
  if (totalNodes < 1 || completedNodeCount < 1) return "none";
  if (!shouldTriggerFlowCheckpoint(completedNodeCount)) return "none";
  if (completedNodeCount >= totalNodes) return "final";
  return "intermediate";
}

/** True while FlowCheckpoint overlay owns the board (pause or continue in-flight). */
export function isFlowCheckpointBlockingVtseStageDone(opts: {
  isActive: boolean;
  continuing?: boolean;
}): boolean {
  return opts.isActive || opts.continuing === true;
}

export function flowNodeIndexForBeat(
  timeline: InstructionTimelineV3,
  beat: Pick<Beat, "beat_id">,
): number {
  return orderedFlowProcessNodes(timeline).findIndex((n) => n.beatId === beat.beat_id);
}

/** Build checkpoint payload when a beat completes a flow node; null if no checkpoint. */
export function buildFlowCheckpointEventForBeat(
  timeline: InstructionTimelineV3,
  beat: Beat,
): FlowCheckpointEvent | null {
  if (!isFlowCheckpointEligible(timeline)) return null;

  const nodes = orderedFlowProcessNodes(timeline);
  const nodeIndex = nodes.findIndex((n) => n.beatId === beat.beat_id);
  if (nodeIndex < 0) return null;

  const completedNodeCount = nodeIndex + 1;
  if (!shouldTriggerFlowCheckpoint(completedNodeCount)) return null;

  const stepLabels = nodes
    .slice(completedNodeCount - FLOW_CHECKPOINT_INTERVAL, completedNodeCount)
    .map((n) => n.label);

  return {
    completedNodeCount,
    checkpointIndex: completedNodeCount / FLOW_CHECKPOINT_INTERVAL - 1,
    stepLabels,
    nodeIds: nodes.slice(0, completedNodeCount).map((n) => n.nodeId),
    resumeAfterBeatIndex: beat.index + 1,
    beatId: beat.beat_id,
  };
}

export function logFlowCheckpoint(
  tag:
    | "FLOW_CHECKPOINT_TRIGGERED"
    | "FLOW_CHECKPOINT_STEP_LABELS"
    | "FLOW_CHECKPOINT_PAUSED"
    | "FLOW_CHECKPOINT_CONTINUE"
    | "FLOW_CHECKPOINT_QUESTION"
    | "FLOW_CHECKPOINT_CLARIFICATION_SENT"
    | "FLOW_CHECKPOINT_RESUME",
  payload?: Record<string, unknown>,
): void {
  // eslint-disable-next-line no-console
  console.info(`[${tag}]`, payload ?? {});
}

export function pauseTimelineSpeech(): void {
  cancelSpeech();
}
