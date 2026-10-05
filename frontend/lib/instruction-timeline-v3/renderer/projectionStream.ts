import type { RuntimeEventBus } from "@/lib/instruction-timeline-v3/eventBus";
import type { ProjectionDiff, ProjectionSnapshot } from "@/lib/instruction-timeline-v3/renderer/projectionTypes";

export interface ProjectionStreamEntry {
  version: number;
  at: string;
  snapshot: ProjectionSnapshot;
  diff: ProjectionDiff;
  operation_id?: string;
}

export class ProjectionStream {
  private readonly entries: ProjectionStreamEntry[] = [];
  private readonly eventBus?: RuntimeEventBus;

  public constructor(eventBus?: RuntimeEventBus) {
    this.eventBus = eventBus;
  }

  public append(entry: Omit<ProjectionStreamEntry, "version">): ProjectionStreamEntry {
    const next: ProjectionStreamEntry = {
      ...entry,
      version: this.entries.length,
    };
    this.entries.push(next);
    this.eventBus?.emit({
      type: "projection_snapshot_created",
      stream_version: next.version,
      projection_hash: next.snapshot.projection_hash,
      at: next.at,
    });
    this.eventBus?.emit({
      type: "projection_diff_applied",
      stream_version: next.version,
      at: next.at,
    });
    return next;
  }

  public latest(): ProjectionStreamEntry | null {
    return this.entries.at(-1) ?? null;
  }

  public all(): ProjectionStreamEntry[] {
    return [...this.entries];
  }

  public at(version: number): ProjectionStreamEntry | undefined {
    return this.entries.find((e) => e.version === version);
  }

  public replay(fromVersion: number, toVersion: number, at: string): ProjectionStreamEntry[] {
    const result = this.entries.filter((e) => e.version >= fromVersion && e.version <= toVersion);
    this.eventBus?.emit({
      type: "projection_stream_replayed",
      from_version: fromVersion,
      to_version: toVersion,
      at,
    });
    return result;
  }
}
