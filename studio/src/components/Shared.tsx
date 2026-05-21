import React from "react";
import { CheckCircle2, XCircle } from "lucide-react";
import type { StudioEvent, OverviewPayload } from "../types";

export function Metric({ label, value, tone }: { label: string; value: string; tone: string }) {
  return (
    <div className={`metric ${tone}`}>
      <small>{label}</small>
      <strong>{value}</strong>
    </div>
  );
}

export function Status({ status }: { status: StudioEvent["status"] }) {
  return <span className={`status ${status}`}>{status}</span>;
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
  const gate = (overview?.gateStatus ?? {}) as Record<string, unknown>;
  return String(gate.stage ?? gate.rollout_state ?? "unknown");
}

export function readinessTone(overview: OverviewPayload | null): string {
  const gate = (overview?.gateStatus ?? {}) as Record<string, unknown>;
  if (gate.release_ready || /ready/i.test(String(gate.stage ?? gate.rollout_state ?? ""))) return "good";
  if (/blocked|failed|missing/i.test(String(gate.stage ?? gate.rollout_state ?? gate.status ?? ""))) return "bad";
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
  return firstNonEmpty(String(strategy.primary_model ?? ""), String(guidance.status ?? ""), String(strategy.recommended_action ?? ""));
}

function firstNonEmpty(...items: string[]): string {
  return items.find((s) => s.trim()) ?? "";
}

export function formatMs(value: unknown): string {
  if (value === null || value === undefined || value === "") return "n/a";
  const n = Number(value);
  if (!Number.isFinite(n)) return "n/a";
  return `${Math.round(n)}ms`;
}

export function percent(value: unknown): string {
  const n = Number(value);
  if (!Number.isFinite(n)) return "n/a";
  return `${Math.round(n * 100)}%`;
}
