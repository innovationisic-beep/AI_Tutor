import type { RuntimeEvent } from "@/lib/instruction-timeline-v3/types";

type Listener = (event: RuntimeEvent) => void;

export class RuntimeEventBus {
  private readonly events: RuntimeEvent[] = [];
  private readonly listeners = new Set<Listener>();
  private sequence = 0;

  public emit(event: RuntimeEvent): void {
    const stamped = {
      ...event,
      at: event.at ?? new Date().toISOString(),
      sequence: this.sequence++,
    } as RuntimeEvent & { sequence: number };
    this.events.push(stamped);
    this.listeners.forEach((listener) => listener(stamped));
  }

  public subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }

  public getEvents(): RuntimeEvent[] {
    return [...this.events];
  }
}
