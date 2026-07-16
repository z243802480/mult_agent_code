import React, { useState } from "react";
import { ChevronDown, ChevronRight, PanelLeftClose, Plus, Sparkles } from "lucide-react";
import type { StudioSession, OverviewPayload, SettingsPayload } from "../types";
import { SignalCard, gateStage, validationTone } from "./Shared";
import type { StudioViewMode } from "../hooks/useViewMode";
import { useSessionListFilter } from "../hooks/useSessionListFilter";
import { SessionList } from "../features/sidebar/SessionList";
import { SessionRail } from "../features/sidebar/SessionRail";

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
  onArchive,
  onImportFile,
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
  onArchive?: (session: StudioSession, archived: boolean) => void;
  onImportFile?: (file: File) => void;
  viewMode: StudioViewMode;
}) {
  const [statusOpen, setStatusOpen] = useState(false);
  const { filter, setFilter } = useSessionListFilter();
  const gate = (overview?.gateStatus ?? {}) as Record<string, unknown>;
  const diagnosticsLoaded = overview?.diagnostics_loaded !== false;
  const compactSessions = viewMode === "focus";

  if (collapsed) {
    return (
      <aside className="sidebar sidebarRail" aria-label="会话">
        <button
          type="button"
          className="sidebarRailButton brandMark"
          title="展开侧栏 (Ctrl+B)"
          aria-label="展开侧栏"
          onClick={onToggleCollapse}
        >
          A
        </button>
        <button type="button" className="sidebarRailButton" title="新建任务" onClick={onNew}>
          <Plus size={16} />
        </button>
        <SessionRail
          sessions={sessions}
          active={active}
          isRunning={isRunning}
          filter={filter}
          onSelect={onSelect}
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
          title="收起侧栏 (Ctrl+B)"
          aria-label="收起侧栏"
          onClick={onToggleCollapse}
        >
          <PanelLeftClose size={15} />
        </button>
      </div>
      <button className="newButton" onClick={onNew}>
        <Plus size={15} /> 新建任务
      </button>

      {viewMode !== "focus" && (
        <div className="sideSection">
          <button className="statusToggle" onClick={() => setStatusOpen((open) => !open)}>
            <span className="sideTitle">工作区健康度</span>
            {statusOpen ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
          </button>
          {statusOpen && (
            <div className="statusCards">
              <SignalCard
                icon={<Sparkles size={14} />}
                label={diagnosticsLoaded ? "就绪" : "检查中"}
                value={gateStage(overview)}
                detail={
                  diagnosticsLoaded
                    ? String(gate.blocking_reason ?? gate.release_state ?? gate.status ?? "已就绪")
                    : "正在加载深度检查"
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
        onArchive={onArchive}
        onImportFile={onImportFile}
        compact={compactSessions}
      />
    </aside>
  );
}
