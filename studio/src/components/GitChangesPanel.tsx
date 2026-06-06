import React from "react";
import { GitBranch, RefreshCw } from "lucide-react";
import type { GitChangeEntry, GitStatusPayload } from "../types";

const STATUS_LABEL: Record<string, string> = {
  modified: "M",
  added: "A",
  deleted: "D",
  untracked: "?",
  renamed: "R",
  changed: "~",
};

export function GitChangesPanel({
  gitStatus,
  loading,
  selectedPath,
  onRefresh,
  onSelectChange,
}: {
  gitStatus: GitStatusPayload | null;
  loading: boolean;
  selectedPath: string | null;
  onRefresh: () => void;
  onSelectChange: (path: string) => void;
}) {
  if (!gitStatus) {
    return (
      <section className="gitChangesPanel">
        <div className="gitChangesHeader">
          <h2>Workspace changes</h2>
          <button type="button" className="iconButton" title="Refresh git status" onClick={onRefresh} disabled={loading}>
            <RefreshCw size={14} className={loading ? "spinning" : ""} />
          </button>
        </div>
        <p className="muted">Loading git status…</p>
      </section>
    );
  }

  if (!gitStatus.available) {
    return (
      <section className="gitChangesPanel">
        <div className="gitChangesHeader">
          <h2>Workspace changes</h2>
          <button type="button" className="iconButton" title="Refresh git status" onClick={onRefresh} disabled={loading}>
            <RefreshCw size={14} className={loading ? "spinning" : ""} />
          </button>
        </div>
        <p className="muted">{gitStatus.reason ?? "Git is not available for this workspace."}</p>
      </section>
    );
  }

  const changes = gitStatus.changes ?? [];

  return (
    <section className="gitChangesPanel">
      <div className="gitChangesHeader">
        <div>
          <h2>Workspace changes</h2>
          <p className="gitBranchLine">
            <GitBranch size={13} />
            <span>{gitStatus.branch ?? "HEAD"}</span>
            <span className="muted">
              {gitStatus.clean ? "· clean" : `· ${gitStatus.change_count ?? changes.length} changed`}
            </span>
          </p>
        </div>
        <button type="button" className="iconButton" title="Refresh git status" onClick={onRefresh} disabled={loading}>
          <RefreshCw size={14} className={loading ? "spinning" : ""} />
        </button>
      </div>
      {changes.length === 0 ? (
        <p className="muted">No uncommitted changes in this workspace.</p>
      ) : (
        <div className="gitChangeList">
          {changes.map((change) => (
            <GitChangeRow
              key={change.path}
              change={change}
              active={selectedPath === change.path}
              onSelect={() => onSelectChange(change.path)}
            />
          ))}
        </div>
      )}
    </section>
  );
}

function GitChangeRow({
  change,
  active,
  onSelect,
}: {
  change: GitChangeEntry;
  active: boolean;
  onSelect: () => void;
}) {
  const badge = STATUS_LABEL[change.status] ?? "~";
  return (
    <button type="button" className={active ? "gitChangeRow active" : "gitChangeRow"} onClick={onSelect}>
      <span className={`gitChangeBadge status-${change.status}`}>{badge}</span>
      <span className="gitChangePath" title={change.path}>{change.path}</span>
    </button>
  );
}
