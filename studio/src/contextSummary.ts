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
  if (normalized.includes("message") || normalized.includes("conversation")) return "消息";
  if (normalized.includes("tool") || normalized.includes("shell")) return "工具";
  if (normalized.includes("skill")) return "技能";
  if (normalized.includes("system")) return "系统";
  if (normalized.includes("prompt") || normalized.includes("instruction")) return "项目规则";
  if (normalized.includes("memory") || normalized.includes("durable")) return "记忆";
  if (normalized.includes("file") || normalized.includes("context")) return "文件";
  return value.replace(/[_-]+/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

function asRecord(value: unknown): AnyRecord {
  return value && typeof value === "object" ? (value as AnyRecord) : {};
}

export function contextWindowSummary(
  runDetail: RunDetailPayload | null,
): ContextWindowSummary | null {
  const cost = asRecord(runDetail?.cost_report);
  const rawUsed = Number(
    cost.latest_context_estimated_tokens ?? cost.max_context_estimated_tokens ?? 0,
  );
  const rawCapacity = Number(cost.context_window_tokens ?? 0);
  const rawRatio = Number(
    cost.context_window_ratio ?? (rawCapacity > 0 ? rawUsed / rawCapacity : 0),
  );
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

export type ContextBudgetSnapshot = {
  estimatedTokens: number;
  windowTokens: number;
  ratio: number;
  status: string;
  compactionThreshold: number;
  hardStopThreshold: number;
  duplicateTokens: number;
  duplicateRefs: number;
  topSections: ContextSection[];
  compaction: { action: string; status: string; delta: number } | null;
  peak: { ratio: number; status: string; taskId: string } | null;
  taskId: string;
  taskCount: number;
};

// B10-a: project the runtime's persisted per-task context budget (context_budget_snapshots.jsonl,
// surfaced by run-detail-reader.buildContextBudget) into the Inspector's Context tab. This is the
// authoritative budget the loop actually measured — richer than the run-level cost_report rollup the
// usage bar reads: it carries dedupe savings (how many tokens are duplicated context that compaction
// could reclaim), the compaction boundary the runtime computed, and the peak pressure across tasks.
// Pure surfacing of existing evidence — no thresholds invented here. Returns null when absent.
export function contextBudgetSnapshot(
  runDetail: RunDetailPayload | null,
): ContextBudgetSnapshot | null {
  const budget = asRecord((runDetail as AnyRecord | null)?.context_budget);
  if (!budget.available) return null;
  const latest = asRecord(budget.latest);
  const rawSections = Array.isArray(latest.top_sections) ? latest.top_sections : [];
  const topSections = rawSections
    .map((item) => {
      const record = asRecord(item);
      return {
        id: String(record.name ?? ""),
        label: contextSectionLabel(String(record.name ?? "")),
        value: Number(record.tokens ?? 0),
      };
    })
    .filter((item) => item.value > 0);
  const total = topSections.reduce((sum, item) => sum + item.value, 0);
  const compactBoundary = asRecord(latest.compact_boundary);
  const peakRecord = asRecord(budget.peak);
  return {
    estimatedTokens: Number(latest.estimated_tokens ?? 0),
    windowTokens: Number(latest.window_tokens ?? 0),
    ratio: Number(latest.ratio ?? 0),
    status: String(latest.pressure_status ?? ""),
    compactionThreshold: Number(latest.compaction_threshold ?? 0),
    hardStopThreshold: Number(latest.hard_stop_threshold ?? 0),
    duplicateTokens: Number(latest.duplicate_estimated_tokens ?? 0),
    duplicateRefs: Number(latest.duplicate_ref_count ?? 0),
    topSections: topSections.map((item) => ({
      ...item,
      ratio: total > 0 ? item.value / total : 0,
    })),
    compaction:
      Object.keys(compactBoundary).length && String(compactBoundary.status ?? "")
        ? {
            action: String(compactBoundary.recommended_action ?? ""),
            status: String(compactBoundary.status ?? ""),
            delta: Number(compactBoundary.estimated_tokens_delta ?? 0),
          }
        : null,
    peak: Object.keys(peakRecord).length
      ? {
          ratio: Number(peakRecord.ratio ?? 0),
          status: String(peakRecord.pressure_status ?? ""),
          taskId: String(peakRecord.task_id ?? ""),
        }
      : null,
    taskId: String(latest.task_id ?? ""),
    taskCount: Number(budget.count ?? 0),
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
