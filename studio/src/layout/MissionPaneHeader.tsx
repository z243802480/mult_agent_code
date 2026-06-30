import React from "react";
import { FolderOpen, GitBranch, LayoutList, PanelRightClose, PanelRightOpen, RefreshCw } from "lucide-react";
import type { SettingsPayload } from "../types";
import { SideChatToggle } from "../features/sidechat/SideChatPanel";
import { viewModeLabel, type StudioViewMode } from "../hooks/useViewMode";

type MissionPaneHeaderProps = {
  title: string;
  settings: SettingsPayload | null;
  viewMode: StudioViewMode;
  panelOpen: boolean;
  diffFocus: boolean;
  sideChatOpen: boolean;
  loading: boolean;
  isRunning: boolean;
  changeCount: number;
  branch?: string;
  onOpenWorkspace: () => void;
  onCycleViewMode: () => void;
  onTogglePanel: () => void;
  onToggleDiffFocus: () => void;
  onToggleSideChat: () => void;
  onRefresh: () => void;
};

export function MissionPaneHeader({
  title,
  settings,
  viewMode,
  panelOpen,
  diffFocus,
  sideChatOpen,
  loading,
  isRunning,
  changeCount,
  branch,
  onOpenWorkspace,
  onCycleViewMode,
  onTogglePanel,
  onToggleDiffFocus,
  onToggleSideChat,
  onRefresh,
}: MissionPaneHeaderProps) {
  return (
    <header className="globalHeader">
      <div className="topBarMain">
        <h1>{title}</h1>
        <button
          type="button"
          className="workspaceChip"
          title={settings?.workspace ?? "Open workspace folder"}
          onClick={onOpenWorkspace}
        >
          <FolderOpen size={13} />
          <span>{settings?.workspaceName ?? "Workspace"}</span>
        </button>
        {branch && (
          <span className="headerBranch" title={`Branch: ${branch}`}>
            <GitBranch size={12} />
            <span>{branch}</span>
          </span>
        )}
        <span
          className={isRunning ? "headerStatus running" : "headerStatus"}
          title={isRunning ? "Agent is running" : "Idle"}
        >
          <span className="headerStatusDot" />
          {isRunning ? "Running" : "Idle"}
        </span>
      </div>
      <div className="topActions">
        <div className="headerPaneGroup">
          <button
            type="button"
            className={diffFocus ? "diffFocusButton active" : "diffFocusButton"}
            title="Review changes (Ctrl+Shift+D)"
            onClick={onToggleDiffFocus}
          >
            Review
            {changeCount > 0 && <span className="headerBadge">{changeCount}</span>}
          </button>
        </div>
        <div className="headerToolGroup">
          <button
            type="button"
            className={`viewModeButton view-${viewMode}`}
            title={`View: ${viewModeLabel(viewMode)} (click to cycle)`}
            onClick={onCycleViewMode}
          >
            <LayoutList size={15} />
            <span>{viewModeLabel(viewMode)}</span>
          </button>
          <SideChatToggle open={sideChatOpen} onToggle={onToggleSideChat} />
          <button
            type="button"
            title={panelOpen ? "Hide side panel (Ctrl+\\)" : "Show side panel (Ctrl+\\)"}
            onClick={onTogglePanel}
          >
            {panelOpen ? <PanelRightClose size={16} /> : <PanelRightOpen size={16} />}
          </button>
          <button title="Refresh" onClick={onRefresh} disabled={loading}>
            <RefreshCw size={16} className={loading ? "spinning" : ""} />
          </button>
        </div>
      </div>
    </header>
  );
}
