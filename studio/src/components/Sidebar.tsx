import React, { useState } from "react";
import { ChevronDown, ChevronRight, GitBranch, Route, Settings, ShieldAlert, Sparkles, Terminal } from "lucide-react";
import type { StudioSession, OverviewPayload, SettingsPayload } from "../types";
import { SignalCard, Metric, gateStage, readinessTone, routeDecision, routeTone, routeDetail } from "./Shared";

function healthValue(doctor: Record<string, unknown>, pkg: Record<string, unknown>): string {
  if (doctor.ok === false || pkg.ok === false) return "需要处理";
  if (doctor.ok === true && pkg.ok === true) return "检查通过";
  return "检查中";
}

function healthDetail(doctor: Record<string, unknown>, pkg: Record<string, unknown>): string {
  return String(doctor.status ?? pkg.status ?? `${Object.keys(doctor.checks ?? {}).length + Object.keys(pkg.checks ?? {}).length} checks`);
}

function healthTone(doctor: Record<string, unknown>, pkg: Record<string, unknown>): string {
  if (doctor.ok === false || pkg.ok === false) return "bad";
  if (doctor.ok === true && pkg.ok === true) return "good";
  return "warn";
}

function latestRunDetail(run?: Record<string, unknown>): string {
  if (!run) return "暂无本地 run 证据";
  const calls = run.cost_report && (run.cost_report as Record<string, unknown>).model_calls;
  return String(run.status ?? "") + (calls != null ? ` · ${calls} 模型调用` : "");
}

function latestRunTone(run?: Record<string, unknown>): string {
  if (!run) return "warn";
  if (/failed|blocked/i.test(String(run.status ?? ""))) return "bad";
  if (/complete|success|ready/i.test(String(run.status ?? ""))) return "good";
  return "warn";
}

export function Sidebar({
  sessions,
  active,
  overview,
  settings,
  onSelect,
  onNew,
}: {
  sessions: StudioSession[];
  active: StudioSession | null;
  overview: OverviewPayload | null;
  settings: SettingsPayload | null;
  onSelect: (session: StudioSession) => void;
  onNew: () => void;
}) {
  const [statusOpen, setStatusOpen] = useState(false);
  const gate = (overview?.gateStatus ?? {}) as Record<string, unknown>;
  const doctor = (overview?.doctor ?? {}) as Record<string, unknown>;
  const packageCheck = (overview?.packageCheck ?? {}) as Record<string, unknown>;
  const latestRun = overview?.runs?.[0] as Record<string, unknown> | undefined;

  return (
    <aside className="sidebar">
      <div className="brandBlock">
        <div className="brand">Asteria</div>
        <small>Local Runtime OS</small>
      </div>
      <button className="newButton" onClick={onNew}>
        <Sparkles size={15} /> 新任务
      </button>

      {/* Collapsible system status */}
      <div className="sideSection">
        <button className="statusToggle" onClick={() => setStatusOpen((o) => !o)}>
          <span className="sideTitle">系统状态</span>
          {statusOpen ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
        </button>
        {statusOpen && (
          <div className="statusCards">
            <SignalCard
              icon={<ShieldAlert size={14} />}
              label="Gate"
              value={gateStage(overview)}
              detail={String(gate.blocking_reason ?? gate.rollout_state ?? gate.status ?? "")}
              tone={readinessTone(overview)}
            />
            <SignalCard
              icon={<Route size={14} />}
              label="Provider"
              value={routeDecision(overview)}
              detail={routeDetail(overview)}
              tone={routeTone(overview)}
            />
            <SignalCard
              icon={<Terminal size={14} />}
              label="Runtime"
              value={healthValue(doctor, packageCheck)}
              detail={healthDetail(doctor, packageCheck)}
              tone={healthTone(doctor, packageCheck)}
            />
            <SignalCard
              icon={<GitBranch size={14} />}
              label="Latest Run"
              value={String(latestRun?.run_id ?? "no run")}
              detail={latestRunDetail(latestRun)}
              tone={latestRunTone(latestRun)}
            />
          </div>
        )}
        {!statusOpen && (
          <div className="statusSummary">
            <Metric label="Gate" value={gateStage(overview)} tone={readinessTone(overview)} />
            <Metric label="Route" value={routeDecision(overview)} tone={routeTone(overview)} />
          </div>
        )}
      </div>

      <nav className="sessionList">
        <p className="sideTitle">会话</p>
        {sessions.map((session) => (
          <button
            className={active?.session_id === session.session_id ? "session active" : "session"}
            key={session.session_id}
            onClick={() => onSelect(session)}
          >
            <span>{session.title || "未命名"}</span>
            <small>{new Date(session.updated_at).toLocaleString()}</small>
          </button>
        ))}
      </nav>

      <div className="settingsLink">
        <Settings size={15} />
        {settings?.workspace ? <span title={settings.workspace}>本地工作区</span> : "本地"}
      </div>
    </aside>
  );
}
