export type {
  AnnotationsStatus,
  RegionShape,
  ConnectionKind,
  NormPoint,
  PointGeometry,
  RectGeometry,
  EllipseGeometry,
  PolygonGeometry,
  RegionGeometry,
  VisualState,
  VisualStatePatch,
  VisualTeachingRegion,
  VisualTeachingAnchor,
  VisualTeachingConnection,
  VisualTeachingImage,
  ConceptVisualTeaching,
  SentenceVisualEvent,
  BoardWriteRuntime,
  ConceptVisualTeachingRuntime,
} from "./types";
export { SVG_VIEWBOX, emptyVisualState } from "./types";

export {
  SUPPORTED_VISUAL_CAPABILITIES,
  ALL_VISUAL_CAPABILITY_KEYS,
  isCapabilitySupported,
  unsupportedIn,
} from "./capabilities";
export type { VisualCapability } from "./capabilities";

export {
  clamp01,
  validateRegionGeometry,
  normalizeRegionGeometry,
  poleOfInaccessibility,
  resolveFocusPoint,
  resolveLabelBox,
  resolveConnectionLabelBox,
  geometryToSvgPaths,
  regionById,
} from "./geometry";
export type { SvgRegionPath } from "./geometry";

export { fitImageBox } from "./fitImageBox";
export type { FitBox } from "./fitImageBox";

export { applyVisualStatePatch } from "./applyVisualState";

export {
  MIN_NORM_SIZE,
  MIN_DRAG_COMMIT,
  MIN_LABEL_W,
  MIN_LABEL_H,
  clientToNorm,
  clampLabelBox,
  cursorForHandle,
  defaultLabelBoxNear,
  dragDistance,
  dragToCircle,
  dragToRect,
  ellipseHandles,
  ellipseToRect,
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
  rectToCircle,
  resizeCircle,
  resizeLabelBox,
  resizeRect,
  toolToRegionShape,
} from "./drawGeometry";
export type {
  DrawTool,
  NormEllipse,
  NormPt,
  NormRect,
  ResizeHandle,
} from "./drawGeometry";

export {
  DEFAULT_HIGHLIGHT_COLOR,
  DEFAULT_LABEL_BG_COLOR,
  DEFAULT_LABEL_TEXT_COLOR,
  DEFAULT_ARROW_COLOR,
  fitLabelFontSize,
  hexToRgba,
  normalizeHexColor,
} from "./regionColors";

export { VisualTeachingOverlay } from "./VisualTeachingOverlay";
export type { VisualTeachingOverlayProps } from "./VisualTeachingOverlay";
export {
  sanitizeSvgIdPart,
  scopedMarkerId,
  scopedLabelClipId,
  scopedArrowLabelClipId,
} from "./VisualTeachingOverlay";

export { VisualTeachingStage } from "./VisualTeachingStage";
export type { VisualTeachingStageProps } from "./VisualTeachingStage";

export {
  arrowEndpointIds,
  arrowLabelPoint,
  clamp01Pt,
  distToSegment,
  hitArrow,
  isArrowEndpointAnchor,
  nextArrowConnectionId,
  shortenArrowLine,
} from "./arrowGeometry";
export type { ArrowHit, Pt as ArrowPt } from "./arrowGeometry";
