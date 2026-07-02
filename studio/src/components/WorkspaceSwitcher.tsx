import React, { useEffect, useMemo, useState } from "react";
import { FolderOpen, X } from "lucide-react";
import type { WorkspaceEntry, WorkspaceProfile } from "../types";
import { api } from "../api";

function basename(value: string): string {
  const normalized = value.replace(/[\\/]+$/, "");
  const parts = normalized.split(/[\\/]/);
  return parts[parts.length - 1] || normalized || "workspace";
}

function WorkspaceProfileBadges({ profile }: { profile: WorkspaceProfile | null | undefined }) {
  if (!profile) return null;
  const badges = [
    profile.initialized ? "Asteria init" : "Needs init",
    profile.has_git ? "Git" : "No git",
    profile.has_agents_md ? "AGENTS.md" : "No AGENTS.md",
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
      setError("Enter a workspace folder path.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const result = await api.openWorkspace(trimmed);
      if (!result.ok) {
        setError(result.error || "Could not open workspace.");
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
        setError(result.error || "Folder picker is unavailable.");
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
        aria-label="Open workspace"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="workspaceModalHeader">
          <div>
            <p className="eyebrow">Project folder</p>
            <h2>Open workspace</h2>
            <p className="muted">
              Like Claude Code&apos;s project picker: goals, plans, and file edits use this folder as the primary working directory.
            </p>
          </div>
          <button className="iconButton" title="Close" aria-label="Close" onClick={onClose}>
            <X size={18} />
          </button>
        </header>

        <div className="workspaceCurrent">
          <small>Current primary cwd</small>
          <strong title={currentWorkspace}>{currentLabel}</strong>
          <span className="muted" title={currentWorkspace}>{currentWorkspace}</span>
        </div>

        <label className="workspaceField">
          <span>Folder path</span>
          <div className="workspacePathRow">
            <input
              type="text"
              value={pathValue}
              placeholder="e.g. H:\projects\my-app"
              onChange={(event) => setPathValue(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") void openPath(pathValue);
              }}
              disabled={loading}
            />
            <button type="button" className="secondaryButton" onClick={() => void browseFolder()} disabled={loading}>
              <FolderOpen size={15} /> Browse
            </button>
          </div>
        </label>

        <WorkspaceProfileBadges profile={previewProfile} />

        {recent.length > 0 && (
          <div className="workspaceRecent">
            <p className="sideTitle">Recent</p>
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
            Cancel
          </button>
          <button type="button" className="primaryButton" onClick={() => void openPath(pathValue)} disabled={loading}>
            {loading ? "Opening…" : "Open workspace"}
          </button>
        </footer>
      </div>
    </div>
  );
}
