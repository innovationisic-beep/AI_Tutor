"use client";

import { useMemo, useState } from "react";

import { MinimalTimelineRuntime } from "@/lib/instruction-timeline-v3/runtime";
import { RuntimeEventBus } from "@/lib/instruction-timeline-v3/eventBus";
import { SimulatedRuntimeClock } from "@/lib/instruction-timeline-v3/clock";
import { RuntimeRendererBridge } from "@/lib/instruction-timeline-v3/renderer/runtimeRendererBridge";
import type { InstructionTimelineV3 } from "@/lib/instruction-timeline-v3/types";
import { MinimalDeterministicRenderer } from "@/components/ai/timeline-v3/MinimalDeterministicRenderer";
import { defaultViewport } from "@/lib/instruction-timeline-v3/renderer/viewport";
import type { RenderProjection } from "@/lib/instruction-timeline-v3/renderer/projectionTypes";

export function LiveRuntimeDemo({
  timeline,
  enabled = false,
}: {
  timeline: InstructionTimelineV3;
  enabled?: boolean;
}) {
  const [latestByLayer, setLatestByLayer] = useState<Record<string, RenderProjection[]>>({});
  const [streamVersion, setStreamVersion] = useState<number>(-1);

  const runtime = useMemo(() => new MinimalTimelineRuntime(), []);

  const runDemo = () => {
    if (!enabled) return;
    const clock = new SimulatedRuntimeClock(Date.now());
    const eventBus = new RuntimeEventBus();
    const bridge = new RuntimeRendererBridge({
      clock,
      eventBus,
      viewport: defaultViewport(960, 540),
    });

    runtime.run(timeline, {
      eventBus,
      onOperationCommitted(payload) {
        const entry = bridge.onCommittedOperation({
          operation_id: payload.operation_id,
          scene: payload.scene,
          at: payload.at,
        });
        const replayed = bridge.replayProjectionStream(entry.version, entry.version, payload.at);
        const snapshot = replayed[0]?.snapshot;
        if (snapshot) {
          const byLayer: Record<string, RenderProjection[]> = {};
          snapshot.projections.forEach((p) => {
            byLayer[p.layer] = byLayer[p.layer] ?? [];
            byLayer[p.layer].push(p);
          });
          setLatestByLayer(byLayer);
          setStreamVersion(entry.version);
        }
      },
    });
  };

  if (!enabled) return null;

  return (
    <div className="space-y-3 rounded-lg border border-zinc-200/70 p-3 dark:border-zinc-800">
      <button
        type="button"
        onClick={runDemo}
        className="rounded bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-500"
      >
        Run Live Runtime Demo
      </button>
      <p className="text-xs text-zinc-500 dark:text-zinc-400">Stream version: {streamVersion}</p>
      <MinimalDeterministicRenderer
        projectionsByLayer={latestByLayer}
        width={960}
        height={540}
        debug
      />
    </div>
  );
}
