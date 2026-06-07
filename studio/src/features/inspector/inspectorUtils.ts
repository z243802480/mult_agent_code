import type { AnyRecord, OverviewPayload, RunDetailPayload } from "../../types";

export function asRecord(value: unknown): AnyRecord {
  return value && typeof value === "object" && !Array.isArray(value) ? value as AnyRecord : {};
}

export function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
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
  if (normalized.includes("message") || normalized.includes("conversation")) return "Messages";
  if (normalized.includes("tool") || normalized.includes("shell")) return "Tool output";
  if (normalized.includes("skill")) return "Skills";
  if (normalized.includes("system")) return "System";
  if (normalized.includes("prompt") || normalized.includes("instruction")) return "Project rules";
  if (normalized.includes("memory") || normalized.includes("durable")) return "Memory";
  if (normalized.includes("file") || normalized.includes("context")) return "Files";
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

