import React from "react";
import type { AnyRecord } from "../types";
import { statusLabel } from "./Shared";

// Scheduling mode of a delegated worker. Backend keeps these English; the Chinese UI localizes them.
const SCHEDULING_MODE_LABELS: Record<string, string> = {
  parallel: "并行",
  concurrent: "并发",
  sequential: "串行",
  serial: "串行",
  isolated: "隔离",
};

export function schedulingModeLabel(mode: string): string {
  const value = mode.trim();
  if (!value) return "";
  return SCHEDULING_MODE_LABELS[value] ?? value;
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

export function WorkerProgressBar({
  data,
  compact = false,
}: {
  data: AnyRecord;
  compact?: boolean;
}) {
  const total = Number(data.total ?? 0);
  if (!total) return null;
  const successful = Number(data.successful ?? 0);
  const failed = Number(data.failed ?? 0);
  const running = Math.max(0, total - successful - failed);
  const percent = Number(data.progress_percent ?? Math.round((successful / total) * 100));
  const promotionHint = String(data.promotion_hint ?? "").trim();
  const schedulingMode = String(data.scheduling_mode ?? "").trim();
  const fakePath = data.fake_path;
  const workers = asArray(data.workers) as AnyRecord[];

  const schedulingLabel = schedulingMode
    ? fakePath === true
      ? `${schedulingMode}（预览）`
      : schedulingMode
    : "";

  // Main thread (compact): show only a friendly aggregate, hide orchestration
  // internals (scheduling_mode/(preview)/fake_path, worker_invocation_id list,
  // promotion_hint). Inspector (non-compact) keeps the raw detail below.
  if (compact) {
    return (
      <div className="workerProgressBar" aria-label="后台任务进度">
        <div className="workerProgressTrack">
          <span
            className="workerProgressFill success"
            style={{ width: `${(successful / total) * 100}%` }}
          />
          <span
            className="workerProgressFill failed"
            style={{ width: `${(failed / total) * 100}%` }}
          />
          <span
            className="workerProgressFill running"
            style={{ width: `${(running / total) * 100}%` }}
          />
        </div>
        <div className="workerProgressMeta">
          <span>
            正在处理 {total} 项…已完成 {successful} 项
          </span>
          {failed > 0 && <span className="workerProgressWarn">{failed} 项需要关注</span>}
        </div>
      </div>
    );
  }

  return (
    <div className="workerProgressBar" aria-label="后台任务进度">
      {schedulingLabel && (
        <div
          className="workerSchedulingBadge"
          data-fake-path={fakePath === true ? "true" : "false"}
        >
          {schedulingLabel}
        </div>
      )}
      <div className="workerProgressTrack">
        <span
          className="workerProgressFill success"
          style={{ width: `${(successful / total) * 100}%` }}
        />
        <span
          className="workerProgressFill failed"
          style={{ width: `${(failed / total) * 100}%` }}
        />
        <span
          className="workerProgressFill running"
          style={{ width: `${(running / total) * 100}%` }}
        />
      </div>
      <div className="workerProgressMeta">
        <span>
          {successful}/{total} 已完成
        </span>
        {failed > 0 && <span className="workerProgressWarn">{failed} 项需要关注</span>}
        <span>{percent}%</span>
      </div>
      {workers.length > 0 && (
        <ul className="workerProgressList">
          {workers.slice(0, 6).map((worker, index) => {
            const id = String(
              worker.worker_invocation_id ?? worker.worker_id ?? `worker-${index + 1}`,
            );
            const status = String(worker.result_status ?? worker.status ?? "unknown");
            const mode = schedulingModeLabel(String(worker.scheduling_mode ?? ""));
            return (
              <li key={id}>
                <span>{id}</span>
                <span>{String(worker.task_id ?? "任务")}</span>
                {mode && <span>{mode}</span>}
                <span>{statusLabel(status)}</span>
              </li>
            );
          })}
        </ul>
      )}
      {promotionHint && <p className="workerPromotionHint">{promotionHint}</p>}
    </div>
  );
}
