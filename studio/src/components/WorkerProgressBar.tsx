import React from "react";
import type { AnyRecord } from "../types";

function asRecord(value: unknown): AnyRecord {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as AnyRecord) : {};
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

export function WorkerProgressBar({ data, compact = false }: { data: AnyRecord; compact?: boolean }) {
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
      ? `${schedulingMode} (preview)`
      : schedulingMode
    : "";

  // Main thread (compact): show only a friendly aggregate, hide orchestration
  // internals (scheduling_mode/(preview)/fake_path, worker_invocation_id list,
  // promotion_hint). Inspector (non-compact) keeps the raw detail below.
  if (compact) {
    return (
      <div className="workerProgressBar" aria-label="Background worker progress">
        <div className="workerProgressTrack">
          <span className="workerProgressFill success" style={{ width: `${(successful / total) * 100}%` }} />
          <span className="workerProgressFill failed" style={{ width: `${(failed / total) * 100}%` }} />
          <span className="workerProgressFill running" style={{ width: `${(running / total) * 100}%` }} />
        </div>
        <div className="workerProgressMeta">
          <span>Working on {total} thing{total === 1 ? "" : "s"}… {successful} done</span>
          {failed > 0 && <span className="workerProgressWarn">{failed} need attention</span>}
        </div>
      </div>
    );
  }

  return (
    <div className="workerProgressBar" aria-label="Background worker progress">
      {schedulingLabel && (
        <div className="workerSchedulingBadge" data-fake-path={fakePath === true ? "true" : "false"}>
          {schedulingLabel}
        </div>
      )}
      <div className="workerProgressTrack">
        <span className="workerProgressFill success" style={{ width: `${(successful / total) * 100}%` }} />
        <span className="workerProgressFill failed" style={{ width: `${(failed / total) * 100}%` }} />
        <span className="workerProgressFill running" style={{ width: `${(running / total) * 100}%` }} />
      </div>
      <div className="workerProgressMeta">
        <span>{successful}/{total} done</span>
        {failed > 0 && <span className="workerProgressWarn">{failed} need attention</span>}
        <span>{percent}%</span>
      </div>
      {workers.length > 0 && (
        <ul className="workerProgressList">
          {workers.slice(0, 6).map((worker, index) => {
            const id = String(worker.worker_invocation_id ?? worker.worker_id ?? `worker-${index + 1}`);
            const status = String(worker.result_status ?? worker.status ?? "unknown");
            const mode = String(worker.scheduling_mode ?? "").trim();
            return (
              <li key={id}>
                <span>{id}</span>
                <span>{String(worker.task_id ?? "task")}</span>
                {mode && <span>{mode}</span>}
                <span>{status}</span>
              </li>
            );
          })}
        </ul>
      )}
      {promotionHint && <p className="workerPromotionHint">{promotionHint}</p>}
    </div>
  );
}
