import React from "react";
import { FolderOpen, GitBranch, LayoutList, PanelRightClose, PanelRightOpen, RefreshCw, Settings, ShieldCheck, WifiOff } from "lucide-react";
import type { SettingsPayload } from "../types";
import type { ConnectivityStatus } from "../api";
import { permissionTier } from "../permissionTiers";
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
  connectivity?: ConnectivityStatus;
  changeCount: number;
  branch?: string;
  onOpenWorkspace: () => void;
  onCycleViewMode: () => void;
  onTogglePanel: () => void;
  onToggleDiffFocus: () => void;
  onToggleSideChat: () => void;
  onOpenSettings: () => void;
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
  connectivity,
  changeCount,
  branch,
  onOpenWorkspace,
  onCycleViewMode,
  onTogglePanel,
  onToggleDiffFocus,
  onToggleSideChat,
  onOpenSettings,
  onRefresh,
}: MissionPaneHeaderProps) {
  return (
    <header className="globalHeader">
      <div className="topBarMain">
        <h1>{title}</h1>
        <button
          type="button"
          className="workspaceChip"
          title={settings?.workspace ?? "打开工作区文件夹"}
          onClick={onOpenWorkspace}
        >
          <FolderOpen size={13} />
          <span>{settings?.workspaceName ?? "工作区"}</span>
        </button>
        {branch && (
          <span className="headerBranch" title={`分支: ${branch}`}>
            <GitBranch size={12} />
            <span>{branch}</span>
          </span>
        )}
        <span
          className={isRunning ? "headerStatus running" : "headerStatus"}
          title={isRunning ? "Agent 运行中" : "空闲"}
        >
          <span className="headerStatusDot" />
          {isRunning ? "运行中" : "空闲"}
        </span>
        {connectivity && connectivity !== "live" && (
          <span
            className={`headerConnectivity ${connectivity}`}
            title={
              connectivity === "offline"
                ? "无法连接 Studio 服务器——正在自动重试。"
                : "实时流已断开——正在重连；更新通过兜底轮询到达。"
            }
          >
            <WifiOff size={12} />
            <span>{connectivity === "offline" ? "离线——重试中" : "重连中…"}</span>
          </span>
        )}
        {settings?.permissionMode && (
          <span
            className="headerPermission"
            title={`默认权限: ${permissionTier(settings.permissionMode).hint}。可在设置中更改。`}
          >
            <ShieldCheck size={12} />
            <span>{permissionTier(settings.permissionMode).label}</span>
          </span>
        )}
      </div>
      <div className="topActions">
        <div className="headerPaneGroup">
          <button
            type="button"
            className={diffFocus ? "diffFocusButton active" : "diffFocusButton"}
            title="查看改动 (Ctrl+Shift+D)"
            onClick={onToggleDiffFocus}
          >
            查看
            {changeCount > 0 && <span className="headerBadge">{changeCount}</span>}
          </button>
        </div>
        <div className="headerToolGroup">
          <button
            type="button"
            className={`viewModeButton view-${viewMode}`}
            title={`视图: ${viewModeLabel(viewMode)} (点击切换)`}
            onClick={onCycleViewMode}
          >
            <LayoutList size={15} />
            <span>{viewModeLabel(viewMode)}</span>
          </button>
          <SideChatToggle open={sideChatOpen} onToggle={onToggleSideChat} />
          <button
            type="button"
            title={panelOpen ? "隐藏侧栏 (Ctrl+\\)" : "显示侧栏 (Ctrl+\\)"}
            onClick={onTogglePanel}
          >
            {panelOpen ? <PanelRightClose size={16} /> : <PanelRightOpen size={16} />}
          </button>
          <button title="刷新" onClick={onRefresh} disabled={loading}>
            <RefreshCw size={16} className={loading ? "spinning" : ""} />
          </button>
          <button type="button" title="设置" aria-label="设置" onClick={onOpenSettings}>
            <Settings size={16} />
          </button>
        </div>
      </div>
    </header>
  );
}
