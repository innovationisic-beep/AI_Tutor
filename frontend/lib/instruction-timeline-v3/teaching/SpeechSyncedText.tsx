"use client";

import type { SpeechRevealPhase } from "@/lib/instruction-timeline-v3/teaching/speechSyncedReveal";
import {
  TIMELINE_LABEL_FONT_SIZE,
  TIMELINE_SVG_TEXT_CLASS,
} from "@/lib/teachingTypography";
import { cn } from "@/lib/utils";

type SpeechSyncedTextProps = {
  passivePrefix: string;
  activeSuffix: string;
  phase: SpeechRevealPhase | null;
  fontSize?: number;
  fontWeight?: number;
  fill?: string;
  x: number;
  y: number;
  className?: string;
};

/**
 * SVG text with passive + active phrase emphasis (opacity only — no layout jitter).
 */
export function SpeechSyncedText({
  passivePrefix,
  activeSuffix,
  phase,
  fontSize = TIMELINE_LABEL_FONT_SIZE,
  fontWeight = 500,
  fill = "#0f172a",
  x,
  y,
  className = "select-none",
}: SpeechSyncedTextProps): JSX.Element {
  const textClass = cn(TIMELINE_SVG_TEXT_CLASS, className);
  const passiveOpacity = phase === "speaking" && activeSuffix ? 0.78 : 1;
  const activeOpacity = phase === "speaking" ? 1 : phase === "stable" ? 1 : 0.92;

  if (!passivePrefix && !activeSuffix) {
    return (
      <text x={x} y={y} fontSize={fontSize} fontWeight={fontWeight} fill={fill} className={textClass} opacity={0}>
        {" "}
      </text>
    );
  }

  if (!activeSuffix) {
    return (
      <text
        x={x}
        y={y}
        fontSize={fontSize}
        fontWeight={fontWeight}
        fill={fill}
        className={textClass}
        opacity={passiveOpacity}
      >
        {passivePrefix}
      </text>
    );
  }

  const passiveLen = passivePrefix.length;
  const approxCharWidth = fontSize * 0.52;
  const activeX = x + passiveLen * approxCharWidth;

  return (
    <g className={textClass}>
      {passivePrefix ? (
        <text
          x={x}
          y={y}
          fontSize={fontSize}
          fontWeight={fontWeight}
          fill={fill}
          className={textClass}
          opacity={passiveOpacity}
        >
          {passivePrefix}
        </text>
      ) : null}
      <text
        x={activeX}
        y={y}
        fontSize={fontSize}
        fontWeight={fontWeight}
        fill={fill}
        className={textClass}
        opacity={activeOpacity}
        style={phase === "speaking" ? { filter: "url(#v3-speech-active-glow)" } : undefined}
      >
        {activeSuffix}
      </text>
    </g>
  );
}
