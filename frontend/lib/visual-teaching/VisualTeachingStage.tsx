"use client";

import { useCallback, useEffect, useRef, useState, type PointerEvent } from "react";
import { AuthImage } from "@/components/media/AuthImage";
import { VisualTeachingOverlay } from "./VisualTeachingOverlay";
import { clientToNorm } from "./drawGeometry";
import { fitImageBox, type FitBox } from "./fitImageBox";
import type {
  VisualState,
  VisualTeachingAnchor,
  VisualTeachingConnection,
  VisualTeachingRegion,
} from "./types";
import { cn } from "@/lib/utils";

export type VisualTeachingStageProps = {
  imageUrl: string;
  alt?: string;
  naturalWidth?: number;
  naturalHeight?: number;
  regions: VisualTeachingRegion[];
  anchors?: VisualTeachingAnchor[];
  connections?: VisualTeachingConnection[];
  visualState?: VisualState | null;
  className?: string;
  imageClassName?: string;
  showAllOutlines?: boolean;
  selectedRegionId?: string | null;
  selectedConnectionId?: string | null;
  /** Scope SVG defs so multi-scene cards do not collide. */
  svgIdScope?: string;
  /** CSS cursor while authoring (crosshair / move / resize). */
  authoringCursor?: string;
  /** Normalized 0..1 image-space pointer for authoring draw tools. */
  onImagePointer?: (pt: { x: number; y: number }, e: PointerEvent) => void;
  onImagePointerMove?: (pt: { x: number; y: number }, e: PointerEvent) => void;
  onImagePointerUp?: (pt: { x: number; y: number }, e: PointerEvent) => void;
  onImagePointerCancel?: (e: PointerEvent) => void;
  onImageError?: () => void;
};

export function VisualTeachingStage({
  imageUrl,
  alt = "",
  naturalWidth: naturalWidthProp,
  naturalHeight: naturalHeightProp,
  regions,
  anchors,
  connections,
  visualState,
  className,
  imageClassName,
  showAllOutlines,
  selectedRegionId,
  selectedConnectionId,
  svgIdScope,
  authoringCursor,
  onImagePointer,
  onImagePointerMove,
  onImagePointerUp,
  onImagePointerCancel,
  onImageError,
}: VisualTeachingStageProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [box, setBox] = useState<FitBox>({ x: 0, y: 0, width: 0, height: 0 });
  const [natural, setNatural] = useState({
    w: naturalWidthProp ?? 0,
    h: naturalHeightProp ?? 0,
  });
  const activePointerId = useRef<number | null>(null);
  const authoring = Boolean(onImagePointer);

  useEffect(() => {
    if (naturalWidthProp && naturalHeightProp) {
      setNatural({ w: naturalWidthProp, h: naturalHeightProp });
    }
  }, [naturalWidthProp, naturalHeightProp]);

  const measure = useCallback(() => {
    const el = containerRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    setBox(fitImageBox(rect.width, rect.height, natural.w || 1, natural.h || 1));
  }, [natural.w, natural.h]);

  useEffect(() => {
    measure();
    const el = containerRef.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => measure());
    ro.observe(el);
    return () => ro.disconnect();
  }, [measure]);

  const toNorm = (clientX: number, clientY: number, clamp: boolean) => {
    const el = containerRef.current;
    if (!el) return null;
    return clientToNorm(
      clientX,
      clientY,
      el.getBoundingClientRect(),
      box,
      { clamp }
    );
  };

  return (
    <div
      ref={containerRef}
      className={cn(
        "relative w-full overflow-hidden bg-slate-100 dark:bg-slate-900",
        authoring && "select-none touch-none",
        className
      )}
      style={authoringCursor ? { cursor: authoringCursor } : undefined}
      onDragStart={(e) => {
        if (authoring) e.preventDefault();
      }}
      onPointerDown={(e) => {
        if (!onImagePointer) return;
        if (e.button !== 0) return;
        const pt = toNorm(e.clientX, e.clientY, false);
        if (!pt) return;
        e.preventDefault();
        activePointerId.current = e.pointerId;
        try {
          e.currentTarget.setPointerCapture(e.pointerId);
        } catch {
          /* ignore */
        }
        onImagePointer(pt, e);
      }}
      onPointerMove={(e) => {
        if (!onImagePointerMove) return;
        const clamping =
          activePointerId.current === e.pointerId || e.buttons === 1;
        const pt = toNorm(e.clientX, e.clientY, clamping);
        if (pt) onImagePointerMove(pt, e);
      }}
      onPointerUp={(e) => {
        if (!onImagePointerUp) return;
        const pt = toNorm(e.clientX, e.clientY, true);
        if (pt) onImagePointerUp(pt, e);
        if (activePointerId.current === e.pointerId) {
          activePointerId.current = null;
        }
        try {
          if (e.currentTarget.hasPointerCapture?.(e.pointerId)) {
            e.currentTarget.releasePointerCapture(e.pointerId);
          }
        } catch {
          /* already released */
        }
      }}
      onPointerCancel={(e) => {
        activePointerId.current = null;
        onImagePointerCancel?.(e);
        try {
          if (e.currentTarget.hasPointerCapture?.(e.pointerId)) {
            e.currentTarget.releasePointerCapture(e.pointerId);
          }
        } catch {
          /* ignore */
        }
      }}
    >
      <AuthImage
        src={imageUrl}
        alt={alt}
        onLoadError={onImageError}
        className={cn(
          "pointer-events-none h-full w-full object-contain",
          imageClassName
        )}
        onDecoded={(img) => {
          if (img.naturalWidth > 0 && img.naturalHeight > 0) {
            setNatural({ w: img.naturalWidth, h: img.naturalHeight });
          }
        }}
      />
      {box.width > 0 && box.height > 0 ? (
        <div
          className="pointer-events-none absolute"
          style={{
            left: box.x,
            top: box.y,
            width: box.width,
            height: box.height,
          }}
        >
          <VisualTeachingOverlay
            regions={regions}
            anchors={anchors}
            connections={connections}
            visualState={visualState}
            showAllOutlines={showAllOutlines}
            selectedRegionId={selectedRegionId}
            selectedConnectionId={selectedConnectionId}
            svgIdScope={svgIdScope}
          />
        </div>
      ) : null}
    </div>
  );
}
