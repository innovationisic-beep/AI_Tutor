import type { RuntimeClockMode } from "@/lib/instruction-timeline-v3/types";

export interface RuntimeClock {
  readonly mode: RuntimeClockMode;
  nowMs(): number;
  nowIso(): string;
  advanceByMs(ms: number): void;
}

export class RealRuntimeClock implements RuntimeClock {
  public readonly mode: RuntimeClockMode = "real";

  public nowMs(): number {
    return Date.now();
  }

  public nowIso(): string {
    return new Date(this.nowMs()).toISOString();
  }

  public advanceByMs(_ms: number): void {}
}

export class SimulatedRuntimeClock implements RuntimeClock {
  public readonly mode: RuntimeClockMode = "simulated";
  private now: number;

  public constructor(startMs = 0) {
    this.now = startMs;
  }

  public nowMs(): number {
    return this.now;
  }

  public nowIso(): string {
    return new Date(this.now).toISOString();
  }

  public advanceByMs(ms: number): void {
    this.now += Math.max(0, ms);
  }
}
