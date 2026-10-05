"use client";

import { useMemo, useRef, useState, type Dispatch, type ReactNode, type SetStateAction } from "react";
import {
  ArrowDown,
  ArrowUp,
  Check,
  Loader2,
  Plus,
  Trash2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { AuthImage } from "@/components/media/AuthImage";
import {
  uploadVisualTeachingImage,
  visualTeachingImageUrl,
  type VisualTeachingAnchorInput,
  type VisualTeachingConnectionInput,
  type VisualTeachingImageInput,
  type VisualTeachingImageUpload,
  type VisualTeachingRegionInput,
} from "@/lib/api/curriculumStructure";
import {
  emptyVisualState,
  normalizeRegionGeometry,
  validateRegionGeometry,
  VisualTeachingStage,
  type RegionShape,
} from "@/lib/visual-teaching";
import {
  dragToCircle,
  dragToRect,
  defaultLabelBoxNear,
  ellipseHandles,
  hitResizeHandle,
  isCircleEllipse,
  isMeaningfulDrag,
  isNearSquare,
  moveEllipse,
  moveLabelBox,
  moveRect,
  pointInEllipse,
  pointInRect,
  rectHandles,
  resizeCircle,
  resizeLabelBox,
  resizeRect,
  toolToRegionShape,
  cursorForHandle,
  type DrawTool,
  type NormEllipse,
  type NormPt,
  type NormRect,
  type ResizeHandle,
} from "@/lib/visual-teaching/drawGeometry";
import {
  arrowEndpointIds,
  clamp01Pt,
  hitArrow,
  nextArrowConnectionId,
  type ArrowHit,
} from "@/lib/visual-teaching/arrowGeometry";
import {
  DEFAULT_ARROW_COLOR,
  DEFAULT_HIGHLIGHT_COLOR,
  DEFAULT_LABEL_BG_COLOR,
  DEFAULT_LABEL_TEXT_COLOR,
} from "@/lib/visual-teaching/regionColors";
import { resolveFocusPoint, resolveLabelBox, resolveConnectionLabelBox } from "@/lib/visual-teaching/geometry";
import type { CurriculumTopicSource } from "@/lib/types";
import { cn } from "@/lib/utils";

type AnnotateTarget = "shape" | "label";

type AnnotateGesture =
  | { mode: "idle" }
  | {
      mode: "drawing";
      origin: NormPt;
      current: NormPt;
      pointerId: number;
    }
  | {
      mode: "moving";
      target: AnnotateTarget;
      regionId: string;
      origin: NormPt;
      initial: NormRect | NormEllipse;
      shape: "rect" | "ellipse";
      pointerId: number;
    }
  | {
      mode: "resizing";
      target: AnnotateTarget;
      regionId: string;
      handle: ResizeHandle;
      initial: NormRect | NormEllipse;
      shape: "rect" | "ellipse";
      lockAspect: boolean;
      pointerId: number;
    }
  | {
      mode: "moving_arrow";
      connectionId: string;
      hit: ArrowHit;
      origin: NormPt;
      initialFrom: NormPt;
      initialTo: NormPt;
      pointerId: number;
    }
  | {
      mode: "moving_arrow_label";
      connectionId: string;
      origin: NormPt;
      initial: NormRect;
      pointerId: number;
    }
  | {
      mode: "resizing_arrow_label";
      connectionId: string;
      handle: ResizeHandle;
      initial: NormRect;
      pointerId: number;
    };

export function useImageAnnotation(opts: {
  images: VisualTeachingImageInput[];
  setImages: Dispatch<SetStateAction<VisualTeachingImageInput[]>>;
  selectedIndex: number;
  markDirty: () => void;
  /** True while the Annotate surface is the one receiving pointer events. */
  active: boolean;
  onNotify?: (msg: string, variant?: "ok" | "err") => void;
}) {
  const { images, setImages, selectedIndex, markDirty, active, onNotify } = opts;
  const [drawTool, setDrawTool] = useState<DrawTool>("rectangle");
  const [gesture, setGesture] = useState<AnnotateGesture>({ mode: "idle" });
  const gestureRef = useRef<AnnotateGesture>({ mode: "idle" });
  const [selectedRegionId, setSelectedRegionId] = useState<string | null>(null);
  const [selectedConnectionId, setSelectedConnectionId] = useState<string | null>(null);
  const [hoverCursor, setHoverCursor] = useState<string | null>(null);

  function setAnnotateGesture(next: AnnotateGesture) {
    gestureRef.current = next;
    setGesture(next);
  }

  const selected = images[selectedIndex] ?? null;

  function patchImage(index: number, patch: Partial<VisualTeachingImageInput>) {
    setImages((prev) => prev.map((img, i) => (i === index ? { ...img, ...patch } : img)));
    markDirty();
  }

  function addRegion(geometry: Record<string, unknown>, shape: RegionShape) {
    if (!selected) return;
    const check = validateRegionGeometry(shape, geometry);
    if (!check.ok) {
      onNotify?.(check.message, "err");
      return;
    }
    const existing = selected.regions ?? [];
    const used = new Set(existing.map((r) => r.region_id));
    let n = 1;
    while (used.has(`region_${n}`)) n += 1;
    const region_id = `region_${n}`;
    const normalized = normalizeRegionGeometry(
      shape,
      geometry
    ) as Record<string, unknown>;
    const tempRegion = {
      region_id,
      label: "",
      teaching_purpose: "",
      sort_order: existing.length,
      shape,
      geometry: normalized as never,
      focus_point: null,
      label_box: null,
    };
    const focus = resolveFocusPoint(tempRegion);
    const label_box = defaultLabelBoxNear(focus, region_id.length);
    const next: VisualTeachingRegionInput = {
      region_id,
      label: "",
      teaching_purpose: "",
      shape,
      geometry: normalized,
      focus_point: focus,
      label_box,
      highlight_color: DEFAULT_HIGHLIGHT_COLOR,
      label_bg_color: DEFAULT_LABEL_BG_COLOR,
      label_text_color: DEFAULT_LABEL_TEXT_COLOR,
    };
    patchImage(selectedIndex, { regions: [...existing, next] });
    setSelectedRegionId(region_id);
    setSelectedConnectionId(null);
    setAnnotateGesture({ mode: "idle" });
  }

  function connectionEndpoints(
    connectionId: string
  ): { from: NormPt; to: NormPt; fromId: string; toId: string } | null {
    if (!selected) return null;
    const c = (selected.connections ?? []).find(
      (row) => row.connection_id === connectionId
    );
    if (!c) return null;
    const fromA = (selected.anchors ?? []).find(
      (a) => a.anchor_id === c.from_anchor
    );
    const toA = (selected.anchors ?? []).find(
      (a) => a.anchor_id === c.to_anchor
    );
    if (!fromA || !toA) return null;
    return {
      from: { ...fromA.point },
      to: { ...toA.point },
      fromId: c.from_anchor,
      toId: c.to_anchor,
    };
  }

  function addArrow(from: NormPt, to: NormPt) {
    if (!selected) return;
    const fromPt = clamp01Pt(from);
    const toPt = clamp01Pt(to);
    if (!isMeaningfulDrag(fromPt, toPt)) {
      onNotify?.("Drag a little farther to place an arrow", "err");
      return;
    }
    const connections = selected.connections ?? [];
    const anchors = selected.anchors ?? [];
    const connection_id = nextArrowConnectionId(
      connections.map((c) => c.connection_id)
    );
    const ids = arrowEndpointIds(connection_id);
    if (
      anchors.some((a) => a.anchor_id === ids.from || a.anchor_id === ids.to)
    ) {
      onNotify?.("Arrow endpoint ids collide with existing anchors", "err");
      return;
    }
    const nextAnchors: VisualTeachingAnchorInput[] = [
      ...anchors,
      { anchor_id: ids.from, label: "", point: fromPt },
      { anchor_id: ids.to, label: "", point: toPt },
    ];
    const nextConn: VisualTeachingConnectionInput = {
      connection_id,
      from_anchor: ids.from,
      to_anchor: ids.to,
      label: "",
      teaching_purpose: "",
      kind: "flow",
      color: DEFAULT_ARROW_COLOR,
      label_bg_color: DEFAULT_LABEL_BG_COLOR,
      label_text_color: DEFAULT_LABEL_TEXT_COLOR,
      label_box: defaultLabelBoxNear(
        {
          x: (fromPt.x + toPt.x) / 2,
          y: (fromPt.y + toPt.y) / 2,
        },
        connection_id.length
      ),
    };
    patchImage(selectedIndex, {
      anchors: nextAnchors,
      connections: [...connections, nextConn],
    });
    setSelectedConnectionId(connection_id);
    setSelectedRegionId(null);
    setAnnotateGesture({ mode: "idle" });
  }

  function patchArrowPoints(
    connectionId: string,
    from: NormPt,
    to: NormPt
  ) {
    if (!selected) return;
    const ends = connectionEndpoints(connectionId);
    if (!ends) return;
    const fromPt = clamp01Pt(from);
    const toPt = clamp01Pt(to);
    patchImage(selectedIndex, {
      anchors: (selected.anchors ?? []).map((a) => {
        if (a.anchor_id === ends.fromId) return { ...a, point: fromPt };
        if (a.anchor_id === ends.toId) return { ...a, point: toPt };
        return a;
      }),
    });
  }

  function deleteArrow(connectionId: string) {
    if (!selected) return;
    const conn = (selected.connections ?? []).find(
      (c) => c.connection_id === connectionId
    );
    if (!conn) return;
    const other = (selected.connections ?? []).filter(
      (c) => c.connection_id !== connectionId
    );
    const stillUsed = new Set(
      other.flatMap((c) => [c.from_anchor, c.to_anchor])
    );
    const drop = new Set(
      [conn.from_anchor, conn.to_anchor].filter((id) => !stillUsed.has(id))
    );
    patchImage(selectedIndex, {
      connections: other,
      anchors: (selected.anchors ?? []).filter((a) => !drop.has(a.anchor_id)),
    });
    if (selectedConnectionId === connectionId) setSelectedConnectionId(null);
  }

  function patchSelectedGeometry(
    regionId: string,
    geometry: Record<string, unknown>
  ) {
    if (!selected) return;
    const regions = (selected.regions ?? []).map((row) =>
      row.region_id === regionId ? { ...row, geometry } : row
    );
    patchImage(selectedIndex, { regions });
  }

  function patchSelectedLabelBox(regionId: string, label_box: NormRect) {
    if (!selected) return;
    const regions = (selected.regions ?? []).map((row) =>
      row.region_id === regionId
        ? {
            ...row,
            label_box,
            focus_point: {
              x: label_box.x + label_box.w * 0.1,
              y: label_box.y + label_box.h,
            },
          }
        : row
    );
    patchImage(selectedIndex, { regions });
  }

  function patchArrowLabelBox(connectionId: string, label_box: NormRect) {
    if (!selected) return;
    patchImage(selectedIndex, {
      connections: (selected.connections ?? []).map((c) =>
        c.connection_id === connectionId ? { ...c, label_box } : c
      ),
    });
  }

  function connectionLabelBox(
    c: VisualTeachingConnectionInput,
    from: NormPt,
    to: NormPt
  ): NormRect {
    return resolveConnectionLabelBox(
      {
        connection_id: c.connection_id,
        label: c.label ?? "",
        label_box: c.label_box ?? null,
      },
      from,
      to
    );
  }

  function regionAsOverlay(r: VisualTeachingRegionInput) {
    return {
      region_id: r.region_id,
      label: r.label ?? "",
      teaching_purpose: r.teaching_purpose ?? "",
      sort_order: 0,
      shape: r.shape,
      geometry: r.geometry as never,
      focus_point: r.focus_point,
      label_box: r.label_box ?? null,
      highlight_color: r.highlight_color ?? null,
      label_bg_color: r.label_bg_color ?? null,
      label_text_color: r.label_text_color ?? null,
    };
  }

  function onAnnotatePointerDown(pt: NormPt, e: { pointerId: number }) {
    if (!active || !selected) return;

    const regions = selected.regions ?? [];
    const connections = selected.connections ?? [];
    const anchors = selected.anchors ?? [];
    const anchorById = new Map(anchors.map((a) => [a.anchor_id, a]));
    const sel = regions.find((r) => r.region_id === selectedRegionId);
    const selConn = connections.find(
      (c) => c.connection_id === selectedConnectionId
    );

    // Selected arrow: label resize/move first, then endpoints/body.
    if (selConn) {
      const fromA = anchorById.get(selConn.from_anchor);
      const toA = anchorById.get(selConn.to_anchor);
      if (fromA && toA) {
        const labelBox = connectionLabelBox(selConn, fromA.point, toA.point);
        const labelHandle = hitResizeHandle(pt, rectHandles(labelBox), 0.045);
        if (labelHandle) {
          setAnnotateGesture({
            mode: "resizing_arrow_label",
            connectionId: selConn.connection_id,
            handle: labelHandle,
            initial: { ...labelBox },
            pointerId: e.pointerId,
          });
          return;
        }
        if (pointInRect(pt, labelBox)) {
          setAnnotateGesture({
            mode: "moving_arrow_label",
            connectionId: selConn.connection_id,
            origin: pt,
            initial: { ...labelBox },
            pointerId: e.pointerId,
          });
          return;
        }
        const hit = hitArrow(pt, fromA.point, toA.point);
        if (hit) {
          setAnnotateGesture({
            mode: "moving_arrow",
            connectionId: selConn.connection_id,
            hit,
            origin: pt,
            initialFrom: { ...fromA.point },
            initialTo: { ...toA.point },
            pointerId: e.pointerId,
          });
          return;
        }
      }
    }

    // Label handles / body on selected region.
    if (sel) {
      const labelBox = resolveLabelBox(regionAsOverlay(sel));
      const labelHandle = hitResizeHandle(pt, rectHandles(labelBox), 0.045);
      if (labelHandle) {
        setSelectedConnectionId(null);
        setAnnotateGesture({
          mode: "resizing",
          target: "label",
          regionId: sel.region_id,
          handle: labelHandle,
          initial: { ...labelBox },
          shape: "rect",
          lockAspect: false,
          pointerId: e.pointerId,
        });
        return;
      }
      if (pointInRect(pt, labelBox)) {
        setSelectedConnectionId(null);
        setAnnotateGesture({
          mode: "moving",
          target: "label",
          regionId: sel.region_id,
          origin: pt,
          initial: { ...labelBox },
          shape: "rect",
          pointerId: e.pointerId,
        });
        return;
      }
    }

    // Shape resize / move on selected region.
    if (sel && (sel.shape === "rect" || sel.shape === "ellipse")) {
      if (sel.shape === "rect") {
        const g = sel.geometry as NormRect;
        const handle = hitResizeHandle(pt, rectHandles(g));
        if (handle) {
          setSelectedConnectionId(null);
          setAnnotateGesture({
            mode: "resizing",
            target: "shape",
            regionId: sel.region_id,
            handle,
            initial: { ...g },
            shape: "rect",
            lockAspect: isNearSquare(g),
            pointerId: e.pointerId,
          });
          return;
        }
        if (pointInRect(pt, g)) {
          setSelectedConnectionId(null);
          setAnnotateGesture({
            mode: "moving",
            target: "shape",
            regionId: sel.region_id,
            origin: pt,
            initial: { ...g },
            shape: "rect",
            pointerId: e.pointerId,
          });
          return;
        }
      } else {
        const g = sel.geometry as NormEllipse;
        const handle = hitResizeHandle(pt, ellipseHandles(g));
        if (handle) {
          setSelectedConnectionId(null);
          setAnnotateGesture({
            mode: "resizing",
            target: "shape",
            regionId: sel.region_id,
            handle,
            initial: { ...g },
            shape: "ellipse",
            lockAspect: isCircleEllipse(g),
            pointerId: e.pointerId,
          });
          return;
        }
        if (pointInEllipse(pt, g)) {
          setSelectedConnectionId(null);
          setAnnotateGesture({
            mode: "moving",
            target: "shape",
            regionId: sel.region_id,
            origin: pt,
            initial: { ...g },
            shape: "ellipse",
            pointerId: e.pointerId,
          });
          return;
        }
      }
    }

    // Hit another region's label or shape.
    for (let i = regions.length - 1; i >= 0; i--) {
      const r = regions[i]!;
      const labelBox = resolveLabelBox(regionAsOverlay(r));
      if (pointInRect(pt, labelBox)) {
        setSelectedRegionId(r.region_id);
        setSelectedConnectionId(null);
        setAnnotateGesture({
          mode: "moving",
          target: "label",
          regionId: r.region_id,
          origin: pt,
          initial: { ...labelBox },
          shape: "rect",
          pointerId: e.pointerId,
        });
        return;
      }
      if (r.shape === "rect") {
        const g = r.geometry as NormRect;
        if (pointInRect(pt, g)) {
          setSelectedRegionId(r.region_id);
          setSelectedConnectionId(null);
          setAnnotateGesture({
            mode: "moving",
            target: "shape",
            regionId: r.region_id,
            origin: pt,
            initial: { ...g },
            shape: "rect",
            pointerId: e.pointerId,
          });
          return;
        }
      } else if (r.shape === "ellipse") {
        const g = r.geometry as NormEllipse;
        if (pointInEllipse(pt, g)) {
          setSelectedRegionId(r.region_id);
          setSelectedConnectionId(null);
          setAnnotateGesture({
            mode: "moving",
            target: "shape",
            regionId: r.region_id,
            origin: pt,
            initial: { ...g },
            shape: "ellipse",
            pointerId: e.pointerId,
          });
          return;
        }
      }
    }

    // Hit an existing arrow label or shaft.
    for (let i = connections.length - 1; i >= 0; i--) {
      const c = connections[i]!;
      const fromA = anchorById.get(c.from_anchor);
      const toA = anchorById.get(c.to_anchor);
      if (!fromA || !toA) continue;
      const labelBox = connectionLabelBox(c, fromA.point, toA.point);
      if (pointInRect(pt, labelBox)) {
        setSelectedConnectionId(c.connection_id);
        setSelectedRegionId(null);
        setAnnotateGesture({
          mode: "moving_arrow_label",
          connectionId: c.connection_id,
          origin: pt,
          initial: { ...labelBox },
          pointerId: e.pointerId,
        });
        return;
      }
      const hit = hitArrow(pt, fromA.point, toA.point);
      if (!hit) continue;
      setSelectedConnectionId(c.connection_id);
      setSelectedRegionId(null);
      setAnnotateGesture({
        mode: "moving_arrow",
        connectionId: c.connection_id,
        hit,
        origin: pt,
        initialFrom: { ...fromA.point },
        initialTo: { ...toA.point },
        pointerId: e.pointerId,
      });
      return;
    }

    setSelectedRegionId(null);
    setSelectedConnectionId(null);
    setAnnotateGesture({
      mode: "drawing",
      origin: pt,
      current: pt,
      pointerId: e.pointerId,
    });
  }

  function onAnnotatePointerMove(pt: NormPt) {
    if (!active || !selected) return;
    const g = gestureRef.current;

    if (g.mode === "drawing") {
      setAnnotateGesture({ ...g, current: pt });
      return;
    }

    if (g.mode === "moving_arrow_label") {
      const dx = pt.x - g.origin.x;
      const dy = pt.y - g.origin.y;
      patchArrowLabelBox(g.connectionId, moveLabelBox(g.initial, dx, dy));
      return;
    }

    if (g.mode === "resizing_arrow_label") {
      patchArrowLabelBox(
        g.connectionId,
        resizeLabelBox(g.initial, g.handle, pt)
      );
      return;
    }

    if (g.mode === "moving_arrow") {
      const dx = pt.x - g.origin.x;
      const dy = pt.y - g.origin.y;
      if (g.hit === "from") {
        patchArrowPoints(g.connectionId, clamp01Pt({
          x: g.initialFrom.x + dx,
          y: g.initialFrom.y + dy,
        }), g.initialTo);
      } else if (g.hit === "to") {
        patchArrowPoints(g.connectionId, g.initialFrom, clamp01Pt({
          x: g.initialTo.x + dx,
          y: g.initialTo.y + dy,
        }));
      } else {
        patchArrowPoints(
          g.connectionId,
          clamp01Pt({
            x: g.initialFrom.x + dx,
            y: g.initialFrom.y + dy,
          }),
          clamp01Pt({
            x: g.initialTo.x + dx,
            y: g.initialTo.y + dy,
          })
        );
      }
      return;
    }

    if (g.mode === "moving") {
      const dx = pt.x - g.origin.x;
      const dy = pt.y - g.origin.y;
      if (g.target === "label") {
        patchSelectedLabelBox(
          g.regionId,
          moveLabelBox(g.initial as NormRect, dx, dy)
        );
        return;
      }
      if (g.shape === "rect") {
        patchSelectedGeometry(
          g.regionId,
          moveRect(g.initial as NormRect, dx, dy) as unknown as Record<
            string,
            unknown
          >
        );
      } else {
        patchSelectedGeometry(
          g.regionId,
          moveEllipse(g.initial as NormEllipse, dx, dy) as unknown as Record<
            string,
            unknown
          >
        );
      }
      return;
    }

    if (g.mode === "resizing") {
      if (g.target === "label") {
        patchSelectedLabelBox(
          g.regionId,
          resizeLabelBox(g.initial as NormRect, g.handle, pt)
        );
        return;
      }
      if (g.shape === "rect") {
        patchSelectedGeometry(
          g.regionId,
          resizeRect(g.initial as NormRect, g.handle, pt, {
            lockAspect: g.lockAspect,
          }) as unknown as Record<string, unknown>
        );
      } else {
        patchSelectedGeometry(
          g.regionId,
          resizeCircle(
            g.initial as NormEllipse,
            g.handle,
            pt
          ) as unknown as Record<string, unknown>
        );
      }
      return;
    }

    // Hover cursors
    const regions = selected.regions ?? [];
    const connections = selected.connections ?? [];
    const anchors = selected.anchors ?? [];
    const anchorById = new Map(anchors.map((a) => [a.anchor_id, a]));
    const sel = regions.find((r) => r.region_id === selectedRegionId);
    if (selectedConnectionId) {
      const c = connections.find((row) => row.connection_id === selectedConnectionId);
      const fromA = c ? anchorById.get(c.from_anchor) : null;
      const toA = c ? anchorById.get(c.to_anchor) : null;
      if (c && fromA && toA) {
        const labelBox = connectionLabelBox(c, fromA.point, toA.point);
        const lh = hitResizeHandle(pt, rectHandles(labelBox), 0.045);
        if (lh) {
          setHoverCursor(cursorForHandle(lh));
          return;
        }
        if (pointInRect(pt, labelBox)) {
          setHoverCursor("move");
          return;
        }
        const hit = hitArrow(pt, fromA.point, toA.point);
        if (hit === "from" || hit === "to") {
          setHoverCursor("crosshair");
          return;
        }
        if (hit === "body") {
          setHoverCursor("move");
          return;
        }
      }
    }
    if (sel) {
      const labelBox = resolveLabelBox(regionAsOverlay(sel));
      const lh = hitResizeHandle(pt, rectHandles(labelBox), 0.045);
      if (lh) {
        setHoverCursor(cursorForHandle(lh));
        return;
      }
      if (pointInRect(pt, labelBox)) {
        setHoverCursor("move");
        return;
      }
      if (sel.shape === "rect") {
        const geom = sel.geometry as NormRect;
        const handle = hitResizeHandle(pt, rectHandles(geom));
        if (handle) {
          setHoverCursor(cursorForHandle(handle));
          return;
        }
        if (pointInRect(pt, geom)) {
          setHoverCursor("move");
          return;
        }
      } else if (sel.shape === "ellipse") {
        const geom = sel.geometry as NormEllipse;
        const handle = hitResizeHandle(pt, ellipseHandles(geom));
        if (handle) {
          setHoverCursor(cursorForHandle(handle));
          return;
        }
        if (pointInEllipse(pt, geom)) {
          setHoverCursor("move");
          return;
        }
      }
    }
    for (const c of connections) {
      const fromA = anchorById.get(c.from_anchor);
      const toA = anchorById.get(c.to_anchor);
      if (!fromA || !toA) continue;
      if (hitArrow(pt, fromA.point, toA.point)) {
        setHoverCursor("move");
        return;
      }
    }
    setHoverCursor(null);
  }

  function onAnnotatePointerUp(pt: NormPt) {
    if (!active || !selected) return;
    const g = gestureRef.current;

    if (
      g.mode === "moving" ||
      g.mode === "resizing" ||
      g.mode === "moving_arrow" ||
      g.mode === "moving_arrow_label" ||
      g.mode === "resizing_arrow_label"
    ) {
      setAnnotateGesture({ mode: "idle" });
      return;
    }

    if (g.mode !== "drawing") return;

    const origin = g.origin;
    const end = pt;
    setAnnotateGesture({ mode: "idle" });
    if (!isMeaningfulDrag(origin, end)) return;

    if (drawTool === "arrow") {
      addArrow(origin, end);
      return;
    }

    const shape = toolToRegionShape(drawTool);
    if (drawTool === "circle") {
      addRegion(
        dragToCircle(origin, end) as unknown as Record<string, unknown>,
        shape
      );
    } else if (drawTool === "square") {
      addRegion(
        dragToRect(origin, end, { square: true }) as unknown as Record<
          string,
          unknown
        >,
        shape
      );
    } else {
      addRegion(
        dragToRect(origin, end) as unknown as Record<string, unknown>,
        shape
      );
    }
  }

  function onAnnotatePointerCancel() {
    setAnnotateGesture({ mode: "idle" });
  }

  const authoringCursor =
    gesture.mode === "drawing"
      ? "crosshair"
      : gesture.mode === "moving" ||
          gesture.mode === "moving_arrow" ||
          gesture.mode === "moving_arrow_label"
        ? "move"
        : gesture.mode === "resizing" || gesture.mode === "resizing_arrow_label"
          ? cursorForHandle(gesture.handle)
          : hoverCursor ?? "crosshair";

  const draftPreviewRegions = useMemo(() => {
    if (gesture.mode !== "drawing" || drawTool === "arrow") return [];
    const shape = toolToRegionShape(drawTool);
    let geometry: Record<string, unknown>;
    if (drawTool === "circle") {
      geometry = dragToCircle(gesture.origin, gesture.current) as unknown as Record<
        string,
        unknown
      >;
    } else if (drawTool === "square") {
      geometry = dragToRect(gesture.origin, gesture.current, {
        square: true,
      }) as unknown as Record<string, unknown>;
    } else {
      geometry = dragToRect(
        gesture.origin,
        gesture.current
      ) as unknown as Record<string, unknown>;
    }
    return [
      {
        region_id: "__draft__",
        label: "",
        teaching_purpose: "",
        sort_order: 999,
        shape,
        geometry,
        focus_point: null,
        label_box: null,
      },
    ];
  }, [gesture, drawTool]);

  const draftPreviewArrow = useMemo(() => {
    if (gesture.mode !== "drawing" || drawTool !== "arrow") return null;
    return {
      from: clamp01Pt(gesture.origin),
      to: clamp01Pt(gesture.current),
    };
  }, [gesture, drawTool]);

  return {
    drawTool,
    setDrawTool,
    gesture,
    setAnnotateGesture,
    selectedRegionId,
    setSelectedRegionId,
    selectedConnectionId,
    setSelectedConnectionId,
    setHoverCursor,
    authoringCursor,
    draftPreviewRegions,
    draftPreviewArrow,
    onAnnotatePointerDown,
    onAnnotatePointerMove,
    onAnnotatePointerUp,
    onAnnotatePointerCancel,
    deleteArrow,
    patchImage,
  };
}


export function ImagesPanel({
  conceptId,
  topicSource,
  token,
  busy,
  images,
  selectedIndex,
  committedKeys,
  onSelect,
  onChange,
  onNotify,
  maxImages = 8,
  uploadImage = uploadVisualTeachingImage,
  imageUrl = visualTeachingImageUrl,
}: {
  conceptId: string;
  topicSource: CurriculumTopicSource;
  token: string;
  busy: boolean;
  images: VisualTeachingImageInput[];
  selectedIndex: number;
  committedKeys: Set<string>;
  onSelect: (i: number) => void;
  onChange: (next: VisualTeachingImageInput[]) => void;
  onNotify?: (msg: string, variant?: "ok" | "err") => void;
  maxImages?: number;
  uploadImage?: (
    token: string,
    conceptId: string,
    topicSource: CurriculumTopicSource,
    file: File,
    opts?: { replaceAssetKey?: string }
  ) => Promise<VisualTeachingImageUpload>;
  imageUrl?: (conceptId: string, assetKey: string) => string;
}) {
  const [uploading, setUploading] = useState(false);

  async function addFiles(files: FileList | null) {
    if (!files || files.length === 0) return;
    if (images.length >= maxImages) {
      onNotify?.(`At most ${maxImages} images`, "err");
      return;
    }
    setUploading(true);
    try {
      const added: VisualTeachingImageInput[] = [];
      for (const file of Array.from(files)) {
        if (images.length + added.length >= maxImages) break;
        const up = await uploadImage(
          token,
          conceptId,
          topicSource,
          file
        );
        added.push({
          id: up.id,
          asset_key: up.asset_key,
          storage_key: up.storage_key,
          mime_type: up.mime_type,
          title: "",
          teaching_purpose: "",
          natural_width: up.natural_width,
          natural_height: up.natural_height,
          content_hash: up.content_hash,
          annotations_status: "confirmed",
          regions: [],
          anchors: [],
          connections: [],
        });
      }
      onChange([...images, ...added]);
      onNotify?.(
        `${added.length} image${added.length === 1 ? "" : "s"} uploaded — save to attach.`
      );
    } catch (e) {
      onNotify?.(e instanceof Error ? e.message : "Upload failed", "err");
    } finally {
      setUploading(false);
    }
  }

  async function replaceFile(index: number, file: File | null) {
    if (!file) return;
    setUploading(true);
    try {
      const prev = images[index]!;
      const up = await uploadImage(
        token,
        conceptId,
        topicSource,
        file,
        { replaceAssetKey: prev.asset_key }
      );
      const next = [...images];
      next[index] = {
        ...prev,
        id: up.id,
        storage_key: up.storage_key,
        mime_type: up.mime_type,
        natural_width: up.natural_width,
        natural_height: up.natural_height,
        content_hash: up.content_hash,
        // Server is authoritative — always stale on replace.
        annotations_status:
          up.annotations_status === "stale" ? "stale" : "stale",
      };
      onChange(next);
      onNotify?.("Image replaced — annotations marked stale. Reconfirm after review.");
    } catch (e) {
      onNotify?.(e instanceof Error ? e.message : "Replace failed", "err");
    } finally {
      setUploading(false);
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
          Diagrams ({images.length}/{maxImages})
        </p>
        <label
          className={cn(
            "inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 dark:border-slate-600 dark:text-slate-200 dark:hover:bg-slate-800",
            (busy || uploading || images.length >= maxImages) &&
              "pointer-events-none opacity-50"
          )}
        >
          {uploading ? (
            <Loader2 className="size-3.5 animate-spin" />
          ) : (
            <Plus className="size-3.5" />
          )}
          Add image
          <input
            type="file"
            accept="image/jpeg,image/png,image/webp"
            multiple
            className="hidden"
            disabled={busy || uploading || images.length >= maxImages}
            onChange={(e) => {
              void addFiles(e.target.files);
              e.target.value = "";
            }}
          />
        </label>
      </div>
      {images.length === 0 ? (
        <p className="text-xs text-slate-500">No images yet.</p>
      ) : (
        <ul className="space-y-3">
          {images.map((img, index) => {
            const canPreview = committedKeys.has(img.asset_key);
            const selected = index === selectedIndex;
            return (
              <li
                key={img.id ?? img.storage_key}
                className={cn(
                  "rounded-md border p-2 dark:border-slate-700",
                  selected
                    ? "border-sky-400 bg-sky-50/60 dark:bg-sky-950/30"
                    : "border-slate-100 bg-slate-50 dark:bg-slate-900"
                )}
              >
                <div className="flex gap-3">
                  <button
                    type="button"
                    className="shrink-0"
                    onClick={() => onSelect(index)}
                  >
                    {canPreview ? (
                      <AuthImage
                        src={imageUrl(conceptId, img.asset_key)}
                        alt={img.title || img.asset_key}
                        className="size-20 rounded object-cover"
                      />
                    ) : (
                      <div className="flex size-20 items-center justify-center rounded bg-slate-200/80 text-center text-[10px] text-slate-500 dark:bg-slate-800">
                        Pending
                        <br />
                        save
                      </div>
                    )}
                  </button>
                  <div className="min-w-0 flex-1 space-y-1.5">
                    <input
                      value={img.asset_key}
                      onChange={(e) => {
                        const next = [...images];
                        next[index] = { ...img, asset_key: e.target.value };
                        onChange(next);
                      }}
                      disabled={busy}
                      placeholder="asset key"
                      className="w-full rounded border border-slate-200 px-2 py-1 font-mono text-xs dark:border-slate-600 dark:bg-slate-950"
                    />
                    <input
                      value={img.title ?? ""}
                      onChange={(e) => {
                        const next = [...images];
                        next[index] = { ...img, title: e.target.value };
                        onChange(next);
                      }}
                      disabled={busy}
                      placeholder="Title"
                      className="w-full rounded border border-slate-200 px-2 py-1 text-xs dark:border-slate-600 dark:bg-slate-950"
                    />
                    <input
                      value={img.teaching_purpose ?? ""}
                      onChange={(e) => {
                        const next = [...images];
                        next[index] = {
                          ...img,
                          teaching_purpose: e.target.value,
                        };
                        onChange(next);
                      }}
                      disabled={busy}
                      placeholder="Teaching purpose (required)"
                      className="w-full rounded border border-slate-200 px-2 py-1 text-xs dark:border-slate-600 dark:bg-slate-950"
                    />
                    <div className="flex flex-wrap items-center gap-2">
                      {img.annotations_status === "stale" ? (
                        <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-medium text-amber-900 dark:bg-amber-950 dark:text-amber-200">
                          Stale annotations
                        </span>
                      ) : (
                        <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-medium text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200">
                          Confirmed
                        </span>
                      )}
                      {img.annotations_status === "stale" ? (
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          disabled={busy}
                          onClick={() => {
                            const next = [...images];
                            next[index] = {
                              ...img,
                              annotations_status: "confirmed",
                            };
                            onChange(next);
                          }}
                        >
                          <Check className="mr-1 size-3.5" />
                          Reconfirm
                        </Button>
                      ) : null}
                      <label className="cursor-pointer text-xs text-slate-600 underline dark:text-slate-300">
                        Replace
                        <input
                          type="file"
                          accept="image/jpeg,image/png,image/webp"
                          className="hidden"
                          disabled={busy || uploading}
                          onChange={(e) => {
                            void replaceFile(index, e.target.files?.[0] ?? null);
                            e.target.value = "";
                          }}
                        />
                      </label>
                    </div>
                  </div>
                  <div className="flex flex-col gap-1">
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      disabled={busy || index === 0}
                      onClick={() => {
                        const next = [...images];
                        const tmp = next[index - 1]!;
                        next[index - 1] = next[index]!;
                        next[index] = tmp;
                        onChange(next);
                        onSelect(index - 1);
                      }}
                      aria-label="Move up"
                    >
                      <ArrowUp className="size-4" />
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      disabled={busy || index === images.length - 1}
                      onClick={() => {
                        const next = [...images];
                        const tmp = next[index + 1]!;
                        next[index + 1] = next[index]!;
                        next[index] = tmp;
                        onChange(next);
                        onSelect(index + 1);
                      }}
                      aria-label="Move down"
                    >
                      <ArrowDown className="size-4" />
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      disabled={busy}
                      onClick={() => onChange(images.filter((_, i) => i !== index))}
                      aria-label="Delete"
                    >
                      <Trash2 className="size-4" />
                    </Button>
                  </div>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

export function AnnotatePanel({
  conceptId,
  image,
  canPreview,
  drawTool,
  draftPreviewRegions,
  draftPreviewArrow,
  selectedRegionId,
  selectedConnectionId,
  authoringCursor,
  onDrawToolChange,
  onSelectRegion,
  onSelectConnection,
  onPointerDown,
  onPointerMove,
  onPointerUp,
  onPointerCancel,
  onPatchRegion,
  onDeleteRegion,
  onPatchConnection,
  onDeleteConnection,
  imageUrl = visualTeachingImageUrl,
  regionExtra,
}: {
  conceptId: string;
  image: VisualTeachingImageInput;
  canPreview: boolean;
  drawTool: DrawTool;
  draftPreviewRegions: Array<{
    region_id: string;
    label: string;
    teaching_purpose: string;
    sort_order: number;
    shape: RegionShape;
    geometry: Record<string, unknown>;
    focus_point: null;
    label_box: null;
  }>;
  draftPreviewArrow: { from: NormPt; to: NormPt } | null;
  selectedRegionId: string | null;
  selectedConnectionId: string | null;
  authoringCursor: string;
  onDrawToolChange: (t: DrawTool) => void;
  onSelectRegion: (id: string | null) => void;
  onSelectConnection: (id: string | null) => void;
  onPointerDown: (pt: NormPt, e: { pointerId: number }) => void;
  onPointerMove: (pt: NormPt) => void;
  onPointerUp: (pt: NormPt) => void;
  onPointerCancel: () => void;
  onPatchRegion: (
    regionId: string,
    patch: Partial<VisualTeachingRegionInput>
  ) => void;
  onDeleteRegion: (regionId: string) => void;
  onPatchConnection: (
    connectionId: string,
    patch: Partial<VisualTeachingConnectionInput>
  ) => void;
  onDeleteConnection: (connectionId: string) => void;
  imageUrl?: (conceptId: string, assetKey: string) => string;
  regionExtra?: (region: VisualTeachingRegionInput) => ReactNode;
}) {
  const selected = (image.regions ?? []).find(
    (r) => r.region_id === selectedRegionId
  );
  const selectedArrow = (image.connections ?? []).find(
    (c) => c.connection_id === selectedConnectionId
  );
  const toolHints: Record<DrawTool, string> = {
    rectangle: "Click and drag to draw a rectangle. Release to place.",
    square: "Click and drag to draw a square. Release to place.",
    circle: "Click and drag a square bounds; release to place the circle.",
    arrow: "Click and drag to draw an arrow (flow/direction). Release to place.",
  };
  const stageRegions = [
    ...(image.regions ?? []).map((r) => ({
      region_id: r.region_id,
      label: r.label ?? "",
      teaching_purpose: r.teaching_purpose ?? "",
      sort_order: 0,
      shape: r.shape,
      geometry: r.geometry as never,
      focus_point: r.focus_point,
      label_box: r.label_box ?? null,
      highlight_color: r.highlight_color ?? null,
      label_bg_color: r.label_bg_color ?? null,
      label_text_color: r.label_text_color ?? null,
    })),
    ...draftPreviewRegions,
  ];

  const draftAnchors = draftPreviewArrow
    ? [
        {
          anchor_id: "__draft_arrow_from",
          label: "",
          point: draftPreviewArrow.from,
        },
        {
          anchor_id: "__draft_arrow_to",
          label: "",
          point: draftPreviewArrow.to,
        },
      ]
    : [];
  const draftConnections = draftPreviewArrow
    ? [
        {
          connection_id: "__draft_arrow__",
          from_anchor: "__draft_arrow_from",
          to_anchor: "__draft_arrow_to",
          label: "",
          kind: "flow" as const,
          color: DEFAULT_ARROW_COLOR,
          label_bg_color: DEFAULT_LABEL_BG_COLOR,
          label_text_color: DEFAULT_LABEL_TEXT_COLOR,
          label_box: defaultLabelBoxNear(
            {
              x: (draftPreviewArrow.from.x + draftPreviewArrow.to.x) / 2,
              y: (draftPreviewArrow.from.y + draftPreviewArrow.to.y) / 2,
            },
            8
          ),
        },
      ]
    : [];

  const stageAnchors = [
    ...(image.anchors ?? []).map((a) => ({
      anchor_id: a.anchor_id,
      label: a.label ?? "",
      point: a.point,
    })),
    ...draftAnchors,
  ];
  const stageConnections = [
    ...(image.connections ?? []).map((c) => ({
      connection_id: c.connection_id,
      from_anchor: c.from_anchor,
      to_anchor: c.to_anchor,
      label: c.label ?? "",
      teaching_purpose: c.teaching_purpose ?? "",
      kind: c.kind ?? "flow",
      color: c.color ?? null,
      label_bg_color: c.label_bg_color ?? null,
      label_text_color: c.label_text_color ?? null,
      label_box: c.label_box ?? null,
    })),
    ...draftConnections,
  ];
  const allArrowIds = stageConnections.map((c) => c.connection_id);

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <div className="space-y-2">
        <div className="flex flex-wrap gap-2">
          {(
            [
              ["rectangle", "Rectangle"],
              ["square", "Square"],
              ["circle", "Circle"],
              ["arrow", "Arrow"],
            ] as const
          ).map(([id, label]) => (
            <Button
              key={id}
              type="button"
              size="sm"
              variant={drawTool === id ? "default" : "outline"}
              onClick={() => onDrawToolChange(id)}
            >
              {label}
            </Button>
          ))}
        </div>
        <p className="text-xs text-slate-500">
          {toolHints[drawTool]} Drag labels to reposition; use corner handles to
          resize (regions and arrows). Select an arrow to drag its body or
          endpoints. Esc cancels an in-progress draw.
        </p>
        {canPreview ? (
          <VisualTeachingStage
            imageUrl={imageUrl(conceptId, image.asset_key)}
            alt={image.title || image.asset_key}
            naturalWidth={image.natural_width}
            naturalHeight={image.natural_height}
            regions={stageRegions as never}
            anchors={stageAnchors}
            connections={stageConnections}
            visualState={{
              ...emptyVisualState(),
              highlights: selectedRegionId ? [selectedRegionId] : ["__draft__"],
              labels_visible: (image.regions ?? []).map((r) => r.region_id),
              arrows: allArrowIds,
            }}
            showAllOutlines
            selectedRegionId={selectedRegionId}
            selectedConnectionId={
              selectedConnectionId ??
              (draftPreviewArrow ? "__draft_arrow__" : null)
            }
            svgIdScope={`annotate-${image.asset_key || "image"}`}
            authoringCursor={authoringCursor}
            className="aspect-[4/3] w-full rounded-xl"
            onImagePointer={(pt, e) => onPointerDown(pt, e)}
            onImagePointerMove={(pt) => onPointerMove(pt)}
            onImagePointerUp={(pt) => onPointerUp(pt)}
            onImagePointerCancel={() => onPointerCancel()}
          />
        ) : (
          <p className="text-sm text-amber-700">Save to annotate new uploads.</p>
        )}
      </div>
      <div className="space-y-4">
        <div className="space-y-2">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            Regions
          </p>
          <ul className="space-y-2">
            {(image.regions ?? []).map((r, idx) => (
              <li
                key={`${r.region_id}#${idx}`}
                className={`rounded border p-2 text-xs dark:border-slate-700 ${
                  selectedRegionId === r.region_id ? "border-sky-400" : ""
                }`}
              >
                <button
                  type="button"
                  className="mb-1 font-mono text-slate-700 dark:text-slate-200"
                  onClick={() => onSelectRegion(r.region_id)}
                >
                  {r.region_id} ·{" "}
                  {r.shape === "ellipse" ? "circle" : r.shape}
                </button>
                {selected?.region_id === r.region_id ? (
                  <div className="space-y-1.5">
                    <input
                      value={r.region_id}
                      onChange={(e) =>
                        onPatchRegion(r.region_id, { region_id: e.target.value })
                      }
                      className="w-full rounded border px-2 py-1 font-mono dark:border-slate-600 dark:bg-slate-950"
                      placeholder="region_id"
                    />
                    <input
                      value={r.label ?? ""}
                      onChange={(e) =>
                        onPatchRegion(r.region_id, { label: e.target.value })
                      }
                      className="w-full rounded border px-2 py-1 text-sm dark:border-slate-600 dark:bg-slate-950"
                      placeholder="Label"
                    />
                    <input
                      value={r.teaching_purpose ?? ""}
                      onChange={(e) =>
                        onPatchRegion(r.region_id, {
                          teaching_purpose: e.target.value,
                        })
                      }
                      className="w-full rounded border px-2 py-1 dark:border-slate-600 dark:bg-slate-950"
                      placeholder="Teaching purpose"
                    />
                    {regionExtra?.(r)}
                    <div className="grid grid-cols-3 gap-2 pt-1">
                      <label className="space-y-0.5 text-[10px] text-slate-500">
                        Highlight
                        <input
                          type="color"
                          value={r.highlight_color || DEFAULT_HIGHLIGHT_COLOR}
                          onChange={(e) =>
                            onPatchRegion(r.region_id, {
                              highlight_color: e.target.value,
                            })
                          }
                          className="h-8 w-full cursor-pointer rounded border border-slate-200 bg-transparent dark:border-slate-600"
                        />
                      </label>
                      <label className="space-y-0.5 text-[10px] text-slate-500">
                        Label bg
                        <input
                          type="color"
                          value={r.label_bg_color || DEFAULT_LABEL_BG_COLOR}
                          onChange={(e) =>
                            onPatchRegion(r.region_id, {
                              label_bg_color: e.target.value,
                            })
                          }
                          className="h-8 w-full cursor-pointer rounded border border-slate-200 bg-transparent dark:border-slate-600"
                        />
                      </label>
                      <label className="space-y-0.5 text-[10px] text-slate-500">
                        Label text
                        <input
                          type="color"
                          value={r.label_text_color || DEFAULT_LABEL_TEXT_COLOR}
                          onChange={(e) =>
                            onPatchRegion(r.region_id, {
                              label_text_color: e.target.value,
                            })
                          }
                          className="h-8 w-full cursor-pointer rounded border border-slate-200 bg-transparent dark:border-slate-600"
                        />
                      </label>
                    </div>
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      onClick={() => onDeleteRegion(r.region_id)}
                    >
                      <Trash2 className="mr-1 size-3.5" />
                      Delete
                    </Button>
                  </div>
                ) : null}
              </li>
            ))}
            {(image.regions ?? []).length === 0 ? (
              <li className="text-xs text-slate-400">No regions yet.</li>
            ) : null}
          </ul>
        </div>

        <div className="space-y-2">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            Arrows
          </p>
          <ul className="space-y-2">
            {(image.connections ?? []).map((c, idx) => (
              <li
                key={`${c.connection_id}#${idx}`}
                className={`rounded border p-2 text-xs dark:border-slate-700 ${
                  selectedConnectionId === c.connection_id
                    ? "border-sky-400"
                    : ""
                }`}
              >
                <button
                  type="button"
                  className="mb-1 font-mono text-slate-700 dark:text-slate-200"
                  onClick={() => onSelectConnection(c.connection_id)}
                >
                  {c.connection_id} · arrow
                </button>
                {selectedArrow?.connection_id === c.connection_id ? (
                  <div className="space-y-1.5">
                    <input
                      value={c.connection_id}
                      onChange={(e) =>
                        onPatchConnection(c.connection_id, {
                          connection_id: e.target.value,
                        })
                      }
                      className="w-full rounded border px-2 py-1 font-mono dark:border-slate-600 dark:bg-slate-950"
                      placeholder="arrow_id"
                    />
                    <input
                      value={c.label ?? ""}
                      onChange={(e) =>
                        onPatchConnection(c.connection_id, {
                          label: e.target.value,
                        })
                      }
                      className="w-full rounded border px-2 py-1 text-sm dark:border-slate-600 dark:bg-slate-950"
                      placeholder="Label"
                    />
                    <input
                      value={c.teaching_purpose ?? ""}
                      onChange={(e) =>
                        onPatchConnection(c.connection_id, {
                          teaching_purpose: e.target.value,
                        })
                      }
                      className="w-full rounded border px-2 py-1 dark:border-slate-600 dark:bg-slate-950"
                      placeholder="Teaching purpose"
                    />
                    <div className="grid grid-cols-3 gap-2 pt-1">
                      <label className="space-y-0.5 text-[10px] text-slate-500">
                        Arrow
                        <input
                          type="color"
                          value={c.color || DEFAULT_ARROW_COLOR}
                          onChange={(e) =>
                            onPatchConnection(c.connection_id, {
                              color: e.target.value,
                            })
                          }
                          className="h-8 w-full cursor-pointer rounded border border-slate-200 bg-transparent dark:border-slate-600"
                        />
                      </label>
                      <label className="space-y-0.5 text-[10px] text-slate-500">
                        Label bg
                        <input
                          type="color"
                          value={c.label_bg_color || DEFAULT_LABEL_BG_COLOR}
                          onChange={(e) =>
                            onPatchConnection(c.connection_id, {
                              label_bg_color: e.target.value,
                            })
                          }
                          className="h-8 w-full cursor-pointer rounded border border-slate-200 bg-transparent dark:border-slate-600"
                        />
                      </label>
                      <label className="space-y-0.5 text-[10px] text-slate-500">
                        Label text
                        <input
                          type="color"
                          value={c.label_text_color || DEFAULT_LABEL_TEXT_COLOR}
                          onChange={(e) =>
                            onPatchConnection(c.connection_id, {
                              label_text_color: e.target.value,
                            })
                          }
                          className="h-8 w-full cursor-pointer rounded border border-slate-200 bg-transparent dark:border-slate-600"
                        />
                      </label>
                    </div>
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      onClick={() => onDeleteConnection(c.connection_id)}
                    >
                      <Trash2 className="mr-1 size-3.5" />
                      Delete
                    </Button>
                  </div>
                ) : null}
              </li>
            ))}
            {(image.connections ?? []).length === 0 ? (
              <li className="text-xs text-slate-400">
                No arrows yet — choose Arrow and click-drag on the image.
              </li>
            ) : null}
          </ul>
        </div>
      </div>
    </div>
  );
}
