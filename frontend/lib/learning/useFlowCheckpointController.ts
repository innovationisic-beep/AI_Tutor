"use client";

import { useCallback, useMemo, useRef, useState } from "react";

import type { SendMessageResult } from "@/lib/api";
import { speakUtteranceWithHooks } from "@/lib/voice";
import {
  logFlowCheckpoint,
  pauseTimelineSpeech,
  type FlowCheckpointEvent,
  type FlowCheckpointGate,
} from "@/lib/learning/flowCheckpointOrchestrator";
import { isFlowCheckpointContinueAck, acceptedCheckpointClarification } from "@/lib/learning/flowCheckpointContinue";

export type FlowCheckpointUiPhase =
  | "idle"
  | "open"
  | "question_input"
  | "clarifying"
  | "clarification_done";

export const FLOW_CHECKPOINT_CLOSING = "Hope that clears your confusion.";

export type FlowCheckpointUi = {
  phase: FlowCheckpointUiPhase;
  event: FlowCheckpointEvent | null;
  clarification: string | null;
  /** True while awaiting backend continue ack before resume. */
  continuing: boolean;
  /** Shown when continue fails; Continue remains retryable. */
  continueError: string | null;
  isActive: boolean;
  onContinue: () => void;
  onAskQuestion: () => void;
  onAskAnotherQuestion: () => void;
  onSubmitQuestion: (text: string) => void;
  onDismissAfterClarification: () => void;
};

type SendMessageFn = (
  sessionId: string,
  message: string,
  options?: { silent?: boolean; omitFromMessages?: boolean },
) => Promise<SendMessageResult | undefined>;

export function splitClarificationText(full: string): {
  body: string;
  closing: string | null;
} {
  const text = full.trim();
  if (!text) return { body: "", closing: null };
  const idx = text.lastIndexOf(FLOW_CHECKPOINT_CLOSING);
  if (idx >= 0) {
    const body = text.slice(0, idx).trim();
    return { body, closing: FLOW_CHECKPOINT_CLOSING };
  }
  return { body: text, closing: null };
}

function clarificationFromResult(result: SendMessageResult | undefined): string | null {
  return acceptedCheckpointClarification(result?.tutor);
}

export function useFlowCheckpointController(options: {
  sessionId: string | null;
  sendMessage: SendMessageFn;
  /** Persist VTSE beat index when a flow checkpoint pauses playback. */
  onBeatCheckpoint?: (beatIndex: number) => void;
  /** Active VTSE timeline id so a late continue cannot clear a newer attempt. */
  getTimelineId?: () => string | undefined;
}): { gate: FlowCheckpointGate; ui: FlowCheckpointUi } {
  const { sessionId, sendMessage, onBeatCheckpoint, getTimelineId } = options;

  const [phase, setPhase] = useState<FlowCheckpointUiPhase>("idle");
  const [event, setEvent] = useState<FlowCheckpointEvent | null>(null);
  const [clarification, setClarification] = useState<string | null>(null);
  const [continuing, setContinuing] = useState(false);
  const [continueError, setContinueError] = useState<string | null>(null);
  const resolveGateRef = useRef<(() => void) | null>(null);
  const continueInFlightRef = useRef(false);
  const pauseReadyRef = useRef<Promise<void>>(Promise.resolve());

  const resumeTimeline = useCallback((reason: "continue" | "clarification") => {
    setPhase("idle");
    setEvent(null);
    setClarification(null);
    setContinuing(false);
    setContinueError(null);
    continueInFlightRef.current = false;
    resolveGateRef.current?.();
    resolveGateRef.current = null;
    logFlowCheckpoint("FLOW_CHECKPOINT_RESUME", { reason });
  }, []);

  const requestContinueAndResume = useCallback(
    async (reason: "continue" | "clarification") => {
      if (continueInFlightRef.current) return;
      continueInFlightRef.current = true;
      setContinueError(null);
      setContinuing(true);
      logFlowCheckpoint("FLOW_CHECKPOINT_CONTINUE", {
        stepLabels: event?.stepLabels,
        afterClarification: reason === "clarification",
      });

      if (!sessionId) {
        continueInFlightRef.current = false;
        setContinuing(false);
        setContinueError("Session unavailable. Try Continue again.");
        return;
      }

      try {
        const tid = getTimelineId?.()?.trim();
        const action = tid
          ? `__action:flow_checkpoint_continue|${tid}`
          : "__action:flow_checkpoint_continue";
        const result = await sendMessage(sessionId, action, { silent: true });
        if (!isFlowCheckpointContinueAck(result?.tutor)) {
          continueInFlightRef.current = false;
          setContinuing(false);
          setContinueError(
            "Could not clear the checkpoint. Tap Continue to retry.",
          );
          logFlowCheckpoint("FLOW_CHECKPOINT_CONTINUE_REJECTED", {
            tutorType: result?.tutor?.type ?? null,
          });
          return;
        }
        resumeTimeline(reason);
      } catch (err) {
        continueInFlightRef.current = false;
        setContinuing(false);
        setContinueError(
          err instanceof Error
            ? err.message
            : "Could not clear the checkpoint. Tap Continue to retry.",
        );
        logFlowCheckpoint("FLOW_CHECKPOINT_CONTINUE_FAILED", {
          error: err instanceof Error ? err.message : String(err),
        });
      }
    },
    [event?.stepLabels, getTimelineId, resumeTimeline, sendMessage, sessionId],
  );

  const syncPauseToServer = useCallback(
    (ev: FlowCheckpointEvent) => {
      if (!sessionId) {
        pauseReadyRef.current = Promise.resolve();
        return;
      }
      const tid = getTimelineId?.()?.trim() || "";
      const payload = JSON.stringify({
        labels: ev.stepLabels,
        timeline_id: tid,
        completed_node_count: ev.completedNodeCount,
      });
      const action = `__action:flow_checkpoint_pause|${payload}`;
      const ready = sendMessage(sessionId, action, { silent: true })
        .then(() => undefined)
        .catch(() => undefined);
      pauseReadyRef.current = ready;
      void ready;
    },
    [getTimelineId, sessionId, sendMessage],
  );

  const gate = useMemo((): FlowCheckpointGate => {
    return {
      async onFlowNodeCompleted(ev: FlowCheckpointEvent) {
        logFlowCheckpoint("FLOW_CHECKPOINT_TRIGGERED", {
          completedNodeCount: ev.completedNodeCount,
          checkpointIndex: ev.checkpointIndex,
          beatId: ev.beatId,
        });
        logFlowCheckpoint("FLOW_CHECKPOINT_STEP_LABELS", { stepLabels: ev.stepLabels });
        pauseTimelineSpeech();
        syncPauseToServer(ev);
        onBeatCheckpoint?.(Math.max(0, ev.resumeAfterBeatIndex - 1));
        await new Promise<void>((resolve) => {
          resolveGateRef.current = resolve;
          setEvent(ev);
          setPhase("open");
          setContinuing(false);
          setContinueError(null);
          continueInFlightRef.current = false;
          logFlowCheckpoint("FLOW_CHECKPOINT_PAUSED", {
            resumeAfterBeatIndex: ev.resumeAfterBeatIndex,
          });
        });
      },
    };
  }, [syncPauseToServer, onBeatCheckpoint]);

  const onContinue = useCallback(() => {
    void requestContinueAndResume("continue");
  }, [requestContinueAndResume]);

  const onAskQuestion = useCallback(() => {
    if (continuing) return;
    void pauseReadyRef.current.then(() => {
      setPhase("question_input");
    });
  }, [continuing]);

  const onAskAnotherQuestion = useCallback(() => {
    if (continuing) return;
    setPhase("question_input");
  }, [continuing]);

  const onSubmitQuestion = useCallback(
    async (text: string) => {
      const q = text.trim();
      if (!q || !sessionId || continuing) return;
      logFlowCheckpoint("FLOW_CHECKPOINT_QUESTION", { question: q });
      setClarification(null);
      setContinueError(null);
      setPhase("clarifying");
      try {
        await pauseReadyRef.current;
        const tid = getTimelineId?.()?.trim() || "";
        const payload = JSON.stringify({
          timeline_id: tid,
          completed_node_count: event?.completedNodeCount,
          text: q,
        });
        const result = await sendMessage(
          sessionId,
          `__action:flow_checkpoint_question|${payload}`,
          {
            silent: true,
            omitFromMessages: true,
          },
        );
        const msg = clarificationFromResult(result);
        if (!msg) {
          setPhase("question_input");
          setContinueError(
            "This checkpoint is no longer open. Continue when you are ready.",
          );
          return;
        }
        setClarification(msg);
        setPhase("clarification_done");
        logFlowCheckpoint("FLOW_CHECKPOINT_CLARIFICATION_SENT", { length: msg.length });
        void speakUtteranceWithHooks(msg, {});
      } catch {
        setPhase("question_input");
        setContinueError(
          "Could not send that question. Try again, or continue.",
        );
      }
    },
    [continuing, event?.completedNodeCount, getTimelineId, sendMessage, sessionId],
  );

  const onDismissAfterClarification = useCallback(() => {
    void requestContinueAndResume("clarification");
  }, [requestContinueAndResume]);

  const ui: FlowCheckpointUi = {
    phase,
    event,
    clarification,
    continuing,
    continueError,
    isActive: phase !== "idle",
    onContinue,
    onAskQuestion,
    onAskAnotherQuestion,
    onSubmitQuestion,
    onDismissAfterClarification,
  };

  return { gate, ui };
}
