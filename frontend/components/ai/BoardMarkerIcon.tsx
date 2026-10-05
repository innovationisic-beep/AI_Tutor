"use client";

import { cn } from "@/lib/utils";

/** Original marker.svg viewBox aspect (width / height). */
const MARKER_ASPECT = 421.5 / 78.786;

type InlineProps = {
  variant: "inline";
  className?: string;
};

type SvgProps = {
  variant: "svg";
  x: number;
  y: number;
  height: number;
  className?: string;
};

type Props = InlineProps | SvgProps;

const MARKER_SRC = "/icons/marker.svg";
/** Tip angles down-left toward the text (counter-clockwise). */
const MARKER_TILT_DEG = -25;

/**
 * Whiteboard marker graphic from marker.svg — used while text is being written.
 */
export function BoardMarkerIcon(props: Props) {
  if (props.variant === "svg") {
    const { x, y, height, className } = props;
    const width = height * MARKER_ASPECT;
    const tipY = height * 0.72;
    // Rotate around the nib tip at (x, y).
    return (
      <g
        transform={`translate(${x}, ${y}) rotate(${MARKER_TILT_DEG}) translate(0, ${-tipY})`}
        className={cn("v3-writing-marker", className)}
        aria-hidden
      >
        <image
          href={MARKER_SRC}
          x={0}
          y={0}
          width={width}
          height={height}
          preserveAspectRatio="xMinYMid meet"
        />
      </g>
    );
  }

  const { className } = props;
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={MARKER_SRC}
      alt=""
      aria-hidden
      className={cn(
        "v3-writing-marker ml-0.5 inline-block h-[0.62em] w-[2.3em] max-w-none align-baseline object-contain object-left",
        "-translate-y-[0.06em] origin-left -rotate-[25deg]",
        className
      )}
    />
  );
}
