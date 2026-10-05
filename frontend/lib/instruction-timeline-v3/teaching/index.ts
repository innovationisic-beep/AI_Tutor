export { deriveInstructionalLayoutKind, type InstructionalLayoutKind } from "./deriveLayoutProfile";
export {
  processAnnotationVisible,
  processEdgeOpacity,
  processNodeIdsFromProjections,
  processNodeOpacity,
  resolveProcessStepPhase,
  type ProcessStepPhase,
} from "./flowProcessPresentation";
export {
  applyInstructionalLayout,
  applyLayoutToLayers,
  cycleRingRadius,
  CYCLE_RING_CY_RATIO,
  COMPARISON_CENTER_X_RATIO,
  COMPARISON_DIVIDER_GAP,
  comparisonDividerGeometry,
  comparisonDividerCenterX,
  comparisonDividerForNodes,
  comparisonSplitStageBounds,
  resolveComparisonDividerCenterX,
} from "./instructionalLayout";
export {
  extractComparisonHints,
  partitionComparisonNodes,
  type ComparisonNodeHints,
  type ComparisonPartition,
} from "./comparisonSplit";
export {
  BOARD_DISPLAY_PAD,
  BOARD_FIT_PADDING,
  HIERARCHY_BOARD_FIT_PADDING,
  PROCESS_BOARD_FIT_PADDING,
  boardDisplayFrame,
  computeBoardFitTransform,
  computeBoardFitTransformFromBounds,
  contentBoundsFromProjections,
  logBoardFit,
  mergeContentBounds,
  parseBoardFitTransform,
  type BoardDisplayFrame,
  type BoardFitLogPayload,
  type BoardFitPadding,
  type ContentBounds,
} from "./boardViewportFit";
export {
  findNarrationBinding,
  pauseAfterSegment,
  primaryEntityIdForOperation,
  revealOffsetMs,
  timelineHasNarrationSync,
  type NarrationSegmentPresentationMeta,
} from "./narrationSync";
export {
  annotationObstaclesFromProjections,
  balanceSceneInViewport,
  buildCompositionContext,
  clusterObstaclesFromProjections,
  composeAnnotations,
  edgeCorridorPenalty,
  edgeObstacleBulge,
  estimateAnnotationStackHeight,
  type AnnotationLane,
  type CompositionContext,
  type ViewportBox,
} from "./sceneComposition";
export {
  buildTeachingClusters,
  clusterBounds,
  type TeachingCluster,
} from "./teachingClusters";
export {
  beatUsesOrchestration,
  buildBeatOrchestrationPlan,
  primaryBeatSegment,
  type BeatOrchestrationPlan,
} from "./beatOrchestration";
