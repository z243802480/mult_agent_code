import React, { useEffect, useMemo, useState } from "react";
import { FolderOpen, X } from "lucide-react";
import type { WorkspaceEntry, WorkspaceProfile } from "../types";
import { api } from "../api";

function basename(value: string): string {
  const normalized = value.replace(/[\\/]+$/, "");
  const parts = normalized.split(/[\\/]/);
  return parts[parts.length - 1] || normalized || "工作区";
}

function WorkspaceProfileBadges({ profile }: { profile: WorkspaceProfile | null | undefined }) {
  if (!profile) return null;
  const badges = [
    profile.initialized ? "Asteria 已初始化" : "待初始化",
    profile.has_git ? "Git" : "无 Git",
    profile.has_agents_md ? "AGENTS.md" : "无 AGENTS.md",
  ];
  return (
    <div className="workspaceBadges">
      {badges.map((badge) => (
        <span key={badge} className="workspaceBadge">{badge}</span>
      ))}
    </div>
  );
}

export function WorkspaceSwitcher({
  open,
  currentWorkspace,
  onClose,
  onOpened,
}: {
  open: boolean;
  currentWorkspace: string;
  onClose: () => void;
  onOpened: () => void;
}) {
  const [pathValue, setPathValue] = useState(currentWorkspace);
  const [recent, setRecent] = useState<WorkspaceEntry[]>([]);
  const [previewProfile, setPreviewProfile] = useState<WorkspaceProfile | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setPathValue(currentWorkspace);
    setError(null);
    void api.workspaces()
      .then((payload) => setRecent(payload.recent_workspaces ?? []))
      .catch(() => setRecent([]));
  }, [open, currentWorkspace]);

  // Escape closes the switcher (was only dismissable via the backdrop / cancel button).
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  useEffect(() => {
    if (!open) return;
    const trimmed = pathValue.trim();
    if (!trimmed) {
      setPreviewProfile(null);
      return;
    }
    const timer = window.setTimeout(() => {
      void api.workspaceProfile(trimmed)
        .then((profile) => setPreviewProfile(profile))
        .catch(() => setPreviewProfile(null));
    }, 250);
    return () => window.clearTimeout(timer);
  }, [open, pathValue]);

  const currentLabel = useMemo(() => basename(currentWorkspace), [currentWorkspace]);

  if (!open) return null;

  async function openPath(nextPath: string) {
    const trimmed = nextPath.trim();
    if (!trimmed) {
      setError("请输入工作区文件夹路径。");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const result = await api.openWorkspace(trimmed);
      if (!result.ok) {
        setError(result.error || "无法打开工作区。");
        return;
      }
      onOpened();
      onClose();
    } catch (err) {
      setError(String((err as Error).message || err));
    } finally {
      setLoading(false);
    }
  }

  async function browseFolder() {
    setLoading(true);
    setError(null);
    try {
      const result = await api.browseWorkspace();
      if (!result.ok) {
        setError(result.error || "文件夹选择器不可用。");
        return;
      }
      if (result.cancelled || !result.path) return;
      setPathValue(result.path);
    } catch (err) {
      setError(String((err as Error).message || err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="workspaceOverlay" role="presentation" onClick={onClose}>
      <div
        className="workspaceModal"
        role="dialog"
        aria-modal="true"
        aria-label="打开工作区"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="workspaceModalHeader">
          <div>
            <p className="eyebrow">项目文件夹</p>
            <h2>打开工作区</h2>
            <p className="muted">
              类似 Claude Code 的项目选择器:目标、计划和文件改动都以此文件夹作为主工作目录。
            </p>
          </div>
          <button className="iconButton" title="关闭" aria-label="关闭" onClick={onClose}>
            <X size={18} />
          </button>
        </header>

        <div className="workspaceCurrent">
          <small>当前主工作目录</small>
          <strong title={currentWorkspace}>{currentLabel}</strong>
          <span className="muted" title={currentWorkspace}>{currentWorkspace}</span>
        </div>

        <label className="workspaceField">
          <span>文件夹路径</span>
          <div className="workspacePathRow">
            <input
              type="text"
              value={pathValue}
              placeholder="例如 H:\projects\my-app"
              onChange={(event) => setPathValue(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") void openPath(pathValue);
              }}
              disabled={loading}
            />
            <button type="button" className="secondaryButton" onClick={() => void browseFolder()} disabled={loading}>
              <FolderOpen size={15} /> 浏览
            </button>
          </div>
        </label>

        <WorkspaceProfileBadges profile={previewProfile} />

        {recent.length > 0 && (
          <div className="workspaceRecent">
            <p className="sideTitle">最近</p>
            <div className="workspaceRecentList">
              {recent.map((entry) => {
                const root = String(entry.workspace_root ?? "");
                const label = String(entry.name || basename(root));
                const active = root === currentWorkspace;
                return (
                  <button
                    key={`${entry.workspace_id ?? root}`}
                    type="button"
                    className={active ? "workspaceRecentItem active" : "workspaceRecentItem"}
                    title={root}
                    disabled={loading || active}
                    onClick={() => void openPath(root)}
                  >
                    <strong>{label}</strong>
                    <small>{root}</small>
                    <WorkspaceProfileBadges profile={entry.profile} />
                  </button>
                );
              })}
            </div>
          </div>
        )}

        {error && <p className="workspaceError">{error}</p>}

        <footer className="workspaceModalFooter">
          <button type="button" className="secondaryButton" onClick={onClose} disabled={loading}>
            取消
          </button>
          <button type="button" className="primaryButton" onClick={() => void openPath(pathValue)} disabled={loading}>
            {loading ? "打开中…" : "打开工作区"}
          </button>
        </footer>
      </div>
    </div>
  );
}
