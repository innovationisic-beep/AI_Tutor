import type { ComparisonRowCell, ComparisonRowUnit } from "@/lib/instruction-timeline-v3/teaching/comparisonRowRenderer";
import {
  COMPARISON_ROW_FONT_SIZE,
  COMPARISON_ROW_LAYOUT_MAX_LINES,
  COMPARISON_ROW_LINE_HEIGHT,
  COMPARISON_ROW_PAD,
  comparisonRowCharsPerLine,
  reflowComparisonRowUnits,
} from "@/lib/instruction-timeline-v3/teaching/comparisonRowRenderer";
import {
  teachingExplanationPlain,
  wrapTeachingExplanationForRow,
} from "@/lib/instruction-timeline-v3/teaching/teachingExplanationBullets";
import {
  resolveSpeechDisplayText,
  type SpeechRevealState,
} from "@/lib/instruction-timeline-v3/teaching/speechSyncedReveal";
import { TeachingExplanationText } from "@/components/ai/timeline-v3/TeachingExplanationText";
import {
  TIMELINE_COMPARISON_DIMENSION_FONT_SIZE,
  TIMELINE_COMPARISON_DIMENSION_RESERVE,
  TIMELINE_SVG_TEXT_CLASS,
} from "@/lib/teachingTypography";
import { cn } from "@/lib/utils";

type RowRenderOpts = {
  enterAnimIds: ReadonlySet<string>;
  useEnterMotion: boolean;
  speechRevealByEntityId?: Readonly<Record<string, SpeechRevealState>>;
  speechRevealEnabled?: boolean;
};

/** Same reveal rules for left and right — stable text never clears when the other side speaks. */
function resolveCellVisibleText(
  fullText: string,
  reveal: SpeechRevealState | undefined,
  speech: ReturnType<typeof resolveSpeechDisplayText>,
  speechEnabled: boolean,
): string {
  if (!speechEnabled || !reveal) return fullText;
  if (reveal.phase === "stable") return fullText;
  if (reveal.phase === "speaking") return speech.visibleText || fullText;
  return speech.visibleText;
}

function cellOpacity(phase: ComparisonRowUnit["phase"], sideVisible: boolean): number {
  if (!sideVisible) return 0;
  if (phase === "active") return 1;
  if (phase === "passive") return 0.78;
  return 0;
}

function renderCell(
  cell: ComparisonRowCell,
  phase: ComparisonRowUnit["phase"],
  dimension: string | null,
  opts: RowRenderOpts,
): JSX.Element | null {
  if (!cell.visible) return null;
  const opacity = cellOpacity(phase, cell.visible);
  const fullText = teachingExplanationPlain(cell.text);
  const reveal = opts.speechRevealByEntityId?.[cell.entityId];
  const speechEnabled = Boolean(opts.speechRevealEnabled);
  const speech = resolveSpeechDisplayText(fullText, reveal, speechEnabled);
  const visibleText = resolveCellVisibleText(fullText, reveal, speech, speechEnabled);
  const pad = COMPARISON_ROW_PAD;
  const lineHeight = COMPARISON_ROW_LINE_HEIGHT;
  const fontSize = COMPARISON_ROW_FONT_SIZE;
  const isActive = phase === "active";
  const showDimension = Boolean(dimension && isActive);
  const maxChars = comparisonRowCharsPerLine(cell.box.w, fontSize, pad);
  const layoutLines = wrapTeachingExplanationForRow(
    cell.text,
    maxChars,
    COMPARISON_ROW_LAYOUT_MAX_LINES,
  );
  const lines = visibleText
    ? wrapTeachingExplanationForRow(visibleText, maxChars, COMPARISON_ROW_LAYOUT_MAX_LINES)
    : [];
  const dimensionReserve = showDimension ? TIMELINE_COMPARISON_DIMENSION_RESERVE : 0;
  const h = cell.box.h;
  const enterKey = `row-${cell.entityId}`;
  const textClass = cn(TIMELINE_SVG_TEXT_CLASS, "select-none");
  const textY = (lineIndex: number) =>
    cell.box.y + pad + dimensionReserve + (lineIndex + 1) * lineHeight;

  return (
    <g
      key={cell.entityId}
      data-comparison-side={cell.side}
      data-comparison-row-phase={phase}
      opacity={opacity}
      className={opts.useEnterMotion && opts.enterAnimIds.has(enterKey) ? "v3-node-enter" : undefined}
    >
      <rect
        x={cell.box.x}
        y={cell.box.y}
        width={cell.box.w}
        height={h}
        rx={12}
        fill={isActive ? "rgba(239, 246, 255, 0.98)" : "rgba(248, 250, 252, 0.94)"}
        stroke={isActive ? "#38bdf8" : "#cbd5e1"}
        strokeWidth={isActive ? 2 : 1.25}
        filter="url(#v3-node-shadow)"
      />
      {layoutLines.map((line, i) => (
        <text
          key={`${cell.entityId}-layout-${i}`}
          x={cell.box.x + pad}
          y={textY(i)}
          fontSize={fontSize}
          fill="transparent"
          aria-hidden
        >
          {line}
        </text>
      ))}
      {showDimension ? (
        <text
          x={cell.box.x + pad}
          y={cell.box.y + pad + 2}
          fontSize={TIMELINE_COMPARISON_DIMENSION_FONT_SIZE}
          fontWeight={700}
          fill="#64748b"
          className={cn(textClass, "uppercase")}
        >
          {dimension}
        </text>
      ) : null}
      {lines.length > 0 ? (
        <TeachingExplanationText
          idPrefix={cell.entityId}
          layoutLines={layoutLines}
          visibleLines={lines}
          originX={cell.box.x + pad}
          originY={cell.box.y + pad + dimensionReserve}
          lineHeight={lineHeight}
          fontSize={fontSize}
          speechPhase={speech.phase}
          keywordTitle={dimension ?? undefined}
          teaching
        />
      ) : null}
    </g>
  );
}

export function ComparisonRowRendererView({
  units,
  opts,
}: {
  units: ComparisonRowUnit[];
  opts: RowRenderOpts;
}): JSX.Element {
  const laidOutUnits = reflowComparisonRowUnits(units);
  return (
    <g data-v3-comparison-rows="1" data-comparison-render-mode="row_aligned">
      {laidOutUnits.map((unit) => {
        if (unit.phase === "hidden") return null;
        const showRowBand = unit.phase === "active" && unit.rowBox.w > 0;
        return (
          <g key={`comparison-row-${unit.pairIndex}`} data-pair-index={unit.pairIndex}>
            {showRowBand ? (
              <rect
                x={unit.rowBox.x - 6}
                y={unit.rowBox.y - 6}
                width={unit.rowBox.w + 12}
                height={unit.rowBox.h + 12}
                rx={14}
                fill="rgba(251, 191, 36, 0.05)"
                stroke="rgba(245, 158, 11, 0.28)"
                strokeWidth={1.5}
                pointerEvents="none"
              />
            ) : null}
            {unit.left ? renderCell(unit.left, unit.phase, unit.dimension, opts) : null}
            {unit.right ? renderCell(unit.right, unit.phase, unit.dimension, opts) : null}
          </g>
        );
      })}
    </g>
  );
}
