"use client";

import { useMemo } from "react";
import {
  geometryToSvgPaths,
  regionById,
  resolveConnectionLabelBox,
  resolveFocusPoint,
  resolveLabelBox,
} from "./geometry";
import type {
  VisualState,
  VisualTeachingAnchor,
  VisualTeachingConnection,
  VisualTeachingRegion,
} from "./types";
import { SVG_VIEWBOX, emptyVisualState } from "./types";
import {
  DEFAULT_ARROW_COLOR,
  DEFAULT_HIGHLIGHT_COLOR,
  DEFAULT_LABEL_BG_COLOR,
  DEFAULT_LABEL_TEXT_COLOR,
  fitLabelFontSize,
  hexToRgba,
  normalizeHexColor,
} from "./regionColors";
import { shortenArrowLine } from "./arrowGeometry";
import { cn } from "@/lib/utils";

export type VisualTeachingOverlayProps = {
  regions: VisualTeachingRegion[];
  anchors?: VisualTeachingAnchor[];
  connections?: VisualTeachingConnection[];
  visualState?: VisualState | null;
  className?: string;
  /** When true, show all region outlines faintly (authoring). */
  showAllOutlines?: boolean;
  /** Highlight a specific region while editing. */
  selectedRegionId?: string | null;
  /** Highlight a specific connection (arrow) while editing. */
  selectedConnectionId?: string | null;
  /**
   * Stable scope for SVG defs (markers/clipPaths) so co-mounted scene cards
   * with the same connection_id/region_id cannot collide.
   * Prefer asset_key or `scene-{index}`; authoring may pass "authoring".
   */
  svgIdScope?: string;
};

/** Sanitize a fragment for use inside an SVG element id. */
export function sanitizeSvgIdPart(raw: string): string {
  const s = String(raw || "")
    .replace(/[^a-zA-Z0-9_-]/g, "_")
    .slice(0, 64);
  return s || "x";
}

export function scopedMarkerId(scope: string, connectionId: string): string {
  return `vt-arrow-${sanitizeSvgIdPart(scope)}-${sanitizeSvgIdPart(connectionId)}`;
}

export function scopedLabelClipId(
  scope: string,
  regionId: string,
  regionIndex: number
): string {
  return `vt-label-clip-${sanitizeSvgIdPart(scope)}-${sanitizeSvgIdPart(regionId)}-${regionIndex}`;
}

export function scopedArrowLabelClipId(
  scope: string,
  connectionId: string
): string {
  return `vt-arrow-label-clip-${sanitizeSvgIdPart(scope)}-${sanitizeSvgIdPart(connectionId)}`;
}

/** Region label font size in SVG viewBox units (~3.2% of viewBox). */
export function regionLabelFontSize(): number {
  return Math.round(SVG_VIEWBOX * 0.032);
}

function regionHighlightHex(region: VisualTeachingRegion | undefined): string {
  return normalizeHexColor(
    region?.highlight_color,
    DEFAULT_HIGHLIGHT_COLOR
  );
}

function connectionArrowHex(c: VisualTeachingConnection): string {
  return normalizeHexColor(c.color, DEFAULT_ARROW_COLOR);
}

/** Arrowhead size in SVG viewBox units (0..1000). */
const ARROW_HEAD = 36;
const ARROW_HEAD_HALF = ARROW_HEAD / 2;

export function VisualTeachingOverlay({
  regions,
  anchors = [],
  connections = [],
  visualState,
  className,
  showAllOutlines = false,
  selectedRegionId = null,
  selectedConnectionId = null,
  svgIdScope = "default",
}: VisualTeachingOverlayProps) {
  const state = visualState ?? emptyVisualState();
  const idScope = sanitizeSvgIdPart(svgIdScope);
  const paths = useMemo(() => geometryToSvgPaths(regions), [regions]);
  const highlightSet = useMemo(
    () => new Set(state.highlights ?? []),
    [state.highlights]
  );
  const labelSet = useMemo(
    () => new Set(state.labels_visible ?? []),
    [state.labels_visible]
  );
  const arrowSet = useMemo(
    () => new Set(state.arrows ?? []),
    [state.arrows]
  );
  const anchorById = useMemo(() => {
    const m = new Map<string, VisualTeachingAnchor>();
    for (const a of anchors) m.set(a.anchor_id, a);
    return m;
  }, [anchors]);

  const zoomRegion = regionById(regions, state.zoom?.region_id);
  let zoomTransform = "";
  if (zoomRegion) {
    const fp = resolveFocusPoint(zoomRegion);
    const cx = fp.x * SVG_VIEWBOX;
    const cy = fp.y * SVG_VIEWBOX;
    const scale = 1.35;
    zoomTransform = `translate(${cx} ${cy}) scale(${scale}) translate(${-cx} ${-cy})`;
  }

  const dimOthers = Boolean(state.dim_others);

  return (
    <svg
      className={cn("pointer-events-none absolute inset-0 h-full w-full", className)}
      viewBox={`0 0 ${SVG_VIEWBOX} ${SVG_VIEWBOX}`}
      preserveAspectRatio="none"
      aria-hidden
    >
      <defs>
        {connections.map((c) => {
          const fill = connectionArrowHex(c);
          return (
            <marker
              key={scopedMarkerId(idScope, c.connection_id)}
              id={scopedMarkerId(idScope, c.connection_id)}
              markerWidth={ARROW_HEAD}
              markerHeight={ARROW_HEAD}
              refX={ARROW_HEAD - 2}
              refY={ARROW_HEAD_HALF}
              orient="auto"
              markerUnits="userSpaceOnUse"
            >
              <path
                d={`M0,0 L${ARROW_HEAD},${ARROW_HEAD_HALF} L0,${ARROW_HEAD} L${ARROW_HEAD * 0.28},${ARROW_HEAD_HALF} Z`}
                fill={fill}
              />
            </marker>
          );
        })}
      </defs>

      <g transform={zoomTransform || undefined}>
        {dimOthers ? (
          <rect
            x={0}
            y={0}
            width={SVG_VIEWBOX}
            height={SVG_VIEWBOX}
            fill="rgba(15,23,42,0.45)"
          />
        ) : null}

        {paths.map((p, pathIndex) => {
          const highlighted = highlightSet.has(p.region_id);
          const selected = selectedRegionId === p.region_id;
          const show = showAllOutlines || highlighted || selected;
          if (!show) return null;

          const region = regionById(regions, p.region_id);
          const hi = regionHighlightHex(region);
          const stroke = selected
            ? "rgb(14 165 233)"
            : highlighted
              ? hi
              : "rgba(148,163,184,0.7)";
          const fill = highlighted
            ? hexToRgba(hi, 0.32)
            : selected
              ? "rgba(56, 189, 248, 0.18)"
              : "rgba(148,163,184,0.08)";
          const strokeWidth = highlighted || selected ? 4 : 2;
          const pathKey = `${p.region_id}#${pathIndex}`;

          if (p.shape === "point") {
            return (
              <circle
                key={pathKey}
                cx={p.cx}
                cy={p.cy}
                r={p.r ?? 10}
                fill={highlighted ? hexToRgba(hi, 0.85) : stroke}
                stroke="#fff"
                strokeWidth={2}
              />
            );
          }
          if (p.shape === "ellipse") {
            return (
              <ellipse
                key={pathKey}
                cx={p.cx}
                cy={p.cy}
                rx={p.rx}
                ry={p.ry}
                fill={fill}
                stroke={stroke}
                strokeWidth={strokeWidth}
              />
            );
          }
          if (!p.d) return null;
          return (
            <path
              key={pathKey}
              d={p.d}
              fill={fill}
              stroke={stroke}
              strokeWidth={strokeWidth}
            />
          );
        })}

        {/* Highlights above dim veil */}
        {dimOthers
          ? paths
              .filter((p) => highlightSet.has(p.region_id))
              .map((p, pathIndex) => {
                const region = regionById(regions, p.region_id);
                const hi = regionHighlightHex(region);
                const hiKey = `hi-${p.region_id}#${pathIndex}`;
                if (p.shape === "point") {
                  return (
                    <circle
                      key={hiKey}
                      cx={p.cx}
                      cy={p.cy}
                      r={p.r ?? 10}
                      fill={hexToRgba(hi, 0.9)}
                      stroke="#fff"
                      strokeWidth={2}
                    />
                  );
                }
                if (p.shape === "ellipse") {
                  return (
                    <ellipse
                      key={hiKey}
                      cx={p.cx}
                      cy={p.cy}
                      rx={p.rx}
                      ry={p.ry}
                      fill={hexToRgba(hi, 0.35)}
                      stroke={hi}
                      strokeWidth={4}
                    />
                  );
                }
                if (!p.d) return null;
                return (
                  <path
                    key={hiKey}
                    d={p.d}
                    fill={hexToRgba(hi, 0.3)}
                    stroke={hi}
                    strokeWidth={4}
                  />
                );
              })
          : null}

        {regions.map((region, regionIndex) => {
          if (!labelSet.has(region.region_id)) return null;
          const box = resolveLabelBox(region);
          const x = box.x * SVG_VIEWBOX;
          const y = box.y * SVG_VIEWBOX;
          const boxW = box.w * SVG_VIEWBOX;
          const boxH = box.h * SVG_VIEWBOX;
          const label = region.label?.trim() || region.region_id;
          const { fontSize, padX } = fitLabelFontSize(
            boxW,
            boxH,
            Math.max(1, label.length)
          );
          const selected = selectedRegionId === region.region_id;
          const bg = normalizeHexColor(
            region.label_bg_color,
            DEFAULT_LABEL_BG_COLOR
          );
          const fg = normalizeHexColor(
            region.label_text_color,
            DEFAULT_LABEL_TEXT_COLOR
          );
          const clipId = scopedLabelClipId(
            idScope,
            region.region_id,
            regionIndex
          );
          return (
            <g key={`label-${region.region_id}#${regionIndex}`}>
              <defs>
                <clipPath id={clipId}>
                  <rect
                    x={x + 1}
                    y={y + 1}
                    width={Math.max(0, boxW - 2)}
                    height={Math.max(0, boxH - 2)}
                    rx={Math.min(8, boxH * 0.25)}
                  />
                </clipPath>
              </defs>
              <rect
                x={x}
                y={y}
                width={boxW}
                height={boxH}
                rx={Math.min(8, boxH * 0.25)}
                fill={hexToRgba(bg, 0.92)}
                stroke={selected ? "rgb(14 165 233)" : "transparent"}
                strokeWidth={selected ? 3 : 0}
              />
              <g clipPath={`url(#${clipId})`}>
                <text
                  x={x + padX}
                  y={y + boxH / 2}
                  fill={fg}
                  fontSize={fontSize}
                  fontWeight={600}
                  fontFamily="system-ui, sans-serif"
                  dominantBaseline="middle"
                >
                  {label}
                </text>
              </g>
              {selected && showAllOutlines ? (
                <rect
                  x={x + boxW - 10}
                  y={y + boxH - 10}
                  width={16}
                  height={16}
                  fill="#fff"
                  stroke="rgb(14 165 233)"
                  strokeWidth={2}
                  rx={2}
                />
              ) : null}
            </g>
          );
        })}

        {state.pointer
          ? (() => {
              const region = regionById(regions, state.pointer);
              if (!region) return null;
              const fp = resolveFocusPoint(region);
              const x = fp.x * SVG_VIEWBOX;
              const y = fp.y * SVG_VIEWBOX;
              return (
                <g key="pointer">
                  <circle
                    cx={x}
                    cy={y}
                    r={14}
                    fill="rgba(14,165,233,0.35)"
                    stroke="rgb(14 165 233)"
                    strokeWidth={3}
                  />
                  <circle cx={x} cy={y} r={5} fill="rgb(14 165 233)" />
                </g>
              );
            })()
          : null}

        {connections.map((c) => {
          if (
            !arrowSet.has(c.connection_id) &&
            !showAllOutlines &&
            selectedConnectionId !== c.connection_id
          ) {
            return null;
          }
          const from = anchorById.get(c.from_anchor);
          const to = anchorById.get(c.to_anchor);
          if (!from || !to) return null;
          const raw = {
            x1: from.point.x * SVG_VIEWBOX,
            y1: from.point.y * SVG_VIEWBOX,
            x2: to.point.x * SVG_VIEWBOX,
            y2: to.point.y * SVG_VIEWBOX,
          };
          const shortened = shortenArrowLine(
            { x: raw.x1, y: raw.y1 },
            { x: raw.x2, y: raw.y2 },
            { startInset: 10, endInset: ARROW_HEAD }
          );
          const line = shortened ?? raw;
          const active =
            arrowSet.has(c.connection_id) ||
            selectedConnectionId === c.connection_id;
          const selected = selectedConnectionId === c.connection_id;
          const arrowHex = connectionArrowHex(c);
          const stroke = selected
            ? arrowHex
            : active
              ? arrowHex
              : hexToRgba(arrowHex, 0.72);
          // Authoring: always show label chrome (placeholder = connection_id).
          // Runtime: show when arrow is active and has text (or id fallback).
          const labelText =
            c.label?.trim() ||
            (showAllOutlines || selected ? c.connection_id : "");
          const showLabelChrome =
            Boolean(labelText) && (active || selected || showAllOutlines);
          const labelBox = showLabelChrome
            ? resolveConnectionLabelBox(c, from.point, to.point)
            : null;
          return (
            <g key={c.connection_id}>
              {showAllOutlines ? (
                <line
                  x1={raw.x1}
                  y1={raw.y1}
                  x2={raw.x2}
                  y2={raw.y2}
                  stroke="transparent"
                  strokeWidth={18}
                />
              ) : null}
              <line
                x1={line.x1}
                y1={line.y1}
                x2={line.x2}
                y2={line.y2}
                stroke={stroke}
                strokeWidth={selected ? 6 : active ? 5 : 3.5}
                strokeLinecap="round"
                markerEnd={`url(#${scopedMarkerId(idScope, c.connection_id)})`}
              />
              {labelBox ? (
                (() => {
                  const x = labelBox.x * SVG_VIEWBOX;
                  const y = labelBox.y * SVG_VIEWBOX;
                  const boxW = labelBox.w * SVG_VIEWBOX;
                  const boxH = labelBox.h * SVG_VIEWBOX;
                  const text = labelText || c.connection_id;
                  const { fontSize, padX } = fitLabelFontSize(
                    boxW,
                    boxH,
                    Math.max(1, text.length)
                  );
                  const labelBg = normalizeHexColor(
                    c.label_bg_color,
                    DEFAULT_LABEL_BG_COLOR
                  );
                  const labelFg = normalizeHexColor(
                    c.label_text_color,
                    DEFAULT_LABEL_TEXT_COLOR
                  );
                  const clipId = scopedArrowLabelClipId(
                    idScope,
                    c.connection_id
                  );
                  return (
                    <g key={`arrow-label-${c.connection_id}`}>
                      <defs>
                        <clipPath id={clipId}>
                          <rect
                            x={x + 1}
                            y={y + 1}
                            width={Math.max(0, boxW - 2)}
                            height={Math.max(0, boxH - 2)}
                            rx={Math.min(8, boxH * 0.25)}
                          />
                        </clipPath>
                      </defs>
                      <rect
                        x={x}
                        y={y}
                        width={boxW}
                        height={boxH}
                        rx={Math.min(8, boxH * 0.25)}
                        fill={hexToRgba(labelBg, 0.92)}
                        stroke={selected ? arrowHex : "transparent"}
                        strokeWidth={selected ? 3 : 0}
                      />
                      <g clipPath={`url(#${clipId})`}>
                        <text
                          x={x + padX}
                          y={y + boxH / 2}
                          fill={labelFg}
                          fontSize={fontSize}
                          fontWeight={600}
                          fontFamily="system-ui, sans-serif"
                          dominantBaseline="middle"
                        >
                          {text}
                        </text>
                      </g>
                      {selected && showAllOutlines ? (
                        <rect
                          x={x + boxW - 10}
                          y={y + boxH - 10}
                          width={16}
                          height={16}
                          fill="#fff"
                          stroke={arrowHex}
                          strokeWidth={2}
                          rx={2}
                        />
                      ) : null}
                    </g>
                  );
                })()
              ) : null}
              {selected && showAllOutlines ? (
                <>
                  <circle
                    cx={raw.x1}
                    cy={raw.y1}
                    r={11}
                    fill="#fff"
                    stroke={arrowHex}
                    strokeWidth={3}
                  />
                  <circle
                    cx={raw.x2}
                    cy={raw.y2}
                    r={11}
                    fill="#fff"
                    stroke={arrowHex}
                    strokeWidth={3}
                  />
                </>
              ) : null}
            </g>
          );
        })}

        {showAllOutlines
          ? anchors
              .filter((a) => {
                // Endpoint anchors are edited via the arrow, not as free dots.
                const usedByConnection = connections.some(
                  (c) =>
                    c.from_anchor === a.anchor_id || c.to_anchor === a.anchor_id
                );
                return !usedByConnection;
              })
              .map((a) => (
                <g key={`anchor-${a.anchor_id}`}>
                  <circle
                    cx={a.point.x * SVG_VIEWBOX}
                    cy={a.point.y * SVG_VIEWBOX}
                    r={6}
                    fill="rgb(99 102 241)"
                    stroke="#fff"
                    strokeWidth={1.5}
                  />
                </g>
              ))
          : null}

        {/* Authoring resize handles for the selected rect/ellipse. */}
        {selectedRegionId
          ? (() => {
              const region = regions.find((r) => r.region_id === selectedRegionId);
              if (!region) return null;
              const handles: Array<{ x: number; y: number }> = [];
              if (region.shape === "rect") {
                const g = region.geometry as {
                  x: number;
                  y: number;
                  w: number;
                  h: number;
                };
                handles.push(
                  { x: g.x, y: g.y },
                  { x: g.x + g.w, y: g.y },
                  { x: g.x, y: g.y + g.h },
                  { x: g.x + g.w, y: g.y + g.h }
                );
              } else if (region.shape === "ellipse") {
                const g = region.geometry as {
                  cx: number;
                  cy: number;
                  rx: number;
                  ry: number;
                };
                handles.push(
                  { x: g.cx - g.rx, y: g.cy - g.ry },
                  { x: g.cx + g.rx, y: g.cy - g.ry },
                  { x: g.cx - g.rx, y: g.cy + g.ry },
                  { x: g.cx + g.rx, y: g.cy + g.ry }
                );
              } else {
                return null;
              }
              return handles.map((h, i) => (
                <rect
                  key={`handle-${selectedRegionId}-${i}`}
                  x={h.x * SVG_VIEWBOX - 8}
                  y={h.y * SVG_VIEWBOX - 8}
                  width={16}
                  height={16}
                  fill="#fff"
                  stroke="rgb(14 165 233)"
                  strokeWidth={2}
                  rx={2}
                />
              ));
            })()
          : null}
      </g>
    </svg>
  );
}
