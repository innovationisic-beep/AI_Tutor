"use client";

import { Component, type ErrorInfo, type ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { sleep, speakUtteranceWithHooks, cancelSpeech, isTtsClientAvailable } from "@/lib/voice";
import { VtseVisualCompanion } from "@/components/ai/timeline-v3/VtseVisualCompanion";
import {
  VTSE_VISUAL_SPLIT_MIN_PX,
  timelineHasVtseVisualPackage,
  vtseVisualFlowMode,
} from "@/lib/vtse-visuals/boardLayout";
import {
  isCollapsedWordBurst,
  narrationWordIndexForBoardWord,
  visualClockEvents,
} from "@/lib/vtse-visuals/playback";
import { wordChunks } from "@/lib/instruction-timeline-v3/teaching/pedagogicalWordChunks";
import {
  extractSpeechRevealTargets,
  stabilizeSpeechReveal,
  type SpeechRevealDebugMeta,
  type SpeechRevealState,
} from "@/lib/instruction-timeline-v3/teaching/speechSyncedReveal";
import {
  boardTextForSpeechReveal,
  normalizeColumnIntroNarration,
  registerSpeechRevealTargets,
  speakSegmentWithSpeechReveal,
} from "@/lib/instruction-timeline-v3/teaching/speechRevealOrchestration";
import {
  findAnnotateOpForOperationId,
  summarizeAnnotationProjections,
} from "@/lib/instruction-timeline-v3/annotationLifecycle";
import {
  findHighlightOpForOperationId,
  summarizeHighlightProjections,
} from "@/lib/instruction-timeline-v3/highlightLifecycle";
import { buildBeatOrchestrationPlan } from "@/lib/instruction-timeline-v3/teaching/beatOrchestration";
import {
  findNarrationBinding,
  pauseAfterSegment,
  primaryEntityIdForOperation,
  revealOffsetMs,
  timelineHasNarrationSync,
} from "@/lib/instruction-timeline-v3/teaching/narrationSync";
import type { InstructionTimelineV3 } from "@/lib/instruction-timeline-v3/types";
import type { RenderProjection } from "@/lib/instruction-timeline-v3/renderer/projectionTypes";
import { MinimalTimelineRuntime } from "@/lib/instruction-timeline-v3/runtime";
import { RuntimeEventBus } from "@/lib/instruction-timeline-v3/eventBus";
import { RuntimeRendererBridge } from "@/lib/instruction-timeline-v3/renderer/runtimeRendererBridge";
import { RealRuntimeClock } from "@/lib/instruction-timeline-v3/clock";
import { defaultViewport } from "@/lib/instruction-timeline-v3/renderer/viewport";
import { MinimalDeterministicRenderer } from "@/components/ai/timeline-v3/MinimalDeterministicRenderer";
import type { RuntimeValidationError } from "@/lib/instruction-timeline-v3/types";
import {
  collectFailingOperationSnapshots,
  compactTimelineSummaryForLog,
  stringifyValidationErrorsDeep,
  validateTimeline,
  type FailingOperationSnapshot,
} from "@/lib/instruction-timeline-v3/validation";
import { deriveInstructionalLayoutKind } from "@/lib/instruction-timeline-v3/teaching";
import {
  buildFlowCheckpointEventForBeat,
  type FlowCheckpointGate,
} from "@/lib/learning/flowCheckpointOrchestrator";
import type { Beat } from "@/lib/instruction-timeline-v3/types";
import {
  logInstructionFinalize,
  logInstructionLifecycle,
  logAnnotationLifecycle,
  logHighlightLifecycle,
  logNarrationSync,
  logTimelineRender,
  type InstructionLifecycleOutcome,
} from "@/lib/learning/instructionLifecycle";

type CommitPresentationFrame = {
  byLayer: Record<string, RenderProjection[]>;
  operation_id: string;
  beat_id: string;
  entityCount: number;
  projectionCount: number;
  sceneEntityIds: string[];
  sceneByType: Record<string, number>;
  projectionPreview: Array<{
    id: string;
    kind: string;
    layer: string;
    source: string;
    box: { x: number; y: number; w: number; h: number };
    visible: boolean;
  }>;
  sceneHash: string | null;
};

/** Logical canvas shared by runtime bridge + SVG layout (extra height for hierarchy + captions). */
const BOARD_VIEWBOX_W = 960;
/** Taller than legacy 720 so root + child row + per-child annotations fit without aggressive scaling. */
const BOARD_VIEWBOX_H = 1040;

function compactFirstValidationErrorForLog(err: RuntimeValidationError): Record<string, unknown> {
  const out: Record<string, unknown> = {
    code: err.code,
    message: err.message,
    path: err.path ?? null,
  };
  if (err.details && typeof err.details === "object") {
    const d = { ...(err.details as Record<string, unknown>) };
    const iv = d.invalid_value;
    if (typeof iv === "string" && iv.length > 160) {
      d.invalid_value = `${iv.slice(0, 160)}…`;
    } else if (iv != null && typeof iv === "object") {
      try {
        const s = JSON.stringify(iv);
        d.invalid_value = s.length > 220 ? `${s.slice(0, 220)}…` : s;
      } catch {
        d.invalid_value = "[unserializable]";
      }
    }
    out.details = d;
  }
  return out;
}

function logInstructionBoardValidation(payload: Record<string, unknown>): void {
  // eslint-disable-next-line no-console -- structured diagnostic (warn: avoids Next devtools "Error" overlay for expected diagnostics)
  console.warn(`[INSTRUCTION_BOARD_VALIDATION] ${JSON.stringify(payload)}`);
}

type Props = {
  timeline: InstructionTimelineV3;
  enabled: boolean;
  plannerSource?: string | null;
  /** Zone 1 compact CIR provenance from finalize (optional). */
  cirInstructionDebug?: Record<string, unknown> | null;
  onRuntimeFailure?: () => void;
  /** Fires once when the instructional cadence for this timeline has finished (quiz / flow gates). */
  onInstructionComplete?: () => void;
  /** Fires when a teaching beat finishes displaying (for resume checkpoint). */
  onPlaybackBeatCommitted?: (beatIndex: number) => void;
  /**
   * When true: board advances on timer only (no narration TTS) and never emits
   * `onInstructionComplete` — parent owns pacing (e.g. AIWhiteboard WordSyncedStreaming).
   */
  visualizationOnly?: boolean;
  /** Resume mode: render final board instantly, no TTS or lifecycle callbacks. */
  restoreMode?: boolean;
  /** When restoreMode: show board state through this beat index (partial VTSE). */
  restoreStaticThroughBeatIndex?: number | null;
  /**
   * `standalone` — lab/demo chrome (header, cadence badges).
   * `whiteboard` — embedded in AI Whiteboard: neutral frame, no “Timeline V3” marketing.
   */
  surface?: "standalone" | "whiteboard";
  /** Play only beats at/after this index (incremental Zone 1 continuations). */
  playbackStartBeatIndex?: number;
  /** Runtime gate — pauses after every 2 completed flow process nodes (flow topics only). */
  flowCheckpointGate?: FlowCheckpointGate | null;
  /** Companion diagram. Off during reteach so a paraphrase cannot drive cue offsets. */
  showVtseVisuals?: boolean;
};

type DebugError = {
  kind: "validation" | "runtime";
  message: string;
};

type RuntimeDebugStats = {
  committedOps: number;
  entityCount: number;
  projectionCount: number;
  layerCounts: Record<string, number>;
  currentBeatId: string | null;
  currentOpId: string | null;
  sceneHash: string | null;
};

type RuntimeDebugSnapshot = {
  sceneEntityIds: string[];
  sceneByType: Record<string, number>;
  projectionPreview: Array<{
    id: string;
    kind: string;
    layer: string;
    source: string;
    box: { x: number; y: number; w: number; h: number };
    visible: boolean;
  }>;
};

type ValidationReportState = {
  status: "passed" | "failed" | "skipped";
  errors: RuntimeValidationError[];
  failingOps: FailingOperationSnapshot[];
};

type RendererErrorBoundaryProps = { children: ReactNode };

type RendererErrorBoundaryState = { error: Error | null };

/**
 * Isolates renderer subtree failures so a throw does not blank the whole lesson shell.
 */
class V3MinimalRendererErrorBoundary extends Component<
  RendererErrorBoundaryProps,
  RendererErrorBoundaryState
> {
  constructor(props: RendererErrorBoundaryProps) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error: Error): RendererErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // eslint-disable-next-line no-console
    console.error("[V3_DEBUG] MinimalDeterministicRenderer error boundary", error, info.componentStack);
  }

  render(): ReactNode {
    if (this.state.error) {
      return (
        <div
          className="rounded border-2 border-rose-600 bg-rose-100 p-3 text-sm text-rose-900 dark:bg-rose-950/50 dark:text-rose-100"
          role="alert"
        >
          <div className="font-semibold">V3 renderer crashed</div>
          <pre className="mt-2 whitespace-pre-wrap break-all text-xs">{this.state.error.message}</pre>
        </div>
      );
    }
    return this.props.children;
  }
}

export function ProductionTimelineRuntimeView({
  timeline,
  enabled,
  plannerSource,
  cirInstructionDebug,
  onRuntimeFailure,
  onInstructionComplete,
  onPlaybackBeatCommitted,
  visualizationOnly = false,
  restoreMode = false,
  restoreStaticThroughBeatIndex = null,
  surface = "standalone",
  playbackStartBeatIndex = 0,
  flowCheckpointGate = null,
  showVtseVisuals = false,
}: Props) {
  const isWhiteboardSurface = surface === "whiteboard";
  const debugEnabled = process.env.NEXT_PUBLIC_V3_DEBUG === "1";
  const forceRenderProbe =
    debugEnabled && process.env.NEXT_PUBLIC_V3_FORCE_RENDER_PROBE === "1";
  const prodBaselineStrip = debugEnabled && process.env.NEXT_PUBLIC_V3_PROD_BASELINE === "1";
  const skipValidation = process.env.NEXT_PUBLIC_V3_SKIP_VALIDATION === "1";
  const instantBoard =
    restoreMode || process.env.NEXT_PUBLIC_V3_INSTANT_BOARD === "1";
  const teachingStepMs = Number(process.env.NEXT_PUBLIC_V3_TEACHING_STEP_MS ?? "480") || 480;
  const timerTeachingOnly = process.env.NEXT_PUBLIC_V3_TIMER_TEACHING === "1";
  const layoutKind = useMemo(() => deriveInstructionalLayoutKind(timeline), [timeline]);
  useEffect(() => {
    if (!restoreMode) return;
    const idx = restoreStaticThroughBeatIndex;
    if (idx == null || idx < 0) return;
    const beat = timeline.beats?.[idx];
    if (!beat?.beat_id) return;
    setVtseBeatId(beat.beat_id);
    setVtseWordIndex(Number.MAX_SAFE_INTEGER);
  }, [restoreMode, restoreStaticThroughBeatIndex, timeline]);
  const flowCheckpointGateRef = useRef(flowCheckpointGate);
  flowCheckpointGateRef.current = flowCheckpointGate;

  const narrationEligible = useMemo(
    () =>
      !visualizationOnly &&
      !instantBoard &&
      !timerTeachingOnly &&
      timelineHasNarrationSync(timeline),
    [visualizationOnly, instantBoard, timerTeachingOnly, timeline],
  );

  const [boardByLayer, setBoardByLayer] = useState<Record<string, RenderProjection[]>>({});
  const [vtseBeatId, setVtseBeatId] = useState<string | null>(null);
  const [vtseWordIndex, setVtseWordIndex] = useState(0);
  const [vtseVisualUnavailable, setVtseVisualUnavailable] = useState(false);
  const [vtseRowWidth, setVtseRowWidth] = useState(0);
  const vtseRowRef = useRef<HTMLDivElement>(null);
  const vtseHasVisualPackage = timelineHasVtseVisualPackage(timeline);
  useEffect(() => {
    const el = vtseRowRef.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const measure = () => setVtseRowWidth(el.clientWidth);
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [showVtseVisuals, vtseHasVisualPackage, vtseVisualUnavailable]);
  /** Entity receiving teaching emphasis (from current operation). */
  const [focusEntityId, setFocusEntityId] = useState<string | null>(null);
  /** Presentation-only TTL expiry — overlay hidden while highlight entity remains in scene history. */
  const [ttlExpiredHighlightIds, setTtlExpiredHighlightIds] = useState<ReadonlySet<string>>(
    () => new Set(),
  );
  const highlightTtlTimerIdsRef = useRef<number[]>([]);
  const ttlExpiredHighlightIdsRef = useRef<ReadonlySet<string>>(ttlExpiredHighlightIds);
  ttlExpiredHighlightIdsRef.current = ttlExpiredHighlightIds;
  /** When set, progressively advances board state for teaching rhythm (does not re-run runtime). */
  const [teachingQueue, setTeachingQueue] = useState<CommitPresentationFrame[] | null>(null);
  /** Progressive phrase reveal per entity during narration-synced playback. */
  const [speechRevealByEntityId, setSpeechRevealByEntityId] = useState<
    Record<string, SpeechRevealState>
  >({});
  const [speechRevealDebug, setSpeechRevealDebug] = useState<SpeechRevealDebugMeta | null>(null);
  const speechRevealByEntityIdRef = useRef(speechRevealByEntityId);
  speechRevealByEntityIdRef.current = speechRevealByEntityId;
  /** Synchronous map so TTS can read targets before React commits setState. */
  const speechRevealMapRef = useRef<Record<string, SpeechRevealState>>({});
  const boardByLayerRef = useRef(boardByLayer);
  boardByLayerRef.current = boardByLayer;
  const teachingQueueRef = useRef(teachingQueue);
  teachingQueueRef.current = teachingQueue;
  const [debugError, setDebugError] = useState<DebugError | null>(null);
  const [validationReport, setValidationReport] = useState<ValidationReportState | null>(null);
  const [runtimeStats, setRuntimeStats] = useState<RuntimeDebugStats>({
    committedOps: 0,
    entityCount: 0,
    projectionCount: 0,
    layerCounts: {},
    currentBeatId: null,
    currentOpId: null,
    sceneHash: null,
  });
  const [runtimeSnapshot, setRuntimeSnapshot] = useState<RuntimeDebugSnapshot>({
    sceneEntityIds: [],
    sceneByType: {},
    projectionPreview: [],
  });
  const runtime = useMemo(() => new MinimalTimelineRuntime(), []);
  const timelineRef = useRef(timeline);
  timelineRef.current = timeline;
  const cirInstructionDebugRef = useRef(cirInstructionDebug);
  cirInstructionDebugRef.current = cirInstructionDebug;
  const plannerSourceRef = useRef(plannerSource);
  plannerSourceRef.current = plannerSource;
  const onInstructionCompleteRef = useRef(onInstructionComplete);
  onInstructionCompleteRef.current = onInstructionComplete;
  const onPlaybackBeatCommittedRef = useRef(onPlaybackBeatCommitted);
  onPlaybackBeatCommittedRef.current = onPlaybackBeatCommitted;
  const onRuntimeFailureRef = useRef(onRuntimeFailure);
  onRuntimeFailureRef.current = onRuntimeFailure;
  const visualizationOnlyRef = useRef(visualizationOnly || restoreMode);
  visualizationOnlyRef.current = visualizationOnly || restoreMode;
  const lifecycleFinalizedRef = useRef(false);
  const lifecycleRunKeyRef = useRef<string | null>(null);
  const narrationPlaybackDoneRef = useRef<string | null>(null);
  const surfaceAliveRef = useRef(false);
  const renderPassRef = useRef(0);
  renderPassRef.current += 1;

  const timelineRunId = timeline.timeline_id;
  const startBeatIndex = Math.max(
    0,
    Math.min(
      playbackStartBeatIndex,
      Math.max(0, timeline.beats.length - 1),
    ),
  );
  const playbackRunKey = `${timelineRunId}:from${startBeatIndex}`;

  const finalizeInstructionLifecycle = useCallback(
    (outcome: Exclude<InstructionLifecycleOutcome, "started" | "started_skip_already_finalized">, detail?: Record<string, unknown>) => {
      if (visualizationOnlyRef.current) return;
      const alreadyFinalized = lifecycleFinalizedRef.current;
      const reason = typeof detail?.reason === "string" ? detail.reason : outcome;
      logInstructionFinalize(reason, alreadyFinalized, timelineRef.current.timeline_id, detail);
      if (alreadyFinalized) return;
      lifecycleFinalizedRef.current = true;
      lifecycleRunKeyRef.current = timelineRef.current.timeline_id;
      logInstructionLifecycle(outcome, detail);

      if (outcome === "runtime_failed" || outcome === "validation_failed") {
        onRuntimeFailureRef.current?.();
      } else if (outcome === "released") {
        // Unmount mid-playback is not instructional completion. Calling
        // onInstructionComplete here armed Concept Check after FlowCheckpoint
        // remounts (linear_process) while more VTSE beats remained.
      } else {
        onInstructionCompleteRef.current?.();
      }
    },
    [],
  );

  useEffect(() => {
    logTimelineRender("mounted", playbackRunKey);
    return () => {
      logTimelineRender("unmounted", playbackRunKey);
    };
  }, [playbackRunKey]);

  useEffect(() => {
    logTimelineRender("rerendered", playbackRunKey, { pass: renderPassRef.current });
  });

  useEffect(() => {
    surfaceAliveRef.current = true;
    return () => {
      surfaceAliveRef.current = false;
      const runKey = playbackRunKey;
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          if (surfaceAliveRef.current) return;
          if (lifecycleRunKeyRef.current !== runKey) return;
          if (lifecycleFinalizedRef.current || visualizationOnlyRef.current) return;
          finalizeInstructionLifecycle("released", { reason: "component_unmount" });
        });
      });
    };
  }, [finalizeInstructionLifecycle, playbackRunKey]);

  useEffect(() => {
    const segmentCount = timeline.beats.reduce((n, b) => n + b.narration_segments.length, 0);
    const bindingCount = timeline.beats.reduce((n, b) => n + b.bindings.length, 0);
    logNarrationSync(narrationEligible ? "eligible" : "ineligible", {
      timeline_id: timelineRunId,
      visualization_only: visualizationOnly,
      instant_board: instantBoard,
      timer_teaching_only: timerTeachingOnly,
      segment_count: segmentCount,
      binding_count: bindingCount,
      has_sync: timelineHasNarrationSync(timeline),
    });
  }, [
    instantBoard,
    narrationEligible,
    timeline,
    timelineRunId,
    timerTeachingOnly,
    visualizationOnly,
  ]);
  const opTypes = useMemo(() => {
    const bag = new Set<string>();
    timeline.beats.forEach((beat) => beat.operations.forEach((op) => bag.add(op.op_type)));
    return Array.from(bag).sort();
  }, [timeline]);

  useEffect(() => {
    if (!debugEnabled) return;
    if (enabled) {
      // eslint-disable-next-line no-console
      console.info("[V3_DEBUG] ProductionTimelineRuntimeView enabled");
    } else {
      // eslint-disable-next-line no-console
      console.warn("[V3_DEBUG] ProductionTimelineRuntimeView disabled by feature flag");
    }
  }, [debugEnabled, enabled]);

  useEffect(() => {
    if (!enabled) return;

    if (lifecycleFinalizedRef.current && lifecycleRunKeyRef.current === playbackRunKey) {
      const hasBoardInk = Object.values(boardByLayerRef.current).some((layer) => layer.length > 0);
      const hasQueue = (teachingQueueRef.current?.length ?? 0) > 0;
      if (hasBoardInk || hasQueue) {
        logInstructionLifecycle("started_skip_already_finalized", {
          timeline_id: timelineRunId,
          planner_source: plannerSourceRef.current ?? null,
          has_board_ink: hasBoardInk,
          has_queue: hasQueue,
        });
        return;
      }
      lifecycleFinalizedRef.current = false;
      narrationPlaybackDoneRef.current = null;
      logInstructionLifecycle("started", {
        timeline_id: timelineRunId,
        planner_source: plannerSourceRef.current ?? null,
        reason: "reinit_empty_board_after_finalize",
      });
    }

    if (lifecycleRunKeyRef.current !== playbackRunKey) {
      lifecycleFinalizedRef.current = false;
      lifecycleRunKeyRef.current = playbackRunKey;
      narrationPlaybackDoneRef.current = null;
    }

    const activeTimeline = timelineRef.current;
    logInstructionLifecycle("started", {
      timeline_id: timelineRunId,
      playback_start_beat_index: startBeatIndex,
      planner_source: plannerSourceRef.current ?? null,
    });
    setDebugError(null);
    setRuntimeStats({
      committedOps: 0,
      entityCount: 0,
      projectionCount: 0,
      layerCounts: {},
      currentBeatId: null,
      currentOpId: null,
      sceneHash: null,
    });
    setRuntimeSnapshot({
      sceneEntityIds: [],
      sceneByType: {},
      projectionPreview: [],
    });
    setValidationReport(null);
    setTeachingQueue(null);
    setBoardByLayer({});
    setFocusEntityId(null);
    for (const timerId of highlightTtlTimerIdsRef.current) {
      window.clearTimeout(timerId);
    }
    highlightTtlTimerIdsRef.current = [];
    setTtlExpiredHighlightIds(new Set());

    try {
      if (debugEnabled) {
        // eslint-disable-next-line no-console
        console.info(
          "[V3_DEBUG] timeline_created_at_validator_input",
          JSON.stringify({
            created_at: activeTimeline.created_at,
            typeof_created_at: typeof activeTimeline.created_at,
            ends_with_Z:
              typeof activeTimeline.created_at === "string" && activeTimeline.created_at.endsWith("Z"),
            includes_plus_00:
              typeof activeTimeline.created_at === "string" &&
              activeTimeline.created_at.includes("+00:00"),
          }),
        );
      }
      if (debugEnabled) {
        // eslint-disable-next-line no-console
        console.info(
          "[V3_DEBUG] timeline_detected",
          JSON.stringify({
            timeline_id: activeTimeline.timeline_id,
            beats: activeTimeline.beats.length,
            ops: activeTimeline.beats.reduce((n, b) => n + b.operations.length, 0),
            op_types: opTypes,
            planner_source: plannerSourceRef.current ?? null,
            beat_ops: activeTimeline.beats.map((b) => ({
              beat_id: b.beat_id,
              index: b.index,
              operation_ids: b.operations.map((o) => o.operation_id),
              operation_types: b.operations.map((o) => o.op_type),
              depends_on: b.operations.map((o) => ({ operation_id: o.operation_id, depends_on: o.depends_on })),
            })),
          }),
        );
      }

      if (skipValidation) {
        if (debugEnabled) {
          // eslint-disable-next-line no-console
          console.warn(
            "[V3_DEBUG] NEXT_PUBLIC_V3_SKIP_VALIDATION=1 — validateTimeline skipped in ProductionTimelineRuntimeView (diagnostic only)",
          );
        }
        setValidationReport({ status: "skipped", errors: [], failingOps: [] });
      } else {
        const validation = validateTimeline(activeTimeline);
        if (!validation.ok) {
          let failingOps: FailingOperationSnapshot[] = [];
          try {
            failingOps = collectFailingOperationSnapshots(activeTimeline, validation.errors);
          } catch {
            failingOps = [];
          }
          const errorsJson = stringifyValidationErrorsDeep(validation.errors);
          const failingOpsJson = JSON.stringify(
            failingOps.map((f) => ({
              beat_id: f.beat_id,
              operation_id: f.operation_id,
              op_type: f.op_type,
              op: f.op,
            })),
            null,
            2,
          );
          const first = validation.errors[0];
          logInstructionBoardValidation({
            planner_source: plannerSourceRef.current ?? null,
            validation_code: first?.code ?? "UNKNOWN",
            validation_message: first?.message ?? "",
            validation_path: first?.path ?? null,
            first_error: first ? compactFirstValidationErrorForLog(first) : null,
            error_count: validation.errors.length,
            timeline_summary: compactTimelineSummaryForLog(activeTimeline),
            cir_source_snapshot: cirInstructionDebugRef.current ?? null,
          });
          if (debugEnabled) {
            // eslint-disable-next-line no-console
            console.error("[V3_DEBUG] timeline_validation_failed_errors_json\n", errorsJson);
            // eslint-disable-next-line no-console
            console.error("[V3_DEBUG] timeline_validation_failing_ops_json\n", failingOpsJson);
          }
          setValidationReport({
            status: "failed",
            errors: validation.errors,
            failingOps,
          });
          const msg = `${first?.code ?? "UNKNOWN"}: ${first?.message ?? "Validation failed"}`;
          const hideValidationChrome = isWhiteboardSurface && !debugEnabled;
          setDebugError(hideValidationChrome ? null : { kind: "validation", message: msg });
          if (debugEnabled) {
            // eslint-disable-next-line no-console
            console.error("[V3_DEBUG] timeline_validation_failed_object", validation.errors);
          }
          finalizeInstructionLifecycle("validation_failed", {
            reason: "schema_validation",
            path: first?.path ?? null,
          });
          return;
        }
        setValidationReport({ status: "passed", errors: [], failingOps: [] });
        if (debugEnabled) {
          // eslint-disable-next-line no-console
          console.info(
            "[V3_DEBUG] timeline_validation_passed_created_at",
            JSON.stringify({ created_at: validation.data?.created_at }),
          );
          // eslint-disable-next-line no-console
          console.info("[V3_DEBUG] timeline_validation_success", activeTimeline.timeline_id);
        }
      }

      const clock = new RealRuntimeClock();
      const eventBus = new RuntimeEventBus();
      const bridge = new RuntimeRendererBridge({
        clock,
        eventBus,
        viewport: defaultViewport(BOARD_VIEWBOX_W, BOARD_VIEWBOX_H),
      });

      const presentationFrames: CommitPresentationFrame[] = [];

      const result = runtime.run(activeTimeline, {
        eventBus,
        onOperationCommitted(payload) {
          if (debugEnabled) {
            // eslint-disable-next-line no-console
            console.info("[V3_DEBUG] op_committed", payload.operation_id);
          }
          const entry = bridge.onCommittedOperation({
            operation_id: payload.operation_id,
            scene: payload.scene,
            at: payload.at,
          });
          if (debugEnabled) {
            // eslint-disable-next-line no-console
            console.info(
              "[V3_DEBUG] projection_diff_applied",
              JSON.stringify({
                version: entry.version,
                added: entry.diff.added.length,
                updated: entry.diff.updated.length,
                removed: entry.diff.removed.length,
              }),
            );
          }
          const replayed = bridge.replayProjectionStream(entry.version, entry.version, payload.at);
          const snapshot = replayed[0]?.snapshot;
          if (!snapshot) return;

          const byLayer: Record<string, RenderProjection[]> = {};
          snapshot.projections.forEach((projection) => {
            byLayer[projection.layer] = byLayer[projection.layer] ?? [];
            byLayer[projection.layer].push(projection);
          });
          const sceneByType = Object.values(payload.scene.entities_by_id).reduce<Record<string, number>>(
            (acc, entity) => {
              acc[entity.entity_type] = (acc[entity.entity_type] ?? 0) + 1;
              return acc;
            },
            {},
          );

          presentationFrames.push({
            byLayer: structuredClone(byLayer),
            operation_id: payload.operation_id,
            beat_id: payload.beat_id,
            entityCount: Object.keys(payload.scene.entities_by_id).length,
            projectionCount: snapshot.projections.length,
            sceneEntityIds: Object.keys(payload.scene.entities_by_id).sort(),
            sceneByType,
            projectionPreview: snapshot.projections.slice(0, 16).map((projection) => ({
              id: projection.projection_id,
              kind: projection.projection_kind,
              layer: projection.layer,
              source: projection.source_entity_id,
              box: projection.viewport_box,
              visible: projection.visible,
            })),
            sceneHash: payload.scene.scene_hash,
          });

          if (instantBoard) {
            const beatIdx = activeTimeline.beats.find(
              (b) => b.beat_id === payload.beat_id,
            )?.index;
            if (typeof beatIdx === "number" && beatIdx >= 0 && !restoreMode) {
              onPlaybackBeatCommittedRef.current?.(beatIdx);
            }
            setRuntimeSnapshot({
              sceneEntityIds: Object.keys(payload.scene.entities_by_id).sort(),
              sceneByType,
              projectionPreview: snapshot.projections.slice(0, 16).map((projection) => ({
                id: projection.projection_id,
                kind: projection.projection_kind,
                layer: projection.layer,
                source: projection.source_entity_id,
                box: projection.viewport_box,
                visible: projection.visible,
              })),
            });
            setBoardByLayer(structuredClone(byLayer));
            setRuntimeStats((prev) => ({
              committedOps: prev.committedOps + 1,
              entityCount: Object.keys(payload.scene.entities_by_id).length,
              projectionCount: snapshot.projections.length,
              layerCounts: Object.fromEntries(
                Object.entries(byLayer).map(([layer, entries]) => [layer, entries.length]),
              ),
              currentBeatId: payload.beat_id,
              currentOpId: payload.operation_id,
              sceneHash: payload.scene.scene_hash,
            }));
          }
        },
      });

      if (result.state.status === "completed" && presentationFrames.length > 0 && !instantBoard) {
        const beatIndexById = new Map(
          activeTimeline.beats.map((b) => [b.beat_id, b.index] as const),
        );
        const frameBeatIndex = (f: CommitPresentationFrame) =>
          beatIndexById.get(f.beat_id) ?? 0;
        const priorFrames =
          startBeatIndex > 0
            ? presentationFrames.filter((f) => frameBeatIndex(f) < startBeatIndex)
            : [];
        const continuationFrames = presentationFrames.filter(
          (f) => frameBeatIndex(f) >= startBeatIndex,
        );
        const initialFrame =
          priorFrames.length > 0 ? priorFrames[priorFrames.length - 1]! : null;
        setBoardByLayer(
          structuredClone(initialFrame?.byLayer ?? {}),
        );
        setTeachingQueue(
          continuationFrames.length > 0 ? continuationFrames : presentationFrames,
        );
        if (narrationEligible) {
          speechRevealMapRef.current = {};
          setSpeechRevealByEntityId({});
          setSpeechRevealDebug(null);
        }
      } else if (result.state.status === "completed" && presentationFrames.length > 0 && instantBoard) {
        const beatIndexById = new Map(
          activeTimeline.beats.map((b) => [b.beat_id, b.index] as const),
        );
        const frameBeatIndex = (f: CommitPresentationFrame) =>
          beatIndexById.get(f.beat_id) ?? 0;
        const throughBeat =
          restoreMode && restoreStaticThroughBeatIndex != null
            ? restoreStaticThroughBeatIndex
            : null;
        const targetFrame =
          throughBeat != null
            ? (() => {
                const eligible = presentationFrames.filter(
                  (f) => frameBeatIndex(f) <= throughBeat,
                );
                return eligible.length > 0
                  ? eligible[eligible.length - 1]!
                  : presentationFrames[0]!;
              })()
            : presentationFrames[presentationFrames.length - 1]!;
        setBoardByLayer(structuredClone(targetFrame.byLayer));
        setRuntimeStats({
          committedOps: presentationFrames.length,
          entityCount: targetFrame.entityCount,
          projectionCount: targetFrame.projectionCount,
          layerCounts: Object.fromEntries(
            Object.entries(targetFrame.byLayer).map(([layer, entries]) => [
              layer,
              entries.length,
            ]),
          ),
          currentBeatId: targetFrame.beat_id,
          currentOpId: targetFrame.operation_id,
          sceneHash: result.state.current_scene_hash,
        });
        const committedBeatIdx = frameBeatIndex(targetFrame);
        if (
          !restoreMode &&
          typeof committedBeatIdx === "number" &&
          committedBeatIdx >= 0
        ) {
          onPlaybackBeatCommittedRef.current?.(committedBeatIdx);
        }
        if (!restoreMode) {
          finalizeInstructionLifecycle("completed", { reason: "instant_board" });
        }
      } else if (result.state.status === "completed" && presentationFrames.length === 0) {
        // No committed ops (empty timeline / degenerate run) — still unblock orchestration.
        finalizeInstructionLifecycle("completed", { reason: "empty_presentation" });
      }
      if (result.state.status === "failed") {
        const msg = result.state.error?.message ?? "Runtime aborted";
        setDebugError({ kind: "runtime", message: msg });
        if (debugEnabled) {
          // eslint-disable-next-line no-console
          console.error("[V3_DEBUG] runtime_failed", result.state.error);
        }
        finalizeInstructionLifecycle("runtime_failed", { reason: msg });
      } else if (result.state.status === "completed" && debugEnabled) {
        // eslint-disable-next-line no-console
        console.info("[V3_DEBUG] runtime_completed", activeTimeline.timeline_id);
      }
    } catch (err) {
      setDebugError({ kind: "runtime", message: "Unhandled runtime exception" });
      if (debugEnabled) {
        // eslint-disable-next-line no-console
        console.error("[V3_DEBUG] runtime_exception", err);
      }
      finalizeInstructionLifecycle("runtime_failed", {
        reason: err instanceof Error ? err.message : "unhandled_runtime_exception",
      });
    }

  }, [
    debugEnabled,
    enabled,
    finalizeInstructionLifecycle,
    instantBoard,
    opTypes,
    runtime,
    skipValidation,
    playbackRunKey,
    startBeatIndex,
    surface,
    visualizationOnly,
    restoreMode,
    restoreStaticThroughBeatIndex,
    narrationEligible,
  ]);

  useEffect(() => {
    if (!teachingQueue?.length) return;
    if (narrationPlaybackDoneRef.current === playbackRunKey) {
      const hasInk = Object.values(boardByLayerRef.current).some((layer) => layer.length > 0);
      if (hasInk) {
        logNarrationSync("cadence_skipped_playback_done", { timeline_id: timelineRunId });
        return;
      }
      narrationPlaybackDoneRef.current = null;
    }

    const queue = teachingQueue;
    const activeTimeline = timelineRef.current;

    const clearHighlightTtlTimers = (): void => {
      for (const id of highlightTtlTimerIdsRef.current) {
        window.clearTimeout(id);
      }
      highlightTtlTimerIdsRef.current = [];
    };

    const scheduleHighlightTtl = (operationId: string): void => {
      const op = findHighlightOpForOperationId(activeTimeline.beats, operationId);
      const ttlMs = op?.payload.ttl_ms;
      if (!op || typeof ttlMs !== "number" || ttlMs <= 0) return;
      const highlightId = op.payload.highlight_id;
      const timerId = window.setTimeout(() => {
        setTtlExpiredHighlightIds((prev) => {
          const next = new Set(prev);
          next.add(highlightId);
          return next;
        });
        logHighlightLifecycle({
          event: "ttl_expired",
          highlight_id: highlightId,
          ttl_ms: ttlMs,
          timeline_id: timelineRunId,
          operation_id: operationId,
        });
      }, ttlMs);
      highlightTtlTimerIdsRef.current.push(timerId);
    };

    const apply = (i: number): void => {
      const f = queue[i];
      setBoardByLayer(structuredClone(f.byLayer));
      setRuntimeStats({
        committedOps: i + 1,
        entityCount: f.entityCount,
        projectionCount: f.projectionCount,
        layerCounts: Object.fromEntries(
          Object.entries(f.byLayer).map(([layer, entries]) => [layer, entries.length]),
        ),
        currentBeatId: f.beat_id,
        currentOpId: f.operation_id,
        sceneHash: f.sceneHash,
      });
      setRuntimeSnapshot({
        sceneEntityIds: f.sceneEntityIds,
        sceneByType: f.sceneByType,
        projectionPreview: f.projectionPreview,
      });
      setFocusEntityId(primaryEntityIdForOperation(activeTimeline, f.operation_id));

      const highlightOp = findHighlightOpForOperationId(activeTimeline.beats, f.operation_id);
      if (highlightOp) {
        scheduleHighlightTtl(f.operation_id);
      }

      const painted = Object.values(f.byLayer).flat();
      const highlightSummary = summarizeHighlightProjections(painted, ttlExpiredHighlightIdsRef.current);
      logHighlightLifecycle({
        event: "presentation_frame",
        timeline_id: timelineRunId,
        operation_id: f.operation_id,
        beat_id: f.beat_id,
        ...highlightSummary,
      });
      const annotationSummary = summarizeAnnotationProjections(painted);
      logAnnotationLifecycle({
        event: "presentation_frame",
        timeline_id: timelineRunId,
        operation_id: f.operation_id,
        beat_id: f.beat_id,
        ...annotationSummary,
      });
      const beatIdx = activeTimeline.beats.find((b) => b.beat_id === f.beat_id)?.index;
      if (typeof beatIdx === "number" && beatIdx >= 0) {
        onPlaybackBeatCommittedRef.current?.(beatIdx);
      }
    };

    const applyWithSpeechReveal = (frameIndex: number, narrationStartChunk = 0): string[] => {
      apply(frameIndex);
      const f = queue[frameIndex]!;
      const targets = extractSpeechRevealTargets(
        activeTimeline,
        f.operation_id,
        f.byLayer,
      );
      if (targets.length > 0) {
        speechRevealMapRef.current = registerSpeechRevealTargets(
          speechRevealMapRef.current,
          targets,
          narrationStartChunk,
        );
        setSpeechRevealByEntityId({ ...speechRevealMapRef.current });
      }
      return targets.map((t) => t.entityId);
    };

    const beatActiveRevealIdsRef = { current: [] as string[] };

    let visualBeatId = "";
    let visualClockSealed = false;
    let lastNarrationWord = 0;
    let visualVisibleMs = 0;
    let visualNarration = "";
    const visualTimers: number[] = [];
    let boardBurst: number[] = [];
    let boardBurstCount = 0;
    const clearVisualTimers = () => {
      for (const id of visualTimers) window.clearTimeout(id);
      visualTimers.length = 0;
      boardBurst = [];
    };
    const startSyntheticVisualClock = (narration: string, visibleMs: number, beatId: string) => {
      const events = visualClockEvents(narration, visibleMs);
      for (const event of events.slice(1)) {
        const id = window.setTimeout(() => {
          if (cancelled || visualBeatId !== beatId) return;
          lastNarrationWord = event.narrationWordIndex;
          setVtseWordIndex(event.narrationWordIndex);
        }, event.atMs);
        visualTimers.push(id);
      }
    };
    const applyBoardBurst = () => {
      if (!boardBurst.length || cancelled) return;
      const batch = boardBurst.splice(0);
      if (isCollapsedWordBurst(batch, boardBurstCount)) {
        startSyntheticVisualClock(visualNarration, visualVisibleMs, visualBeatId);
        return;
      }
      const narrIdx = narrationWordIndexForBoardWord(
        visualNarration,
        batch[batch.length - 1] ?? 0,
        boardBurstCount,
      );
      if (narrIdx === 0 && lastNarrationWord > 0) return;
      lastNarrationWord = Math.max(lastNarrationWord, narrIdx);
      setVtseWordIndex(lastNarrationWord);
    };
    const noteBoardWord = (boardIndex: number, boardCount: number, narration: string) => {
      if (visualClockSealed || !isTtsClientAvailable()) return;
      boardBurst.push(boardIndex);
      boardBurstCount = boardCount;
      visualNarration = narration;
      const id = window.setTimeout(() => {
        if (visualClockSealed) return;
        applyBoardBurst();
      }, 0);
      visualTimers.push(id);
    };
    const publishVtseBeat = (beat: Beat, narration: string, visibleMs: number) => {
      if (visualBeatId === beat.beat_id) return;
      visualBeatId = beat.beat_id;
      visualClockSealed = false;
      lastNarrationWord = 0;
      visualVisibleMs = visibleMs;
      visualNarration = narration;
      clearVisualTimers();
      setVtseBeatId(beat.beat_id);
      setVtseWordIndex(0);
      if (process.env.NEXT_PUBLIC_V3_DEBUG === "1") {
        console.info("[VTSE_VISUAL] publish_beat", {
          beat_id: beat.beat_id,
          visibleMs,
          tts: isTtsClientAvailable(),
        });
      }
      if (!isTtsClientAvailable()) {
        startSyntheticVisualClock(narration, visibleMs, beat.beat_id);
      }
    };
    const sealVisualClock = () => {
      applyBoardBurst();
      visualClockSealed = true;
    };

    const runSpeechSyncedSegment = async (
      narrationText: string,
      targetEntityIds: string[],
    ): Promise<void> => {
      const spokenText = normalizeColumnIntroNarration(narrationText);
      if (!targetEntityIds.length) {
        await speakUtteranceWithHooks(spokenText, {});
        sealVisualClock();
        return;
      }
      const boardCount = wordChunks(spokenText).length;
      await speakSegmentWithSpeechReveal({
        narrationText: spokenText,
        targetEntityIds,
        getRevealMap: () => speechRevealMapRef.current,
        patchRevealMap: (updater) => {
          speechRevealMapRef.current = updater(speechRevealMapRef.current);
          setSpeechRevealByEntityId({ ...speechRevealMapRef.current });
        },
        onDebug: (meta) => {
          setSpeechRevealDebug(meta);
          logNarrationSync("speech_reveal_complete", {
            timeline_id: timelineRunId,
            ...meta,
          });
        },
        onWordIndex: (wordIndex) => noteBoardWord(wordIndex, boardCount, narrationText),
      });
      sealVisualClock();
    };

    let cancelled = false;
    const minDelay = activeTimeline.global_sync_policy.min_delay_ms ?? 350;

    if (!narrationEligible) {
      apply(0);
      if (queue.length <= 1) {
        if (!cancelled) {
          narrationPlaybackDoneRef.current = playbackRunKey;
          finalizeInstructionLifecycle("completed", { reason: "timer_single_step" });
        }
        return () => {
          cancelled = true;
          clearHighlightTtlTimers();
          logNarrationSync("cancelled", { timeline_id: timelineRunId, path: "timer_single_step" });
        };
      }
      let step = 1;
      const id = window.setInterval(() => {
        if (cancelled) {
          window.clearInterval(id);
          return;
        }
        if (step >= queue.length) {
          window.clearInterval(id);
          narrationPlaybackDoneRef.current = playbackRunKey;
          finalizeInstructionLifecycle("completed", { reason: "timer_cadence_finished" });
          return;
        }
        apply(step);
        step += 1;
      }, teachingStepMs);
      return () => {
        cancelled = true;
        window.clearInterval(id);
        clearHighlightTtlTimers();
        logNarrationSync("cancelled", { timeline_id: timelineRunId, path: "timer_interval" });
      };
    }

    async function runLegacyFrameNarration(frameIndex: number): Promise<void> {
      const frame = queue[frameIndex];
      const nb = findNarrationBinding(activeTimeline, frame.operation_id);

      if (!nb) {
        logNarrationSync("segment_missing_binding", {
          timeline_id: timelineRunId,
          operation_id: frame.operation_id,
          step: frameIndex,
        });
        await sleep(minDelay);
        if (cancelled) return;
        apply(frameIndex);
        return;
      }

      const { segment, binding } = nb;
      const pause = pauseAfterSegment(segment, minDelay);
      const text = segment.text;

      switch (binding.relation) {
        case "before_segment": {
          const ids = applyWithSpeechReveal(frameIndex);
          if (cancelled) return;
          await runSpeechSyncedSegment(text, ids);
          if (cancelled) return;
          await sleep(pause);
          break;
        }

        case "on_segment_start": {
          const ids = applyWithSpeechReveal(frameIndex);
          await new Promise<void>((resolve) => {
            requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
          });
          if (cancelled) return;
          await runSpeechSyncedSegment(text, ids);
          if (cancelled) return;
          await sleep(pause);
          break;
        }

        case "during_segment": {
          const offset = revealOffsetMs(segment);
          if (offset > 0) {
            await sleep(offset);
          }
          if (cancelled) return;
          const ids = applyWithSpeechReveal(frameIndex);
          await runSpeechSyncedSegment(text, ids);
          if (cancelled) return;
          await sleep(pause);
          break;
        }

        case "on_segment_end": {
          const ids = applyWithSpeechReveal(frameIndex);
          if (cancelled) return;
          await runSpeechSyncedSegment(text, ids);
          if (cancelled) return;
          await sleep(pause);
          break;
        }

        case "after_segment":
          await speakUtteranceWithHooks(text, {
            onUtteranceEnd: () => {
              if (!cancelled) apply(frameIndex);
            },
          });
          if (cancelled) return;
          await sleep(pause);
          break;

        default:
          await sleep(minDelay);
          if (cancelled) return;
          apply(frameIndex);
      }
    }

    async function runBeatOrchestratedNarration(): Promise<void> {
      logNarrationSync("started", {
        timeline_id: timelineRunId,
        queue_steps: queue.length,
        mode: "beat_orchestration",
      });
      setFocusEntityId(null);

      const frameIndexByOp = new Map<string, number>();
      queue.forEach((f, i) => {
        frameIndexByOp.set(f.operation_id, i);
      });

      const beatIndexById = new Map(activeTimeline.beats.map((b) => [b.beat_id, b.index]));
      const beatsInOrder = activeTimeline.beats
        .filter((b) => (beatIndexById.get(b.beat_id) ?? 0) >= startBeatIndex)
        .sort((a, b) => a.index - b.index);

      const firstBeat = beatsInOrder[0];
      if (firstBeat && queue.length > 0 && !cancelled) {
        const plan = buildBeatOrchestrationPlan(firstBeat, minDelay);
        const warmOp =
          plan?.onStart[0] ??
          plan?.before[0] ??
          queue.find((f) => f.beat_id === firstBeat.beat_id)?.operation_id;
        const warmIdx = warmOp ? frameIndexByOp.get(warmOp) : 0;
        if (warmIdx != null) apply(warmIdx);
      }

      const forceStableReveal = (entityIds: string[]) => {
        if (entityIds.length === 0) return;
        const endMs = Date.now();
        for (const id of entityIds) {
          const s = speechRevealMapRef.current[id];
          if (s) speechRevealMapRef.current[id] = stabilizeSpeechReveal(s, endMs);
        }
        setSpeechRevealByEntityId({ ...speechRevealMapRef.current });
      };

      async function maybeAwaitFlowCheckpoint(beat: Beat): Promise<void> {
        const gate = flowCheckpointGateRef.current;
        if (!gate || cancelled) return;
        const event = buildFlowCheckpointEventForBeat(activeTimeline, beat);
        if (!event) return;
        await gate.onFlowNodeCompleted(event);
      }

      for (const beat of beatsInOrder) {
        if (cancelled) return;

        const plan = buildBeatOrchestrationPlan(beat, minDelay);
        if (!plan) continue;
        publishVtseBeat(beat, plan.segment.text, pauseAfterSegment(plan.segment, minDelay));

        const beatFrames = queue
          .map((f, i) => ({ f, i }))
          .filter((x) => x.f.beat_id === beat.beat_id);

        const applyOp = (opId: string, narrationStartChunk = 0): string[] => {
          const idx = frameIndexByOp.get(opId);
          if (idx == null) return [];
          const ids = applyWithSpeechReveal(idx, narrationStartChunk);
          setFocusEntityId(primaryEntityIdForOperation(activeTimeline, opId));
          beatActiveRevealIdsRef.current = [
            ...new Set([...beatActiveRevealIdsRef.current, ...ids]),
          ];
          return ids;
        };

        if (!plan.orchestrated) {
          logNarrationSync("beat_legacy_frames", {
            timeline_id: timelineRunId,
            beat_id: beat.beat_id,
            frames: beatFrames.length,
          });
          for (const { i } of beatFrames) {
            if (cancelled) return;
            await runLegacyFrameNarration(i);
          }
          if (cancelled) return;
          await maybeAwaitFlowCheckpoint(beat);
          continue;
        }

        logNarrationSync("beat_orchestrated", {
          timeline_id: timelineRunId,
          beat_id: beat.beat_id,
          on_start: plan.onStart.length,
          during: plan.during.length,
          on_end: plan.onEnd.length,
          after: plan.after.length,
        });

        for (const opId of plan.before) {
          if (cancelled) return;
          applyOp(opId);
        }

        beatActiveRevealIdsRef.current = [];

        for (const opId of plan.onStart) {
          if (cancelled) return;
          applyOp(opId, 0);
          await new Promise<void>((resolve) => {
            requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
          });
        }

        const text = plan.segment.text;
        const leftSpeakIds = [...beatActiveRevealIdsRef.current];

        if (leftSpeakIds.length > 0) {
          await runSpeechSyncedSegment(text, leftSpeakIds);
          forceStableReveal(leftSpeakIds);
        } else {
          await speakUtteranceWithHooks(text, {});
        }

        if (cancelled) return;

        for (const d of plan.during) {
          if (cancelled) return;
          const rightIds = applyOp(d.operationId, 0);
          if (rightIds.length > 0) {
            await runSpeechSyncedSegment(text, rightIds);
            forceStableReveal(rightIds);
          }
        }

        if (cancelled) return;

        for (const opId of plan.onEnd) {
          if (cancelled) return;
          const ids = applyOp(opId, 0);
          const endMs = Date.now();
          setSpeechRevealByEntityId((prev) => {
            const next = { ...prev };
            for (const entityId of ids) {
              const s = next[entityId];
              if (s) next[entityId] = stabilizeSpeechReveal(s, endMs);
            }
            return next;
          });
        }

        if (cancelled) return;

        for (const opId of plan.after) {
          applyOp(opId);
        }

        await sleep(plan.pauseAfterMs);

        if (cancelled) return;
        await maybeAwaitFlowCheckpoint(beat);
      }

      if (!cancelled) {
        narrationPlaybackDoneRef.current = playbackRunKey;
        logNarrationSync("completed", {
          timeline_id: timelineRunId,
          queue_steps: queue.length,
          mode: "beat_orchestration",
        });
        finalizeInstructionLifecycle("completed", { reason: "narration_sync_finished" });
      }
    }

    async function runNarrationSynced(): Promise<void> {
      await runBeatOrchestratedNarration();
    }

    void runNarrationSynced().catch((err: unknown) => {
      if (debugEnabled) {
        // eslint-disable-next-line no-console
        console.error("[V3_DEBUG] narration_sync_failed", err);
      }
      finalizeInstructionLifecycle("runtime_failed", {
        reason: err instanceof Error ? err.message : "narration_sync_failed",
      });
    });

    return () => {
      cancelled = true;
      clearVisualTimers();
      clearHighlightTtlTimers();
      cancelSpeech();
      logNarrationSync("cancelled", { timeline_id: timelineRunId, path: "narration_effect_cleanup" });
    };
  }, [
    debugEnabled,
    finalizeInstructionLifecycle,
    teachingQueue,
    teachingStepMs,
    playbackRunKey,
    timelineRunId,
    narrationEligible,
    startBeatIndex,
    visualizationOnly,
  ]);

  if (!enabled) return null;

  const vtseVisualBesideBoard =
    showVtseVisuals && !vtseVisualUnavailable && vtseHasVisualPackage;
  const vtseVisualFlow = vtseVisualFlowMode({
    hasPackage: vtseVisualBesideBoard,
    showVisuals: true,
    containerWidth: vtseRowWidth || VTSE_VISUAL_SPLIT_MIN_PX,
  });

  const outerShellClass = isWhiteboardSurface
    ? "relative flex w-full shrink-0 flex-col gap-0"
    : "relative flex flex-col gap-2 rounded-lg border border-indigo-200/70 bg-indigo-50/40 p-3 dark:border-indigo-900/60 dark:bg-indigo-950/20";

  const boardShellClass = isWhiteboardSurface
    ? "relative w-full shrink-0"
    : "relative max-h-[min(72vh,680px)] w-full min-h-0 shrink-0 overflow-y-auto overflow-x-auto overscroll-contain rounded-2xl border border-slate-200/90 bg-gradient-to-b from-[#f6f4ef] to-[#ece8df] p-3 shadow-[0_16px_48px_-20px_rgba(15,23,42,0.22)] [scrollbar-gutter:stable] dark:border-slate-700/80 dark:from-slate-900 dark:to-slate-950 dark:shadow-[0_20px_50px_-18px_rgba(0,0,0,0.55)]";

  return (
    <div className={outerShellClass}>
      {!isWhiteboardSurface ? (
        <div className="flex flex-wrap items-start justify-between gap-2 px-0.5">
          <div>
            <p className="text-xs font-semibold text-indigo-800 dark:text-indigo-200">Timeline V3 Live Lesson</p>
            <p className="mt-0.5 max-w-xl text-[11px] leading-snug text-slate-600 dark:text-slate-400">
              Watch the explanation take shape on the board—one piece at a time.
            </p>
          </div>
          {!instantBoard && narrationEligible ? (
            <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-medium text-emerald-900 dark:bg-emerald-950/60 dark:text-emerald-200">
              Narration-synced board
            </span>
          ) : !instantBoard ? (
            <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-medium text-emerald-900 dark:bg-emerald-950/60 dark:text-emerald-200">
              Teaching cadence · {teachingStepMs}ms per step
            </span>
          ) : (
            <span className="rounded-full bg-slate-200 px-2 py-0.5 text-[10px] font-medium text-slate-700 dark:bg-slate-700 dark:text-slate-200">
              Instant board (NEXT_PUBLIC_V3_INSTANT_BOARD)
            </span>
          )}
        </div>
      ) : null}
      {isWhiteboardSurface && debugError && !debugEnabled && debugError.kind !== "validation" ? (
        <div
          role="alert"
          className="mb-2 rounded-lg border border-amber-200/90 bg-amber-50/95 px-3 py-2.5 text-sm leading-snug text-amber-950 shadow-sm dark:border-amber-900/40 dark:bg-amber-950/35 dark:text-amber-50"
        >
          The teaching board could not load this step. You can keep going—the lesson will continue with the next
          prompt or question.
        </div>
      ) : null}
      {debugEnabled && isWhiteboardSurface && validationReport?.status === "failed" ? (
        <div
          className="mb-1 shrink-0 rounded border border-rose-400/70 bg-rose-50 px-2 py-1 font-mono text-[10px] leading-tight text-rose-950 dark:border-rose-700 dark:bg-rose-950/60 dark:text-rose-100"
          role="status"
        >
          [INSTRUCTION_BOARD_VALIDATION] path={validationReport.errors[0]?.path ?? "?"}{" "}
          code={validationReport.errors[0]?.code ?? "?"}
        </div>
      ) : null}
      {debugEnabled ? (
        <details className="max-h-52 shrink-0 overflow-hidden rounded-lg border border-slate-300 bg-white/85 text-[11px] text-slate-700 shadow-sm dark:border-slate-600 dark:bg-slate-900/85 dark:text-slate-200">
          <summary className="cursor-pointer select-none px-3 py-2 font-semibold hover:bg-slate-50 dark:hover:bg-slate-800">
            V3 technical debug (collapsed by default — expand for logs)
          </summary>
          <div className="max-h-44 space-y-2 overflow-y-auto overscroll-contain border-t border-slate-200 p-2 dark:border-slate-700">
            {validationReport ? (
              <details
                className="rounded border border-slate-300 dark:border-slate-600"
                open={validationReport.status === "failed"}
              >
                <summary className="cursor-pointer select-none bg-slate-100 px-2 py-1 font-medium dark:bg-slate-800">
                  Validation: {validationReport.status}
                  {validationReport.status === "failed"
                    ? ` — ${validationReport.errors.length} error(s)`
                    : null}
                  {skipValidation ? " (client check skipped)" : null}
                </summary>
                <div className="max-h-48 overflow-y-auto border-t border-slate-200 p-2 font-mono text-[10px] dark:border-slate-700">
                  {validationReport.status === "failed" ? (
                    <>
                      <div className="mb-1 font-sans text-[11px] font-medium text-rose-700 dark:text-rose-300">
                        Errors (full JSON, see console for same)
                      </div>
                      <pre className="whitespace-pre-wrap break-all">
                        {stringifyValidationErrorsDeep(validationReport.errors)}
                      </pre>
                      <div className="mb-1 mt-2 font-sans text-[11px] font-medium text-rose-700 dark:text-rose-300">
                        Failing operations (full op JSON)
                      </div>
                      <pre className="whitespace-pre-wrap break-all">
                        {JSON.stringify(
                          validationReport.failingOps.map((f) => ({
                            beat_id: f.beat_id,
                            operation_id: f.operation_id,
                            op_type: f.op_type,
                            op: f.op,
                          })),
                          null,
                          2,
                        )}
                      </pre>
                    </>
                  ) : (
                    <div className="font-sans">
                      {validationReport.status === "skipped"
                        ? "Frontend schema/invariant/DAG validation was skipped. Runtime still executes if payload is usable."
                        : "Timeline passed validateTimeline (schema + semantic + global DAG)."}
                    </div>
                  )}
                </div>
              </details>
            ) : (
              <div className="text-slate-500">Validation: (pending)</div>
            )}

            <details className="rounded border border-slate-300 dark:border-slate-600" open>
              <summary className="cursor-pointer select-none bg-slate-100 px-2 py-1 font-medium dark:bg-slate-800">
                Timeline summary
              </summary>
              <div className="space-y-1 border-t border-slate-200 p-2 dark:border-slate-700">
                <div>timeline_id: {timeline.timeline_id}</div>
                <div>planner_source: {plannerSource ?? "unknown"}</div>
                <div>beats: {timeline.beats.length}</div>
                <div>ops: {timeline.beats.reduce((n, b) => n + b.operations.length, 0)}</div>
                <div>op_types: {opTypes.join(", ") || "none"}</div>
              </div>
            </details>

            <details className="rounded border border-slate-300 dark:border-slate-600" open>
              <summary className="cursor-pointer select-none bg-slate-100 px-2 py-1 font-medium dark:bg-slate-800">
                Runtime stats
              </summary>
              <div className="space-y-1 border-t border-slate-200 p-2 dark:border-slate-700">
                <div>committed_ops: {runtimeStats.committedOps}</div>
                <div>entity_count: {runtimeStats.entityCount}</div>
                <div>projection_count: {runtimeStats.projectionCount}</div>
                <div>current_beat: {runtimeStats.currentBeatId ?? "none"}</div>
                <div>current_op: {runtimeStats.currentOpId ?? "none"}</div>
                <div>scene_hash: {runtimeStats.sceneHash ?? "none"}</div>
                {speechRevealDebug ? (
                  <>
                    <div>narration_chunk_count: {speechRevealDebug.narration_chunk_count}</div>
                    <div>active_speech_chunk: {String(speechRevealDebug.active_speech_chunk)}</div>
                    <div>narration_sync_latency: {speechRevealDebug.narration_sync_latency}ms</div>
                    <div>reveal_completion_time: {speechRevealDebug.reveal_completion_time ?? "—"}</div>
                  </>
                ) : null}
                <div>
                  layer_counts:{" "}
                  {Object.entries(runtimeStats.layerCounts)
                    .map(([layer, count]) => `${layer}:${count}`)
                    .join(" | ") || "none"}
                </div>
              </div>
            </details>

            <details className="rounded border border-slate-300 dark:border-slate-600">
              <summary className="cursor-pointer select-none bg-slate-100 px-2 py-1 font-medium dark:bg-slate-800">
                Beats / op ids
              </summary>
              <div className="max-h-40 overflow-y-auto border-t border-slate-200 p-2 dark:border-slate-700">
                {timeline.beats.map((beat) => (
                  <div key={beat.beat_id}>
                    {beat.beat_id} [{beat.index}] ops=
                    {beat.operations.map((op) => `${op.operation_id}:${op.op_type}`).join(", ")}
                  </div>
                ))}
              </div>
            </details>

            <details className="rounded border border-slate-300 dark:border-slate-600">
              <summary className="cursor-pointer select-none bg-slate-100 px-2 py-1 font-medium dark:bg-slate-800">
                Scene / projection preview
              </summary>
              <div className="max-h-40 overflow-y-auto space-y-1 border-t border-slate-200 p-2 dark:border-slate-700">
                <div>
                  scene_by_type:{" "}
                  {Object.entries(runtimeSnapshot.sceneByType)
                    .map(([k, v]) => `${k}:${v}`)
                    .join(" | ") || "none"}
                </div>
                <div>scene_entity_ids: {runtimeSnapshot.sceneEntityIds.join(", ") || "none"}</div>
                {runtimeSnapshot.projectionPreview.length === 0 ? (
                  <div>projection_preview: empty</div>
                ) : (
                  runtimeSnapshot.projectionPreview.map((p) => (
                    <div key={p.id}>
                      {p.id} kind={p.kind} layer={p.layer} source={p.source} visible={String(p.visible)}{" "}
                      box=({p.box.x},{p.box.y},{p.box.w},{p.box.h})
                    </div>
                  ))
                )}
              </div>
            </details>
          </div>
        </details>
      ) : null}
      {debugEnabled && debugError ? (
        <div className="rounded border border-rose-300 bg-rose-50 p-2 text-xs text-rose-800 dark:border-rose-800 dark:bg-rose-950/40 dark:text-rose-200">
          [V3_DEBUG] Runtime Failure ({debugError.kind}): {debugError.message}
        </div>
      ) : null}
      {forceRenderProbe ? (
        <div
          className="flex items-center justify-center font-black text-white"
          style={{ width: 400, height: 200, background: "red", fontSize: 28 }}
        >
          FORCED RENDER WORKS
        </div>
      ) : null}
      <div className={boardShellClass} role="region" aria-label="Teaching board">
        <div
          className={
            vtseVisualBesideBoard
              ? "w-full min-w-0"
              : isWhiteboardSurface
                ? "mx-auto flex w-full min-w-0 shrink-0 justify-center"
                : "mx-auto flex w-full min-w-0 justify-center"
          }
        >
          {validationReport?.status === "failed" && isWhiteboardSurface ? (
            <div
              role="status"
              className="flex min-h-[220px] w-full max-w-xl flex-col items-center justify-center gap-2 px-4 text-center text-sm text-slate-600 dark:text-slate-300"
            >
              <p>We could not preview this diagram. The lesson continues.</p>
              {debugEnabled && validationReport.errors[0] ? (
                <p className="max-w-full break-words font-mono text-[10px] text-rose-800 dark:text-rose-200">
                  {(validationReport.errors[0].path as string | undefined) ?? "(no path)"}:{" "}
                  {validationReport.errors[0].message}
                </p>
              ) : null}
            </div>
          ) : (
            <V3MinimalRendererErrorBoundary>
              {vtseVisualBesideBoard ? (
                <div
                  ref={vtseRowRef}
                  data-vtse-visual-flow={vtseVisualFlow === "stack" ? "stack" : "split"}
                  className="w-full min-w-0"
                  style={
                    vtseVisualFlow === "stack"
                      ? {
                          display: "grid",
                          gridTemplateColumns: "minmax(0, 1fr)",
                          gap: "0.75rem",
                          alignItems: "start",
                        }
                      : {
                          display: "grid",
                          gridTemplateColumns: "minmax(0, 7fr) minmax(20rem, 3fr)",
                          gap: "1.25rem",
                          alignItems: "start",
                        }
                  }
                >
                  <div
                    className="relative min-w-0"
                    style={{ overflow: "hidden", gridRow: vtseVisualFlow === "stack" ? 2 : "auto" }}
                  >
                    <MinimalDeterministicRenderer
                      projectionsByLayer={boardByLayer}
                      width={BOARD_VIEWBOX_W}
                      height={BOARD_VIEWBOX_H}
                      debug={debugEnabled}
                      showDebugFallback={debugEnabled}
                      prodBaseline={debugEnabled && prodBaselineStrip}
                      layoutKind={layoutKind}
                      presentation={debugEnabled ? "debug" : "teaching"}
                      clipToViewport={!isWhiteboardSurface}
                      stepKey={runtimeStats.currentOpId}
                      focusEntityId={focusEntityId}
                      ttlExpiredHighlightIds={ttlExpiredHighlightIds}
                      speechRevealByEntityId={speechRevealByEntityId}
                      speechRevealEnabled={narrationEligible}
                    />
                  </div>
                  <div
                    className="relative min-w-0"
                    style={{ zIndex: 1, gridRow: vtseVisualFlow === "stack" ? 1 : "auto" }}
                  >
                    <VtseVisualCompanion
                      timeline={timeline}
                      beatId={vtseBeatId}
                      wordIndex={vtseWordIndex}
                      enabled
                      frame={vtseVisualFlow === "stack" ? "stack" : "split"}
                      onUnavailable={() => setVtseVisualUnavailable(true)}
                    />
                  </div>
                </div>
              ) : (
                <div className="relative">
                  <MinimalDeterministicRenderer
                    projectionsByLayer={boardByLayer}
                    width={BOARD_VIEWBOX_W}
                    height={BOARD_VIEWBOX_H}
                    debug={debugEnabled}
                    showDebugFallback={debugEnabled}
                    prodBaseline={debugEnabled && prodBaselineStrip}
                    layoutKind={layoutKind}
                    presentation={debugEnabled ? "debug" : "teaching"}
                    clipToViewport={!isWhiteboardSurface}
                    stepKey={runtimeStats.currentOpId}
                    focusEntityId={focusEntityId}
                    ttlExpiredHighlightIds={ttlExpiredHighlightIds}
                    speechRevealByEntityId={speechRevealByEntityId}
                    speechRevealEnabled={narrationEligible}
                  />
                </div>
              )}
            </V3MinimalRendererErrorBoundary>
          )}
        </div>
      </div>
    </div>
  );
}
