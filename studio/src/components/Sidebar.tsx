import React, { useState } from "react";
import {
  ChevronDown,
  ChevronRight,
  FolderOpen,
  PanelLeftClose,
  Sparkles,
} from "lucide-react";
import type { StudioSession, OverviewPayload, SettingsPayload } from "../types";
import { SignalCard, gateStage, validationTone } from "./Shared";
import type { StudioViewMode } from "../hooks/useViewMode";
import { useSessionListFilter } from "../hooks/useSessionListFilter";
import { WorkspaceSwitcher } from "./WorkspaceSwitcher";
import { SessionList } from "../features/sidebar/SessionList";
import { SessionRail } from "../features/sidebar/SessionRail";

function workspaceLabel(settings: SettingsPayload | null): string {
  if (!settings?.workspace) return "Workspace";
  return settings.workspaceName || settings.workspace.split(/[\\/]/).pop() || "Workspace";
}

export function Sidebar({
  sessions,
  active,
  overview,
  settings,
  isRunning,
  collapsed,
  onToggleCollapse,
  onSelect,
  onNew,
  onDelete,
  onRename,
  onWorkspaceChanged,
  workspaceOpen,
  onWorkspaceOpenChange,
  viewMode,
}: {
  sessions: StudioSession[];
  active: StudioSession | null;
  overview: OverviewPayload | null;
  settings: SettingsPayload | null;
  isRunning: boolean;
  collapsed: boolean;
  onToggleCollapse: () => void;
  onSelect: (session: StudioSession) => void;
  onNew: () => void;
  onDelete: (session: StudioSession) => void;
  onRename: (session: StudioSession, title: string) => Promise<void>;
  onWorkspaceChanged: () => void;
  workspaceOpen: boolean;
  onWorkspaceOpenChange: (open: boolean) => void;
  viewMode: StudioViewMode;
}) {
  const [statusOpen, setStatusOpen] = useState(false);
  const { filter, setFilter } = useSessionListFilter();
  const gate = (overview?.gateStatus ?? {}) as Record<string, unknown>;
  const diagnosticsLoaded = overview?.diagnostics_loaded !== false;
  const compactSessions = viewMode === "focus";

  if (collapsed) {
    return (
      <aside className="sidebar sidebarRail" aria-label="Sessions">
        <button
          type="button"
          className="sidebarRailButton brandMark"
          title="Expand sidebar (Ctrl+B)"
          aria-label="Expand sidebar"
          onClick={onToggleCollapse}
        >
          A
        </button>
        <button type="button" className="sidebarRailButton" title="New task" onClick={onNew}>
          <Sparkles size={16} />
        </button>
        <SessionRail
          sessions={sessions}
          active={active}
          isRunning={isRunning}
          filter={filter}
          onSelect={onSelect}
        />
        <button
          type="button"
          className="sidebarRailButton sidebarRailFooter"
          title={settings?.workspace ?? workspaceLabel(settings)}
          aria-label="Switch workspace"
          onClick={() => onWorkspaceOpenChange(true)}
        >
          <FolderOpen size={16} />
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

  return (
    <aside className="sidebar">
      <div className="sidebarHead">
        <div className="brandBlock">
          <div className="brand">Asteria</div>
        </div>
        <button
          type="button"
          className="sidebarCollapseButton"
          title="Collapse sidebar (Ctrl+B)"
          aria-label="Collapse sidebar"
          onClick={onToggleCollapse}
        >
          <PanelLeftClose size={15} />
        </button>
      </div>
      <button className="newButton" onClick={onNew}>
        <Sparkles size={15} /> New task
      </button>

      {viewMode !== "focus" && (
        <div className="sideSection">
          <button className="statusToggle" onClick={() => setStatusOpen((open) => !open)}>
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
      )}

      <SessionList
        sessions={sessions}
        active={active}
        isRunning={isRunning}
        filter={filter}
        onFilterChange={setFilter}
        onSelect={onSelect}
        onDelete={onDelete}
        onRename={onRename}
        compact={compactSessions}
      />

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
