import type { AnyRecord } from "../../types";

export function asRecord(value: unknown): AnyRecord {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as AnyRecord) : {};
}

export function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

// Single source for first-non-empty-text; re-exported so existing thread imports keep working.
export { firstText } from "../../narrative";

export function formatEventTime(value: unknown): string {
  const date = new Date(String(value ?? ""));
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString();
}

export function formatUsage(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return "0";
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}k`;
  return String(Math.round(value));
}

export function percent(value: number): string {
  if (!Number.isFinite(value)) return "0%";
  return `${Math.round(Math.max(0, Math.min(1, value)) * 100)}%`;
}

export function textOrFallback(value: unknown, fallback: string): string {
  const text = String(value ?? "").trim();
  return text || fallback;
}

// De-jargon a backend exit-reason string for the (Chinese) next-step bar. The replacements must be
// Chinese — this is the fallback path for an unmapped exit_reason (RuntimeSnapshot.userFacingStateLabel),
// so English replacements would leak straight into the Chinese UI.
export function stripBackendWording(value: string): string {
  return String(value || "")
    .replace(/\bprovider route blocked\b/gi, "模型连接中断")
    .replace(/\bmodel-check\b/gi, "连接检查")
    .replace(/\bgate-status\b/gi, "诊断")
    .replace(/\bruntime_progress\b/gi, "进度")
    .replace(/\buser_progress\.jsonl\b/gi, "进度日志")
    .trim();
}
