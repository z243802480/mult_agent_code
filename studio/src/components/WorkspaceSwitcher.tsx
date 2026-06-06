import React, { useEffect, useMemo, useState } from "react";
import { FolderOpen, X } from "lucide-react";
import type { WorkspaceEntry } from "../types";
import { api } from "../api";

function basename(value: string): string {
  const normalized = value.replace(/[\\/]+$/, "");
  const parts = normalized.split(/[\\/]/);
  return parts[parts.length - 1] || normalized || "workspace";
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
            <p className="eyebrow">Project</p>
            <h2>Open workspace</h2>
            <p className="muted">Goals, plans, and code changes run in the selected folder.</p>
          </div>
          <button className="iconButton" title="Close" aria-label="Close" onClick={onClose}>
            <X size={18} />
          </button>
        </header>

        <div className="workspaceCurrent">
          <small>Current</small>
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
