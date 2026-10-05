import type { RuntimeMetrics, RuntimeTelemetry } from "@/lib/instruction-timeline-v3/types";

export class RuntimeTelemetryCollector {
  private readonly data: RuntimeTelemetry = {
    operation_latency_ms: [],
    integrity_check_ms: [],
    replay_verification_ms: [],
    rollback_count: 0,
    scheduler_ops_per_second: [],
    journal_size_samples: [],
    checkpoint_count_samples: [],
  };

  public recordOperationLatency(ms: number): void {
    this.data.operation_latency_ms.push(ms);
  }
  public recordIntegrityTiming(ms: number): void {
    this.data.integrity_check_ms.push(ms);
  }
  public recordReplayTiming(ms: number): void {
    this.data.replay_verification_ms.push(ms);
  }
  public recordRollback(): void {
    this.data.rollback_count += 1;
  }
  public recordSchedulerThroughput(opsPerSecond: number): void {
    this.data.scheduler_ops_per_second.push(opsPerSecond);
  }
  public recordJournalSize(size: number): void {
    this.data.journal_size_samples.push(size);
  }
  public recordCheckpointCount(size: number): void {
    this.data.checkpoint_count_samples.push(size);
  }

  public metrics(): RuntimeMetrics {
    return {
      operation_count: this.data.operation_latency_ms.length,
      integrity_check_count: this.data.integrity_check_ms.length,
      replay_verification_count: this.data.replay_verification_ms.length,
      rollback_count: this.data.rollback_count,
      latest_journal_size: this.data.journal_size_samples.at(-1) ?? 0,
      latest_checkpoint_count: this.data.checkpoint_count_samples.at(-1) ?? 0,
    };
  }
}
