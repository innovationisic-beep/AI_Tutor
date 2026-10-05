import type { RuntimeEventBus } from "@/lib/instruction-timeline-v3/eventBus";
import type { RuntimeClock } from "@/lib/instruction-timeline-v3/clock";
import type { SceneStoreSnapshot } from "@/lib/instruction-timeline-v3/types";
import { SceneProjectionEngine } from "@/lib/instruction-timeline-v3/renderer/projection";
import { MinimalRendererRuntime, type RendererFrame } from "@/lib/instruction-timeline-v3/renderer/rendererRuntime";
import { ProjectionStream, type ProjectionStreamEntry } from "@/lib/instruction-timeline-v3/renderer/projectionStream";
import { RenderScheduler } from "@/lib/instruction-timeline-v3/renderer/renderScheduler";
import { ProjectionHistory } from "@/lib/instruction-timeline-v3/renderer/projectionHistory";
import { buildTransitionStateMap } from "@/lib/instruction-timeline-v3/renderer/transitionModel";
import type { ViewportState } from "@/lib/instruction-timeline-v3/renderer/projectionTypes";

const v3DebugEnabled = process.env.NEXT_PUBLIC_V3_DEBUG === "1";

export class RuntimeRendererBridge {
  private readonly rendererRuntime: MinimalRendererRuntime;
  private readonly stream: ProjectionStream;
  private readonly scheduler: RenderScheduler<{ frame: RendererFrame; operation_id: string }>;
  private readonly history = new ProjectionHistory();
  private readonly eventBus?: RuntimeEventBus;

  public constructor(params: {
    clock: RuntimeClock;
    viewport?: ViewportState;
    eventBus?: RuntimeEventBus;
  }) {
    this.eventBus = params.eventBus;
    const projectionEngine = new SceneProjectionEngine({ eventBus: params.eventBus });
    this.rendererRuntime = new MinimalRendererRuntime({
      viewport: params.viewport,
      projectionEngine,
      eventBus: params.eventBus,
    });
    this.stream = new ProjectionStream(params.eventBus);
    this.scheduler = new RenderScheduler(params.clock);
  }

  public onCommittedOperation(payload: {
    operation_id: string;
    scene: SceneStoreSnapshot;
    at: string;
  }): ProjectionStreamEntry {
    const frame = this.rendererRuntime.render(payload.scene, payload.at);
    this.scheduler.enqueue({ frame, operation_id: payload.operation_id });
    const queuedBeforeFlush = this.scheduler.size();
    const [flushed] = this.scheduler.flush(1);
    if (v3DebugEnabled) {
      // eslint-disable-next-line no-console
      console.info(
        "[V3_DEBUG] render_scheduler_flush",
        JSON.stringify({
          queued_before_flush: queuedBeforeFlush,
          flushed: Boolean(flushed),
          operation_id: payload.operation_id,
        }),
      );
    }
    const current = flushed?.payload.frame.snapshot.projections ?? frame.snapshot.projections;
    const transitionMap = buildTransitionStateMap(frame.diff, current);
    const streamEntry = this.stream.append({
      at: payload.at,
      snapshot: frame.snapshot,
      diff: frame.diff,
      operation_id: payload.operation_id,
    });
    this.history.append(payload.operation_id, frame.snapshot);
    if (transitionMap && Object.keys(transitionMap).length > 0) {
      this.eventBus?.emit({
        type: "render_layer_updated",
        layer: "debug",
        count: Object.keys(transitionMap).length,
        at: payload.at,
      });
    }
    this.eventBus?.emit({
      type: "projection_stream_checkpointed",
      stream_version: streamEntry.version,
      at: payload.at,
    });
    return streamEntry;
  }

  public replayProjectionStream(fromVersion: number, toVersion: number, at: string): ProjectionStreamEntry[] {
    return this.stream.replay(fromVersion, toVersion, at);
  }

  public getProjectionHistory(): ProjectionHistory {
    return this.history;
  }
}
