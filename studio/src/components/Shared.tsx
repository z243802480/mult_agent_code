import React from "react";
import { CheckCircle2, XCircle } from "lucide-react";
import type { OverviewPayload } from "../types";

export function Metric({ label, value, tone }: { label: string; value: string; tone: string }) {
  return (
    <div className={`metric ${tone}`}>
      <small>{label}</small>
      <strong>{value}</strong>
    </div>
  );
}

const STATUS_LABELS: Record<string, string> = {
  running: "运行中",
  queued: "已排队",
  completed: "已完成",
  failed: "失败",
  blocked: "受阻",
  waiting_user: "待你处理",
  // Worker/step statuses that reach Status via inspector panels (worker topology, workflow monitor)
  // which cast past the StudioEvent["status"] type. Before these were mapped, an unlabeled value fell
  // through to the raw English enum — an English word in a Chinese UI. Map every realistic value.
  success: "成功",
  pending: "等待中",
  in_progress: "进行中",
  cancelled: "已取消",
  canceled: "已取消",
  error: "错误",
  skipped: "已跳过",
  timeout: "超时",
  ok: "正常",
  done: "已完成",
  unknown: "未知",
};

// Localize a worker/step/event status enum. Falls back to a neutral Chinese label rather than leaking
// the raw English enum — losing granularity on a never-seen value beats an English word in a Chinese UI.
export function statusLabel(status: string): string {
  return STATUS_LABELS[status] ?? "未知";
}

// Accept a plain string: the inspector panels legitimately carry worker/step statuses beyond the
// StudioEvent["status"] union (they cast to reach here). The className keeps the raw token for styling.
export function Status({ status }: { status: string }) {
  return <span className={`status ${status}`}>{statusLabel(status)}</span>;
}

export function Banner({ text, tone }: { text: string; tone: "good" | "bad" }) {
  return (
    <div className={`banner ${tone}`}>
      {tone === "good" ? <CheckCircle2 size={18} /> : <XCircle size={18} />}
      {text}
    </div>
  );
}

export function SignalCard({
  icon,
  label,
  value,
  detail,
  tone,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  detail: string;
  tone: string;
}) {
  return (
    <div className={`signalCard ${tone}`}>
      <div className="signalHead">
        {icon}
        <span>{label}</span>
      </div>
      <strong>{value}</strong>
      <small>{detail || "暂无证据"}</small>
    </div>
  );
}

export function gateStage(overview: OverviewPayload | null): string {
  if (overview && overview.diagnostics_loaded === false) return "loading";
  const gate = (overview?.gateStatus ?? {}) as Record<string, unknown>;
  return String(gate.stage ?? gate.release_state ?? "unknown");
}

export function validationTone(overview: OverviewPayload | null): string {
  if (overview && overview.diagnostics_loaded === false) return "warn";
  const gate = (overview?.gateStatus ?? {}) as Record<string, unknown>;
  if (gate.release_ready || /ready/i.test(String(gate.stage ?? gate.release_state ?? "")))
    return "good";
  if (/blocked|failed|missing/i.test(String(gate.stage ?? gate.release_state ?? gate.status ?? "")))
    return "bad";
  return "warn";
}

export function routeDecision(overview: OverviewPayload | null): string {
  const gateStatus = (overview?.gateStatus ?? {}) as Record<string, unknown>;
  const guidance = (gateStatus.route_guidance ?? {}) as Record<string, unknown>;
  const strategy = (guidance.provider_route_strategy ?? {}) as Record<string, unknown>;
  return String(strategy.decision ?? guidance.status ?? "route unknown");
}

export function routeTone(overview: OverviewPayload | null): string {
  const value = routeDecision(overview);
  if (/continue|healthy|allow/i.test(value)) return "good";
  if (/block|failed|missing/i.test(value)) return "bad";
  return "warn";
}

export function routeDetail(overview: OverviewPayload | null): string {
  const gateStatus = (overview?.gateStatus ?? {}) as Record<string, unknown>;
  const guidance = (gateStatus.route_guidance ?? {}) as Record<string, unknown>;
  const strategy = (guidance.provider_route_strategy ?? {}) as Record<string, unknown>;
  return firstNonEmpty(
    String(strategy.primary_model ?? ""),
    String(guidance.status ?? ""),
    String(strategy.recommended_action ?? ""),
  );
}

function firstNonEmpty(...items: string[]): string {
  return items.find((s) => s.trim()) ?? "";
}

export function formatMs(value: unknown): string {
  if (value === null || value === undefined || value === "") return "不适用";
  const n = Number(value);
  if (!Number.isFinite(n)) return "不适用";
  return `${Math.round(n)}ms`;
}

export function percent(value: unknown): string {
  const n = Number(value);
  if (!Number.isFinite(n)) return "不适用";
  return `${Math.round(n * 100)}%`;
}
