import type { ProjectionSnapshot } from "@/lib/instruction-timeline-v3/renderer/projectionTypes";

export interface ProjectionHistoryEntry {
  index: number;
  operation_id: string;
  snapshot: ProjectionSnapshot;
}

export class ProjectionHistory {
  private entries: ProjectionHistoryEntry[] = [];

  public append(operationId: string, snapshot: ProjectionSnapshot): ProjectionHistoryEntry {
    const entry: ProjectionHistoryEntry = {
      index: this.entries.length,
      operation_id: operationId,
      snapshot,
    };
    this.entries = [...this.entries, entry];
    return entry;
  }

  public all(): ProjectionHistoryEntry[] {
    return [...this.entries];
  }

  public byOperation(operationId: string): ProjectionHistoryEntry | undefined {
    return this.entries.find((e) => e.operation_id === operationId);
  }
}
