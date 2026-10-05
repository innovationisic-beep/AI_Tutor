"use client";

import { BoardMarkerIcon } from "@/components/ai/BoardMarkerIcon";

type Props = {
  x: number;
  y: number;
  fontSize: number;
};

/** Board marker that follows the active writing position in VTSE text. */
export function TeacherWritingMarker({ x, y, fontSize }: Props) {
  const height = Math.max(7, fontSize * 0.55);
  return (
    <BoardMarkerIcon variant="svg" x={x} y={y} height={height} />
  );
}
