import React, { useState } from "react";
import { ChevronDown, ChevronRight, Settings, Sparkles, Trash2 } from "lucide-react";
import type { StudioSession, OverviewPayload, SettingsPayload } from "../types";
import { SignalCard, gateStage, validationTone } from "./Shared";

function cleanTitle(value: string): string {
  const text = value.replace(/\?{2,}/g, " ").replace(/\s+/g, " ").trim();
  return text || "Untitled session";
}

export function Sidebar({
  sessions,
  active,
  overview,
  settings,
  onSelect,
  onNew,
  onDelete,
}: {
  sessions: StudioSession[];
  active: StudioSession | null;
  overview: OverviewPayload | null;
  settings: SettingsPayload | null;
  onSelect: (session: StudioSession) => void;
  onNew: () => void;
  onDelete: (session: StudioSession) => void;
}) {
  const [statusOpen, setStatusOpen] = useState(false);
  const gate = (overview?.gateStatus ?? {}) as Record<string, unknown>;

  return (
    <aside className="sidebar">
      <div className="brandBlock">
        <div className="brand">Asteria</div>
        <small>AI workspace</small>
      </div>
      <button className="newButton" onClick={onNew}>
        <Sparkles size={15} /> New task
      </button>

      <div className="sideSection">
        <button className="statusToggle" onClick={() => setStatusOpen((o) => !o)}>
          <span className="sideTitle">Workspace health</span>
          {statusOpen ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
        </button>
        {statusOpen && (
          <div className="statusCards">
            <SignalCard
              icon={<Sparkles size={14} />}
              label="Ready"
              value={gateStage(overview)}
              detail={String(gate.blocking_reason ?? gate.release_state ?? gate.status ?? "Ready to help")}
              tone={validationTone(overview)}
            />
          </div>
        )}
      </div>

      <nav className="sessionList">
        <p className="sideTitle">Sessions</p>
        {sessions.map((session) => (
          <div className={active?.session_id === session.session_id ? "sessionRow active" : "sessionRow"} key={session.session_id}>
            <button
              className="session"
              onClick={() => onSelect(session)}
            >
              <span>{cleanTitle(String(session.title || "Untitled"))}</span>
              <small>{new Date(session.updated_at).toLocaleString()}</small>
            </button>
            <button
              className="sessionDelete"
              title="Delete session"
              aria-label="Delete session"
              onClick={(event) => {
                event.stopPropagation();
                onDelete(session);
              }}
            >
              <Trash2 size={14} />
            </button>
          </div>
        ))}
      </nav>

      <div className="settingsLink">
        <Settings size={15} />
        {settings?.workspace ? <span title={settings.workspace}>Workspace</span> : "Workspace"}
      </div>
    </aside>
  );
}
