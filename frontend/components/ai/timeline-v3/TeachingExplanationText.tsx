"use client";

import { useMemo } from "react";
import { TeacherWritingMarker } from "@/components/ai/timeline-v3/TeacherWritingMarker";
import type { SpeechRevealPhase } from "@/lib/instruction-timeline-v3/teaching/speechSyncedReveal";
import {
  extractTeachingKeywords,
  lineKeywordSegments,
  shouldHighlightLine,
} from "@/lib/instruction-timeline-v3/teaching/teachingKeywordHighlight";
import { TIMELINE_SVG_TEXT_CLASS, timelineCharWidthPx } from "@/lib/teachingTypography";
import { cn } from "@/lib/utils";

export type TeachingExplanationTextProps = {
  idPrefix: string;
  layoutLines: readonly string[];
  visibleLines: readonly string[];
  originX: number;
  /** Top inset inside the card — first baseline is originY + lineHeight. */
  originY: number;
  lineHeight: number;
  fontSize: number;
  speechPhase?: SpeechRevealPhase | null;
  keywordTitle?: string;
  fill?: string;
  fontStyle?: string;
  teaching?: boolean;
};

function lineOpacity(
  lineIndex: number,
  visibleCount: number,
  speechPhase: SpeechRevealPhase | null | undefined,
): number {
  if (speechPhase !== "speaking" || visibleCount === 0) return 1;
  if (lineIndex === visibleCount - 1) return 1;
  if (lineIndex < visibleCount) return 0.82;
  return 0;
}

export function TeachingExplanationText({
  idPrefix,
  layoutLines,
  visibleLines,
  originX,
  originY,
  lineHeight,
  fontSize,
  speechPhase = null,
  keywordTitle,
  fill = "#1e293b",
  fontStyle,
  teaching = true,
}: TeachingExplanationTextProps) {
  const charWidth = timelineCharWidthPx(fontSize);
  const keywords = useMemo(
    () => extractTeachingKeywords(keywordTitle, layoutLines),
    [keywordTitle, layoutLines],
  );
  const showMarker =
    teaching &&
    speechPhase === "speaking" &&
    visibleLines.length > 0 &&
    visibleLines[visibleLines.length - 1].length > 0;

  let markerX = originX;
  let markerY = originY + lineHeight;

  return (
    <g data-v3-explanation-text={idPrefix}>
      {visibleLines.map((line, lineIndex) => {
        const y = originY + (lineIndex + 1) * lineHeight;
        const opacity = lineOpacity(lineIndex, visibleLines.length, speechPhase);
        const highlightLine = shouldHighlightLine(lineIndex, visibleLines.length, speechPhase);
        const segments = lineKeywordSegments(line, keywords);
        let cursorX = originX;

        if (lineIndex === visibleLines.length - 1) {
          markerX = originX + line.length * charWidth;
          markerY = y;
        }

        return (
          <g key={`${idPrefix}-L${lineIndex}`} opacity={opacity}>
            {segments.map((segment, segIndex) => {
              const segWidth = Math.max(charWidth, segment.text.length * charWidth);
              const x = cursorX;
              cursorX += segWidth;
              const showHighlight = highlightLine && segment.highlight && !/^\s+$/u.test(segment.text);

              return (
                <g key={`${idPrefix}-L${lineIndex}-S${segIndex}`}>
                  {showHighlight ? (
                    <rect
                      x={x}
                      y={y - fontSize * 0.78}
                      width={segWidth}
                      height={fontSize * 0.32}
                      rx={2}
                      fill="rgba(251, 191, 36, 0.42)"
                      stroke="rgba(245, 158, 11, 0.35)"
                      strokeWidth={0.5}
                    />
                  ) : null}
                  <text
                    x={x}
                    y={y}
                    fontSize={fontSize}
                    fontStyle={fontStyle}
                    fill={fill}
                    className={cn(TIMELINE_SVG_TEXT_CLASS, "select-none")}
                  >
                    {segment.text}
                  </text>
                  {showHighlight ? (
                    <line
                      x1={x}
                      x2={x + segWidth}
                      y1={y + 2}
                      y2={y + 2}
                      stroke="rgba(217, 119, 6, 0.55)"
                      strokeWidth={1.25}
                      strokeLinecap="round"
                    />
                  ) : null}
                </g>
              );
            })}
          </g>
        );
      })}
      {showMarker ? <TeacherWritingMarker x={markerX} y={markerY} fontSize={fontSize} /> : null}
    </g>
  );
}
