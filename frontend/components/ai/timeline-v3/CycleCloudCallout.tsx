"use client";

import {
  cycleCloudContentRect,
  type CycleCloudPlacement,
} from "@/lib/instruction-timeline-v3/teaching/cycleCloudLayout";
import type { SpeechRevealPhase } from "@/lib/instruction-timeline-v3/teaching/speechSyncedReveal";
import type { ViewportBox } from "@/lib/instruction-timeline-v3/teaching/teachingClusters";
import { TeachingExplanationText } from "@/components/ai/timeline-v3/TeachingExplanationText";

const CALLOUT_RADIUS = 14;

type Props = {
  projectionId: string;
  box: ViewportBox;
  height: number;
  layoutLines: string[];
  visibleLines: string[];
  fontSize: number;
  lineHeight: number;
  opacity: number;
  placement: CycleCloudPlacement;
  nodeBox: ViewportBox;
  phase: "active" | "passive" | "compressed" | "transient";
  teaching: boolean;
  speechPhase?: SpeechRevealPhase | null;
  keywordTitle?: string;
};

export function CycleCloudCallout({
  projectionId,
  box,
  height,
  layoutLines,
  visibleLines,
  fontSize,
  lineHeight,
  opacity,
  placement,
  phase,
  teaching,
  speechPhase = null,
  keywordTitle,
}: Props) {
  const content = cycleCloudContentRect(box, height);
  const fillBg =
    phase === "active"
      ? "rgba(255, 255, 255, 0.98)"
      : phase === "passive"
        ? "rgba(248, 250, 252, 0.96)"
        : "rgba(241, 245, 249, 0.92)";
  const strokeColor = phase === "active" ? "#dbeafe" : "#e2e8f0";

  return (
    <g opacity={opacity} data-cycle-callout={placement}>
      <rect
        x={box.x}
        y={box.y}
        width={box.w}
        height={height}
        rx={CALLOUT_RADIUS}
        ry={CALLOUT_RADIUS}
        fill={fillBg}
        stroke={strokeColor}
        strokeWidth={phase === "active" ? 1.1 : 0.9}
        filter={phase === "active" && teaching ? "url(#v3-cloud-shadow)" : "url(#v3-soft-shadow)"}
      />
      <TeachingExplanationText
        idPrefix={projectionId}
        layoutLines={layoutLines}
        visibleLines={visibleLines}
        originX={content.x}
        originY={content.y}
        lineHeight={lineHeight}
        fontSize={fontSize}
        speechPhase={speechPhase}
        keywordTitle={keywordTitle}
        teaching={teaching}
      />
      <title>{visibleLines.join("\n") || projectionId}</title>
    </g>
  );
}
