import type { AnyRecord, OverviewPayload, RunDetailPayload } from "../../types";

export function asRecord(value: unknown): AnyRecord {
  return value && typeof value === "object" && !Array.isArray(value) ? value as AnyRecord : {};
}

export function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

export type ContextUsage = {
  usedTokens: number | null;
  windowTokens: number | null;
  ratio: number | null;
  inputTokens: number | null;
  outputTokens: number | null;
  pressure: string | null;
};

// Shared, honest read of context-window usage from the run's cost_report. All values are ESTIMATES
// the runtime records (there is no billing/pricing data), so callers must label them "est." and never
// render a monetary cost. Returns null when the run carries no usable usage numbers → render nothing.
export function readContextUsage(runDetail: RunDetailPayload | null | undefined): ContextUsage | null {
  const cost = asRecord(runDetail?.cost_report);
  if (!Object.keys(cost).length) return null;
  const num = (value: unknown): number | null => {
    const n = Number(value);
    return Number.isFinite(n) && n >= 0 ? n : null;
  };
  const usedTokens = num(cost.latest_context_estimated_tokens);
  const windowTokens = num(cost.context_window_tokens);
  let ratio = num(cost.context_window_ratio);
  if (ratio === null && usedTokens !== null && windowTokens) ratio = usedTokens / windowTokens;
  const inputTokens = num(cost.estimated_input_tokens);
  const outputTokens = num(cost.estimated_output_tokens);
  const pressure = cost.context_pressure_status ? String(cost.context_pressure_status) : null;
  // The server may redact raw token counts (they come back non-numeric); the ratio is enough to render
  // an honest pressure meter on its own. Only bail when we have neither a ratio nor any token number.
  if (ratio === null && usedTokens === null && windowTokens === null && inputTokens === null && outputTokens === null) {
    return null;
  }
  return { usedTokens, windowTokens, ratio, inputTokens, outputTokens, pressure };
}

export function runtimeProgressFromDetail(runDetail: RunDetailPayload | null): AnyRecord {
  const direct = asRecord(runDetail?.runtime_progress);
  if (Object.keys(direct).length) return direct;
  const finalSummary = asRecord(runDetail?.final_report_summary);
  const loopSummary = asRecord(runDetail?.run_loop_summary);
  return asRecord(finalSummary.runtime_progress ?? loopSummary.runtime_progress);
}

export function latestRoute(runDetail: RunDetailPayload | null): AnyRecord | null {
  const routeArtifact = asRecord(runDetail?.model_route_timeline);
  const finalSummary = asRecord(runDetail?.final_report_summary);
  const timeline = (
    Array.isArray(routeArtifact.timeline)
      ? routeArtifact.timeline
      : Array.isArray(routeArtifact.route_timeline)
        ? routeArtifact.route_timeline
        : Array.isArray(finalSummary.model_route_timeline)
          ? finalSummary.model_route_timeline
          : []
  ) as AnyRecord[];
  return timeline.length ? timeline.at(-1) ?? null : null;
}

export function metricTone(value: string): string {
  if (/ready|completed|succeeded|pass|healthy/i.test(value)) return "good";
  if (/blocked|failed|missing|error/i.test(value)) return "bad";
  return "warn";
}

export function formatUsage(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return "0";
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}k`;
  return String(Math.round(value));
}

export function contextSectionLabel(value: string): string {
  const normalized = value.toLowerCase();
  if (normalized.includes("message") || normalized.includes("conversation")) return "消息";
  if (normalized.includes("tool") || normalized.includes("shell")) return "工具输出";
  if (normalized.includes("skill")) return "技能";
  if (normalized.includes("system")) return "系统";
  if (normalized.includes("prompt") || normalized.includes("instruction")) return "项目规则";
  if (normalized.includes("memory") || normalized.includes("durable")) return "记忆";
  if (normalized.includes("file") || normalized.includes("context")) return "文件";
  return value.replace(/[_-]+/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

export function rollingValidationFromOverview(overview: OverviewPayload | null): AnyRecord {
  const gateStatus = asRecord(overview?.gateStatus);
  return asRecord(overview?.v0_2_rolling_validation ?? gateStatus.v0_2_rolling_validation);
}

export function workerCountFromTree(workerTree: AnyRecord): number {
  const direct = Number(workerTree.total_workers);
  if (Number.isFinite(direct)) return direct;
  const roots = asArray(workerTree.roots) as AnyRecord[];
  const countNodes = (items: AnyRecord[]): number =>
    items.reduce((total, item) => total + 1 + countNodes(asArray(item.children) as AnyRecord[]), 0);
  return countNodes(roots);
}

