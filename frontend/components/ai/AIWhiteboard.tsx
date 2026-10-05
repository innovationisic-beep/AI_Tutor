"use client";

import {
  useEffect,
  useMemo,
  useRef,
  type ReactNode,
} from "react";
import { WordSyncedStreaming } from "./WordSyncedStreaming";
import { StreamingText } from "./StreamingText";
import { ProductionTimelineRuntimeView } from "@/components/ai/timeline-v3/ProductionTimelineRuntimeView";
import type { InstructionTimelineV3 } from "@/lib/instruction-timeline-v3/types";
import {
  resolveProductionVisualRenderer,
  logProductionVisualRenderer,
} from "@/lib/learning/productionVisualRenderer";
import { boardItemPlaybackStart } from "@/lib/learning/instructionOwnership";
import {
  buildBoardScrollFollowKey,
  scrollElementToBottom,
  shouldScrollOnContentGrowth,
  shouldScrollOnFollowKeyChange,
  stickAfterUserScroll,
} from "@/lib/learning/boardAutoScroll";
import { FlowCheckpointOverlay } from "@/components/learning/FlowCheckpointOverlay";
import {
  PedagogyIntroCard,
  parsePedagogyIntroCard,
} from "@/components/learning/PedagogyIntroCard";
import { ConceptStoryHookCard } from "@/components/learning/ConceptStoryHookCard";
import {
  ConceptVisualTeachingCard,
  parseConceptVisualTeachingCard,
} from "@/components/learning/ConceptVisualTeachingCard";
import { ZoneIndicator } from "@/components/learning/ZoneIndicator";
import type { FlowCheckpointGate } from "@/lib/learning/flowCheckpointOrchestrator";
import type { FlowCheckpointUi } from "@/lib/learning/useFlowCheckpointController";
import {
  groupWhiteboardSegments,
  attachStoryHookStepStreaming,
  attachVisualTeachingBeatStreaming,
  type StoryHookStreamedStep,
  type WhiteboardSegment,
} from "@/lib/learning/storyHookBoardGrouping";
import { WHITEBOARD_TEXT_CLASS } from "@/lib/teachingTypography";
import {
  timelineHasVtseVisualPackage,
  VTSE_VISUAL_WIDE_CLASS,
  WHITEBOARD_CONTENT_COLUMN_CLASS,
} from "@/lib/vtse-visuals/boardLayout";

export type BoardItem = {
  id: string;
  type: string;
  content: string;
  visual?: { svg?: string | null } | null;
  /** Timeline V3 board payload (authored VTSE → ITV3). */
  instruction_timeline_v3?: InstructionTimelineV3 | null;
  planner_source?: string | null;
  cir_instruction_debug?: Record<string, unknown> | null;
  timeline_metadata?: Record<string, unknown> | null;
  /** Zone 0 dual-channel: when writingMode is notes, WSS uses displayText for ink. */
  writingMode?: "legacy" | "notes";
  displayText?: string;
  /** Sentence-anchored board writes (preferred over proportional displayText). */
  boardWrites?: Array<{ sentenceIndex: number; text: string }>;
};

const PLACEHOLDER = "AI is ready to teach...";

const streamTextClass = WHITEBOARD_TEXT_CLASS;

type AIWhiteboardProps = {
  items: BoardItem[];
  /** Large centered topic title at the top of the board. */
  topicTitle?: string | null;
  /** Current teaching zone — shown inside the board surface (not on the frame). */
  zone?: number;
  /**
   * Called once the last board item finishes streaming.
   * Used by the parent to ungate quiz card rendering.
   */
  onLastItemComplete?: () => void;
  /** Flow checkpoint runtime gate (flow_vertical_process topics only). */
  flowCheckpointGate?: FlowCheckpointGate | null;
  flowCheckpointUi?: FlowCheckpointUi | null;
  /** Resume mode: static board playback, no TTS or auto-advance side effects. */
  restoreMode?: boolean;
  /** Per-item static restore (board item id → beat index; -1 = prose-only). */
  staticRestoreByItemId?: Record<string, number>;
  /** Live VTSE beat checkpoint while teaching. */
  onPlaybackBeatCommitted?: (beatIndex: number) => void;
  /** VTSE diagram overlay. Off while reteach is paraphrasing the same beats. */
  showVtseVisuals?: boolean;
  /**
   * Persist Visual Teaching sentence progress (silent background session action).
   * Carries scene + beat identity for stale-callback rejection.
   */
  onVisualTeachingSentenceProgress?: (progress: {
    sceneIndex: number;
    beatIndex: number;
    sentenceIndex: number;
  }) => void;
  /**
   * Chronological stage-anchored timeline (preferred).
   * When set, legacy `inlineChat` / before-after split props are ignored.
   */
  timeline?: Array<
    | { kind: "board"; items: BoardItem[] }
    | { kind: "conversation"; key: string; content: ReactNode }
  >;
  /** @deprecated Prefer `timeline`. */
  inlineChat?: ReactNode;
  /** @deprecated Prefer `timeline`. */
  itemsBeforeInlineChat?: BoardItem[];
  /** @deprecated Prefer `timeline`. */
  itemsAfterInlineChat?: BoardItem[];
  /**
   * Composer / action chrome — anchored at the bottom of the inner writing
   * surface (inside the board frame), not a page-level sibling footer.
   */
  boardFooter?: ReactNode;
  /**
   * When false, skip auto-follow (restore/hydration). Default true.
   */
  autoScrollEnabled?: boolean;
  /**
   * External panel/stage that opened over/below the board
   * (e.g. concept-check, cluster-quiz). Changes trigger one follow scroll.
   */
  scrollFollowPanelKey?: string | null;
};

/** Bold rule between stacked *visible* AI responses */
function ResponseDivider() {
  return (
    <div
      className="my-7 w-full shrink-0 border-t-4 border-zinc-900 dark:border-zinc-200"
      role="separator"
      aria-hidden
    />
  );
}

/** Notes-mode board item with no durable ink (speak-only dual channel). */
export function isNotesSpeakOnlyBoardItem(item: BoardItem): boolean {
  if (item.writingMode !== "notes") return false;
  if (item.boardWrites && item.boardWrites.length > 0) return false;
  if (String(item.displayText ?? "").trim()) return false;
  return true;
}

/** Story Hook streamed steps that would show card chrome / image / ink. */
export function storyHookStreamHasVisibleLayout(
  steps: StoryHookStreamedStep[]
): boolean {
  return steps.some((step) => {
    if (step.imagePath) return true;
    if (step.boardWrites && step.boardWrites.length > 0) return true;
    if (step.displayText !== undefined) {
      return Boolean(String(step.displayText).trim());
    }
    // Legacy: spoken text is the visible ink.
    const spoken =
      (step.streamText && step.streamText.trim() && step.streamText !== "\u00a0"
        ? step.streamText
        : step.spokenText || step.body) || "";
    return Boolean(String(spoken).trim());
  });
}

/**
 * Main teaching surface — framed like a wall-mounted board; content scrolls inside.
 * Optional inlineChat shares the scroll surface; boardFooter anchors inside the frame.
 */
export function AIWhiteboard({
  items,
  topicTitle,
  zone,
  onLastItemComplete,
  flowCheckpointGate = null,
  flowCheckpointUi = null,
  restoreMode = false,
  staticRestoreByItemId,
  onPlaybackBeatCommitted,
  showVtseVisuals = false,
  onVisualTeachingSentenceProgress,
  timeline,
  inlineChat = null,
  itemsBeforeInlineChat,
  itemsAfterInlineChat,
  boardFooter = null,
  autoScrollEnabled = true,
  scrollFollowPanelKey = null,
}: AIWhiteboardProps) {
  void restoreMode;

  const scrollRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const stickToBottomRef = useRef(true);
  const prevFollowKeyRef = useRef("");
  const growthRafRef = useRef<number | null>(null);
  const restorePassDoneRef = useRef(false);

  const timelineBoardItems = timeline
    ? timeline.flatMap((e) => (e.kind === "board" ? e.items : []))
    : null;

  const useSplit =
    !timeline &&
    (itemsBeforeInlineChat !== undefined || itemsAfterInlineChat !== undefined);
  const beforeItems = useSplit
    ? (itemsBeforeInlineChat ?? [])
    : items;
  const afterItems = useSplit ? (itemsAfterInlineChat ?? []) : [];

  const allItemsForLast = timelineBoardItems
    ? timelineBoardItems
    : useSplit
      ? [...beforeItems, ...afterItems]
      : items;
  const lastBoardItemId =
    allItemsForLast.length > 0
      ? allItemsForLast[allItemsForLast.length - 1]?.id
      : null;

  const isStaticRestore =
    staticRestoreByItemId != null &&
    Object.keys(staticRestoreByItemId).length > 0;

  const followKey = useMemo(() => {
    const timelineKeys =
      timeline?.map((e) =>
        e.kind === "conversation"
          ? e.key
          : `board:${e.items.map((it) => it.id).join("+")}`
      ) ?? [];
    const thinkingVisible =
      timeline?.some(
        (e) =>
          e.kind === "conversation" &&
          (e.key === "stage-transition-thinking" ||
            e.key.endsWith(":thinking") ||
            e.key.includes("thinking"))
      ) ?? false;
    return buildBoardScrollFollowKey({
      timelineKeys,
      lastBoardItemId,
      thinkingVisible,
      panelKey: scrollFollowPanelKey,
    });
  }, [timeline, lastBoardItemId, scrollFollowPanelKey]);

  const scheduleScrollToBottom = (behavior: ScrollBehavior) => {
    const el = scrollRef.current;
    if (!el) return;
    if (growthRafRef.current != null) {
      cancelAnimationFrame(growthRafRef.current);
    }
    growthRafRef.current = requestAnimationFrame(() => {
      growthRafRef.current = null;
      if (!stickToBottomRef.current) return;
      scrollElementToBottom(el, behavior);
    });
  };

  const scrollLatestIntoView = () => {
    const anchor = bottomRef.current;
    if (anchor) {
      anchor.scrollIntoView({ behavior: "smooth", block: "nearest" });
      stickToBottomRef.current = true;
      return;
    }
    scheduleScrollToBottom("smooth");
  };

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const onScroll = () => {
      stickToBottomRef.current = stickAfterUserScroll(el);
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, []);

  // Restore: one settle after layout, then enable follow (no repeated jumps).
  useEffect(() => {
    if (!isStaticRestore) {
      restorePassDoneRef.current = true;
      return;
    }
    restorePassDoneRef.current = false;
    let cancelled = false;
    const id = requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        if (cancelled) return;
        const el = scrollRef.current;
        if (el) {
          scrollElementToBottom(el, "auto");
          stickToBottomRef.current = true;
        }
        restorePassDoneRef.current = true;
        prevFollowKeyRef.current = followKey;
      });
    });
    return () => {
      cancelled = true;
      cancelAnimationFrame(id);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isStaticRestore]);

  useEffect(() => {
    if (!autoScrollEnabled) return;
    if (isStaticRestore && !restorePassDoneRef.current) return;
    const prev = prevFollowKeyRef.current;
    if (
      !shouldScrollOnFollowKeyChange({
        enabled: true,
        stickToBottom: stickToBottomRef.current,
        prevKey: prev,
        nextKey: followKey,
      })
    ) {
      prevFollowKeyRef.current = followKey;
      return;
    }
    prevFollowKeyRef.current = followKey;
    scrollLatestIntoView();
  }, [followKey, autoScrollEnabled, isStaticRestore]);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const content = el.firstElementChild;
    if (!content) return;
    const ro = new ResizeObserver(() => {
      if (!autoScrollEnabled) return;
      if (isStaticRestore && !restorePassDoneRef.current) return;
      if (
        !shouldScrollOnContentGrowth({
          enabled: true,
          stickToBottom: stickToBottomRef.current,
        })
      ) {
        return;
      }
      scheduleScrollToBottom("auto");
    });
    ro.observe(content);
    return () => {
      ro.disconnect();
      if (growthRafRef.current != null) {
        cancelAnimationFrame(growthRafRef.current);
        growthRafRef.current = null;
      }
    };
  }, [autoScrollEnabled, isStaticRestore, timeline, items]);

  const renderBoard = (boardItems: BoardItem[], keyPrefix: string) => {
    if (boardItems.length === 0) return null;
    const segments = groupWhiteboardSegments(boardItems);
    return (
      <div key={keyPrefix} data-testid={`${keyPrefix}-block`}>
        <WhiteboardSegments
          segments={segments}
          lastBoardItemId={lastBoardItemId}
          staticRestoreByItemId={staticRestoreByItemId}
          onLastItemComplete={onLastItemComplete}
          flowCheckpointGate={flowCheckpointGate}
          onPlaybackBeatCommitted={onPlaybackBeatCommitted}
          showVtseVisuals={showVtseVisuals}
          onVisualTeachingSentenceProgress={onVisualTeachingSentenceProgress}
        />
      </div>
    );
  };

  const hasTimelineContent =
    timeline != null &&
    timeline.some((e) =>
      e.kind === "board" ? e.items.length > 0 : e.content != null
    );

  const emptyPlaceholder =
    !hasTimelineContent &&
    allItemsForLast.length === 0 &&
    !inlineChat ? (
      <StreamingText
        text={PLACEHOLDER}
        className={`${WHITEBOARD_TEXT_CLASS} text-slate-600 dark:text-slate-400`}
      />
    ) : null;

  const scrollBody = timeline ? (
    <>
      {timeline.map((entry, i) => {
        if (entry.kind === "board") {
          return renderBoard(entry.items, `ai-whiteboard-timeline-board-${i}`);
        }
        return (
          <div
            key={entry.key}
            className={`my-6 md:my-8 ${WHITEBOARD_CONTENT_COLUMN_CLASS}`}
            data-testid="ai-whiteboard-inline-chat-slot"
            data-timeline-episode={entry.key}
            data-whiteboard-width="column"
          >
            {entry.content}
          </div>
        );
      })}
    </>
  ) : (
    <>
      {renderBoard(beforeItems, "ai-whiteboard-board-before")}
      {inlineChat ? (
        <div
          className={`my-6 md:my-8 ${WHITEBOARD_CONTENT_COLUMN_CLASS}`}
          data-testid="ai-whiteboard-inline-chat-slot"
          data-placement="chronological-split"
          data-whiteboard-width="column"
        >
          {inlineChat}
        </div>
      ) : null}
      {renderBoard(afterItems, "ai-whiteboard-board-after")}
    </>
  );

  return (
    <section
      className="flex h-full min-h-0 w-full flex-col"
      aria-label="AI teaching whiteboard"
      data-testid="ai-whiteboard"
    >
      {/* Outer frame: dark border + depth */}
      <div
        className={[
          "relative flex h-full min-h-0 flex-col overflow-hidden rounded-xl",
          "border-[3px] border-zinc-950 bg-zinc-900",
          "p-2 md:p-2.5",
          "shadow-[0_18px_50px_-10px_rgba(0,0,0,0.5),0_6px_0_0_rgba(0,0,0,0.18),inset_0_1px_0_rgba(255,255,255,0.12)]",
        ].join(" ")}
        data-testid="ai-whiteboard-frame"
      >
        {/* Inner writing surface — one continuous canvas */}
        <div
          className={[
            "relative flex min-h-0 flex-1 flex-col overflow-hidden rounded-lg",
            "border border-black/20",
            /* Half-white: soft blend between pure white and light gray */
            "bg-[linear-gradient(180deg,#ffffff_0%,#e8eaee_100%)]",
            "shadow-[inset_0_3px_14px_rgba(0,0,0,0.08)]",
            "dark:border-white/10 dark:bg-[linear-gradient(180deg,#262626_0%,#1a1a1a_100%)]",
          ].join(" ")}
          data-testid="ai-whiteboard-surface"
        >
          {flowCheckpointUi ? (
            <FlowCheckpointOverlay
              phase={flowCheckpointUi.phase}
              event={flowCheckpointUi.event}
              clarification={flowCheckpointUi.clarification}
              continuing={flowCheckpointUi.continuing}
              continueError={flowCheckpointUi.continueError}
              onContinue={flowCheckpointUi.onContinue}
              onAskQuestion={flowCheckpointUi.onAskQuestion}
              onAskAnotherQuestion={flowCheckpointUi.onAskAnotherQuestion}
              onSubmitQuestion={flowCheckpointUi.onSubmitQuestion}
              onDismissAfterClarification={flowCheckpointUi.onDismissAfterClarification}
            />
          ) : null}
          {typeof zone === "number" ? (
            <div className="absolute left-3 top-3 z-10 md:left-4 md:top-4">
              <ZoneIndicator zone={zone} />
            </div>
          ) : null}
          <div
            className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle,_rgba(0,0,0,0.045)_1px,_transparent_1px)] bg-[length:18px_18px] opacity-60 dark:bg-[radial-gradient(circle,_rgba(255,255,255,0.05)_1px,_transparent_1px)] dark:opacity-35"
            aria-hidden
          />
          <div
            ref={scrollRef}
            className="scrollbar-hide relative min-h-0 flex-1 overflow-y-auto overflow-x-hidden scroll-smooth pl-1 pr-6 pb-5 pt-14 md:pl-2 md:pr-10 md:pb-8 md:pt-16"
            data-testid="ai-whiteboard-scroll"
          >
            <div className="w-full min-w-0">
              {topicTitle ? (
                <div className={`mb-8 text-center md:mb-10 ${WHITEBOARD_CONTENT_COLUMN_CLASS}`}>
                  <h2 className="text-2xl font-bold tracking-tight text-zinc-800 md:text-3xl lg:text-4xl dark:text-zinc-100">
                    {topicTitle}
                  </h2>
                </div>
              ) : null}
              {emptyPlaceholder ? (
                <div className={WHITEBOARD_CONTENT_COLUMN_CLASS}>{emptyPlaceholder}</div>
              ) : null}
              {scrollBody}
              <div
                ref={bottomRef}
                data-testid="ai-whiteboard-scroll-anchor"
                aria-hidden
                className="h-px w-full shrink-0"
              />
            </div>
          </div>
          {boardFooter ? (
            <div
              className="relative z-20 shrink-0 border-t border-black/10 bg-white/55 backdrop-blur-[2px] dark:border-white/10 dark:bg-zinc-900/55"
              data-testid="ai-whiteboard-footer-slot"
            >
              {boardFooter}
            </div>
          ) : null}
        </div>
      </div>
    </section>
  );
}

function WhiteboardSegments({
  segments,
  lastBoardItemId,
  staticRestoreByItemId,
  onLastItemComplete,
  flowCheckpointGate,
  onPlaybackBeatCommitted,
  showVtseVisuals = false,
  onVisualTeachingSentenceProgress,
}: {
  segments: WhiteboardSegment[];
  lastBoardItemId: string | null;
  staticRestoreByItemId?: Record<string, number>;
  onLastItemComplete?: () => void;
  flowCheckpointGate: FlowCheckpointGate | null;
  onPlaybackBeatCommitted?: (beatIndex: number) => void;
  showVtseVisuals?: boolean;
  onVisualTeachingSentenceProgress?: (progress: {
    sceneIndex: number;
    beatIndex: number;
    sentenceIndex: number;
  }) => void;
}) {
  let priorVisible = false;

  return (
    <>
      {segments.map((segment, segIndex) => {
        if (segment.kind === "story_hook_run") {
          const runItems = segment.items;
          const streamedSteps = attachStoryHookStepStreaming(
            segment.steps,
            runItems,
            {
              lastBoardItemId,
              staticRestoreByItemId,
            }
          ).map((step) => ({
            ...step,
            onStreamComplete: step.ownsCompletion
              ? onLastItemComplete
              : undefined,
          }));
          const layoutVisible = storyHookStreamHasVisibleLayout(streamedSteps);
          const showDivider = layoutVisible && priorVisible;
          if (layoutVisible) priorVisible = true;

          if (!layoutVisible) {
            // Speak-only Story Hook run: TTS drivers only — no divider / padding.
            return (
              <div
                key={`story-hook-run-${runItems[0]?.id ?? segIndex}`}
                className="sr-only"
                aria-hidden
              >
                {streamedSteps.length > 0 ? (
                  <ConceptStoryHookCard steps={streamedSteps} />
                ) : null}
              </div>
            );
          }

          return (
            <div
              key={`story-hook-run-${runItems[0]?.id ?? segIndex}`}
              className={WHITEBOARD_CONTENT_COLUMN_CLASS}
              data-whiteboard-width="column"
            >
              {showDivider ? <ResponseDivider /> : null}
              <div className="mb-4 pb-1">
                {streamedSteps.length > 0 ? (
                  <ConceptStoryHookCard steps={streamedSteps} />
                ) : null}
              </div>
            </div>
          );
        }

        if (segment.kind === "visual_teaching_scene") {
          const runItems = segment.items;
          const streamedBeats = attachVisualTeachingBeatStreaming(
            segment.beats,
            runItems,
            {
              lastBoardItemId,
              staticRestoreByItemId,
            }
          ).map((beat) => ({
            ...beat,
            onStreamComplete: beat.ownsCompletion
              ? onLastItemComplete
              : undefined,
          }));
          const showDivider = priorVisible;
          priorVisible = true;
          return (
            <div
              key={`vt-scene-${runItems[0]?.id ?? segIndex}`}
              className={WHITEBOARD_CONTENT_COLUMN_CLASS}
              data-whiteboard-width="column"
              data-vt-scene-run={streamedBeats[0]?.sceneIndex ?? 0}
              data-vt-beat-items={runItems.length}
            >
              {showDivider ? <ResponseDivider /> : null}
              <div className="mb-4 pb-1">
                {streamedBeats.length > 0 ? (
                  <ConceptVisualTeachingCard
                    beats={streamedBeats}
                    onSentencePersist={onVisualTeachingSentenceProgress}
                  />
                ) : null}
              </div>
            </div>
          );
        }

        const item = segment.item;
        const isLast = item.id === lastBoardItemId;
        const decision = resolveProductionVisualRenderer(item, {
          useInstructionBoard: true,
        });
        logProductionVisualRenderer(item.id, decision);
        // eslint-disable-next-line no-console
        console.info(
          "[VTSE] AIWhiteboard id=",
          item.id,
          "itv3_present=",
          item.instruction_timeline_v3 != null,
          "renderer=",
          decision.activeRenderer,
          "fallbackReason=",
          decision.fallbackReason
        );
        const showTimeline =
          decision.activeRenderer === "timeline_v3" &&
          decision.timeline != null;
        const itemStaticRestore = staticRestoreByItemId?.[item.id];
        const itemRestoreMode = itemStaticRestore !== undefined;
        const timelineStaticThrough =
          itemStaticRestore != null && itemStaticRestore >= 0
            ? itemStaticRestore
            : null;
        const pedagogyCard = parsePedagogyIntroCard(item.visual);
        const visualTeachingCard = parseConceptVisualTeachingCard(item.visual);
        const notesMode = item.writingMode === "notes";
        const hasBoardWrites = Boolean(
          notesMode && item.boardWrites && item.boardWrites.length
        );
        const displayText = notesMode ? (item.displayText ?? "") : undefined;
        const notesNoInk =
          notesMode && !hasBoardWrites && !String(displayText ?? "").trim();

        const wideVtseVisual =
          showTimeline &&
          showVtseVisuals &&
          timelineHasVtseVisualPackage(decision.timeline);

        const layoutVisible = Boolean(
          pedagogyCard ||
            visualTeachingCard ||
            showTimeline ||
            (!decision.suppressLegacyProse && !notesNoInk)
        );
        const showDivider = layoutVisible && priorVisible;
        if (layoutVisible) priorVisible = true;

        // Speak-only notes prose: keep TTS/completion, zero layout height.
        if (notesNoInk && !pedagogyCard && !visualTeachingCard && !showTimeline) {
          return (
            <div key={item.id} className="sr-only" aria-hidden>
              <WordSyncedStreaming
                text={item.content.trim() ? item.content : "\u00a0"}
                displayText=""
                staticMode={itemRestoreMode}
                onComplete={
                  isLast && !itemRestoreMode ? onLastItemComplete : undefined
                }
              />
            </div>
          );
        }

        return (
          <div
            key={item.id}
            className={
              wideVtseVisual ? VTSE_VISUAL_WIDE_CLASS : WHITEBOARD_CONTENT_COLUMN_CLASS
            }
            data-whiteboard-width={wideVtseVisual ? "vtse-visual" : "column"}
          >
            {showDivider ? <ResponseDivider /> : null}
            <div className="pb-1">
              {visualTeachingCard ? (
                <div className="mb-4">
                  <ConceptVisualTeachingCard
                    card={visualTeachingCard}
                    streamStaticMode={itemRestoreMode && !isLast}
                    onStreamComplete={isLast ? onLastItemComplete : undefined}
                    onSentencePersist={onVisualTeachingSentenceProgress}
                  />
                </div>
              ) : null}
              {pedagogyCard ? (
                <div className="mb-4">
                  <PedagogyIntroCard card={pedagogyCard} />
                  <WordSyncedStreaming
                    text={item.content.trim() ? item.content : "\u00a0"}
                    className="sr-only"
                    staticMode={itemRestoreMode}
                    onComplete={
                      isLast && !itemRestoreMode ? onLastItemComplete : undefined
                    }
                  />
                </div>
              ) : null}
              {showTimeline ? (
                <ProductionTimelineRuntimeView
                  timeline={decision.timeline!}
                  enabled={true}
                  plannerSource={item.planner_source ?? null}
                  cirInstructionDebug={item.cir_instruction_debug ?? null}
                  surface="whiteboard"
                  playbackStartBeatIndex={boardItemPlaybackStart(item)}
                  restoreMode={itemRestoreMode && timelineStaticThrough != null}
                  restoreStaticThroughBeatIndex={timelineStaticThrough}
                  onPlaybackBeatCommitted={
                    isLast ? onPlaybackBeatCommitted : undefined
                  }
                  showVtseVisuals={showVtseVisuals}
                  flowCheckpointGate={
                    isLast && !itemRestoreMode ? flowCheckpointGate : null
                  }
                  onInstructionComplete={
                    isLast && !itemRestoreMode ? onLastItemComplete : undefined
                  }
                />
              ) : null}
              {!decision.suppressLegacyProse &&
              !pedagogyCard &&
              !visualTeachingCard ? (
                <WordSyncedStreaming
                  text={item.content.trim() ? item.content : "\u00a0"}
                  displayText={displayText}
                  boardWrites={hasBoardWrites ? item.boardWrites : undefined}
                  className={streamTextClass}
                  staticMode={itemRestoreMode && !showTimeline}
                  onComplete={
                    isLast && !itemRestoreMode ? onLastItemComplete : undefined
                  }
                />
              ) : null}
              {decision.suppressLegacyProse &&
                !showTimeline &&
                !visualTeachingCard &&
                isLast &&
                !itemRestoreMode && (
                  <WordSyncedStreaming
                    text="\u00a0"
                    className="sr-only"
                    onComplete={onLastItemComplete}
                  />
                )}
            </div>
          </div>
        );
      })}
    </>
  );
}
