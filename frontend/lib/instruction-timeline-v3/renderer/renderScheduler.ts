import type { RuntimeClock } from "@/lib/instruction-timeline-v3/clock";

export interface RenderScheduleItem<T> {
  sequence: number;
  payload: T;
  enqueued_at_ms: number;
}

export class RenderScheduler<T> {
  private readonly queue: Array<RenderScheduleItem<T>> = [];
  private readonly clock: RuntimeClock;
  private seq = 0;

  public constructor(clock: RuntimeClock) {
    this.clock = clock;
  }

  public enqueue(payload: T): RenderScheduleItem<T> {
    const item: RenderScheduleItem<T> = {
      sequence: this.seq++,
      payload,
      enqueued_at_ms: this.clock.nowMs(),
    };
    this.queue.push(item);
    this.queue.sort((a, b) => a.sequence - b.sequence);
    return item;
  }

  public flush(maxItems = Number.MAX_SAFE_INTEGER): RenderScheduleItem<T>[] {
    const count = Math.min(maxItems, this.queue.length);
    return this.queue.splice(0, count);
  }

  public size(): number {
    return this.queue.length;
  }
}
