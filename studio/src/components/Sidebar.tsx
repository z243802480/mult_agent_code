import React, { useState } from "react";
import { ChevronDown, ChevronRight, FolderOpen, Pencil, Sparkles, Trash2 } from "lucide-react";
import type { StudioSession, OverviewPayload, SettingsPayload } from "../types";
import { SignalCard, gateStage, validationTone } from "./Shared";
import { WorkspaceSwitcher } from "./WorkspaceSwitcher";

function cleanTitle(value: string): string {
  const text = value.replace(/\?{2,}/g, " ").replace(/\s+/g, " ").trim();
  return text || "Untitled session";
}

function workspaceLabel(settings: SettingsPayload | null): string {
  if (!settings?.workspace) return "Workspace";
  return settings.workspaceName || settings.workspace.split(/[\\/]/).pop() || "Workspace";
}

function sessionPreview(session: StudioSession): string {
  return String(session.goal_preview ?? "").trim();
}

export function Sidebar({
  sessions,
  active,
  overview,
  settings,
  isRunning,
  onSelect,
  onNew,
  onDelete,
  onRename,
  onWorkspaceChanged,
  workspaceOpen,
  onWorkspaceOpenChange,
}: {
  sessions: StudioSession[];
  active: StudioSession | null;
  overview: OverviewPayload | null;
  settings: SettingsPayload | null;
  isRunning: boolean;
  onSelect: (session: StudioSession) => void;
  onNew: () => void;
  onDelete: (session: StudioSession) => void;
  onRename: (session: StudioSession, title: string) => Promise<void>;
  onWorkspaceChanged: () => void;
  workspaceOpen: boolean;
  onWorkspaceOpenChange: (open: boolean) => void;
}) {
  const [statusOpen, setStatusOpen] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draftTitle, setDraftTitle] = useState("");
  const gate = (overview?.gateStatus ?? {}) as Record<string, unknown>;
  const diagnosticsLoaded = overview?.diagnostics_loaded !== false;

  async function commitRename(session: StudioSession) {
    const next = draftTitle.trim();
    setEditingId(null);
    if (!next || next === session.title) return;
    await onRename(session, next);
  }

  return (
    <aside className="sidebar">
      <div className="brandBlock">
        <div className="brand">Asteria</div>
        <small>AI workspace · Ctrl+Tab switch</small>
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
              label={diagnosticsLoaded ? "Ready" : "Checking"}
              value={gateStage(overview)}
              detail={
                diagnosticsLoaded
                  ? String(gate.blocking_reason ?? gate.release_state ?? gate.status ?? "Ready to help")
                  : "Loading deeper checks"
              }
              tone={validationTone(overview)}
            />
          </div>
        )}
      </div>

      <nav className="sessionList">
        <p className="sideTitle">Sessions</p>
        {sessions.map((session) => {
          const preview = sessionPreview(session);
          const isActive = active?.session_id === session.session_id;
          const showLive = isActive && isRunning;
          return (
            <div className={isActive ? "sessionRow active" : "sessionRow"} key={session.session_id}>
              {editingId === session.session_id ? (
                <input
                  className="sessionRenameInput"
                  value={draftTitle}
                  autoFocus
                  onChange={(event) => setDraftTitle(event.target.value)}
                  onBlur={() => void commitRename(session)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") void commitRename(session);
                    if (event.key === "Escape") setEditingId(null);
                  }}
                />
              ) : (
                <button className="session" onClick={() => onSelect(session)}>
                  <span className="sessionTitleRow">
                    <span>{cleanTitle(String(session.title || "Untitled"))}</span>
                    {showLive && <em className="sessionLiveBadge">live</em>}
                  </span>
                  {preview && <small className="sessionPreview" title={preview}>{preview}</small>}
                  <small>{new Date(session.updated_at).toLocaleString()}</small>
                </button>
              )}
              <button
                className="sessionRename"
                title="Rename session"
                aria-label="Rename session"
                onClick={(event) => {
                  event.stopPropagation();
                  setEditingId(session.session_id);
                  setDraftTitle(String(session.title || ""));
                }}
              >
                <Pencil size={13} />
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
          );
        })}
      </nav>

      <button className="settingsLink workspaceButton" type="button" onClick={() => onWorkspaceOpenChange(true)}>
        <FolderOpen size={15} />
        <span title={settings?.workspace ?? ""}>{workspaceLabel(settings)}</span>
      </button>
      <WorkspaceSwitcher
        open={workspaceOpen}
        currentWorkspace={settings?.workspace ?? ""}
        onClose={() => onWorkspaceOpenChange(false)}
        onOpened={onWorkspaceChanged}
      />
    </aside>
  );
}
