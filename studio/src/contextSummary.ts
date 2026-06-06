import type { AnyRecord, RunDetailPayload } from "./types";

export type ContextSection = {
  id: string;
  label: string;
  value: number;
  ratio: number;
};

export type ContextWindowSummary = {
  ratio: number;
  used: number;
  capacity: number;
  status: string;
  sections: ContextSection[];
};

export function contextSectionLabel(value: string): string {
  const normalized = value.toLowerCase();
  if (normalized.includes("mcp")) return "MCP";
  if (normalized.includes("message") || normalized.includes("conversation")) return "Messages";
  if (normalized.includes("tool") || normalized.includes("shell")) return "Tools";
  if (normalized.includes("skill")) return "Skills";
  if (normalized.includes("system")) return "System";
  if (normalized.includes("prompt") || normalized.includes("instruction")) return "Project rules";
  if (normalized.includes("memory") || normalized.includes("durable")) return "Memory";
  if (normalized.includes("file") || normalized.includes("context")) return "Files";
  return value.replace(/[_-]+/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

function asRecord(value: unknown): AnyRecord {
  return value && typeof value === "object" ? (value as AnyRecord) : {};
}

export function contextWindowSummary(runDetail: RunDetailPayload | null): ContextWindowSummary | null {
  const cost = asRecord(runDetail?.cost_report);
  const rawUsed = Number(cost.latest_context_estimated_tokens ?? cost.max_context_estimated_tokens ?? 0);
  const rawCapacity = Number(cost.context_window_tokens ?? 0);
  const rawRatio = Number(cost.context_window_ratio ?? (rawCapacity > 0 ? rawUsed / rawCapacity : 0));
  const rawSections = asRecord(cost.latest_context_sections ?? cost.max_context_sections);
  const sectionEntries = Object.entries(rawSections)
    .map(([id, value]) => ({ id, label: contextSectionLabel(id), value: Number(value ?? 0) }))
    .filter((item) => Number.isFinite(item.value) && item.value > 0)
    .sort((a, b) => b.value - a.value);
  const total = sectionEntries.reduce((sum, item) => sum + item.value, 0);
  const used = rawUsed || total;
  const ratio = Number.isFinite(rawRatio) ? rawRatio : 0;
  const capacity = rawCapacity || (used > 0 && ratio > 0 ? Math.round(used / ratio) : 0);
  const sections = sectionEntries.map((item) => ({
    ...item,
    ratio: total > 0 ? item.value / total : 0,
  }));
  if (!used && !capacity && !sections.length) return null;
  return {
    ratio: Number.isFinite(ratio) ? ratio : 0,
    used: Number.isFinite(used) ? used : 0,
    capacity: Number.isFinite(capacity) ? capacity : 0,
    status: String(cost.context_pressure_status ?? cost.status ?? ""),
    sections,
  };
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

export function contextHealth(ratio: number): "good" | "warn" | "bad" {
  if (ratio >= 0.9) return "bad";
  if (ratio >= 0.75) return "warn";
  return "good";
}
