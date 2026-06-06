import React from "react";
import { GitBranch, RefreshCw } from "lucide-react";
import type { GitChangeEntry, GitStatusPayload } from "../types";
import type { TurnDiffScope } from "../turnDiff";

const STATUS_LABEL: Record<string, string> = {
  modified: "M",
  added: "A",
  deleted: "D",
  untracked: "?",
  renamed: "R",
  changed: "~",
};

export function DiffScopePanel({
  gitStatus,
  loading,
  selectedPath,
  scopes,
  activeScopeId,
  onSelectScope,
  onRefresh,
  onSelectChange,
}: {
  gitStatus: GitStatusPayload | null;
  loading: boolean;
  selectedPath: string | null;
  scopes: TurnDiffScope[];
  activeScopeId: string;
  onSelectScope: (scopeId: string) => void;
  onRefresh: () => void;
  onSelectChange: (path: string) => void;
}) {
  const activeScope = scopes.find((scope) => scope.id === activeScopeId) ?? scopes[0];
  const turnScopes = scopes.filter((scope) => scope.kind === "turn");

  if (!gitStatus) {
    return (
      <section className="gitChangesPanel">
        <div className="gitChangesHeader">
          <h2>Diff review</h2>
          <button type="button" className="iconButton" title="Refresh git status" onClick={onRefresh} disabled={loading}>
            <RefreshCw size={14} className={loading ? "spinning" : ""} />
          </button>
        </div>
        <p className="muted">Loading git status…</p>
      </section>
    );
  }

  return (
    <section className="gitChangesPanel">
      <div className="gitChangesHeader">
        <div>
          <h2>Diff review</h2>
          {gitStatus.available && (
            <p className="gitBranchLine">
              <GitBranch size={13} />
              <span>{gitStatus.branch ?? "HEAD"}</span>
              <span className="muted">
                {gitStatus.clean ? "· clean" : `· ${gitStatus.change_count ?? gitStatus.changes?.length ?? 0} changed`}
              </span>
            </p>
          )}
        </div>
        <button type="button" className="iconButton" title="Refresh git status" onClick={onRefresh} disabled={loading}>
          <RefreshCw size={14} className={loading ? "spinning" : ""} />
        </button>
      </div>

      <div className="diffScopeTabs" role="tablist" aria-label="Diff scope">
        <button
          type="button"
          role="tab"
          className={activeScopeId === "current" ? "diffScopeTab active" : "diffScopeTab"}
          aria-selected={activeScopeId === "current"}
          onClick={() => onSelectScope("current")}
        >
          Current
        </button>
        {turnScopes.map((scope) => (
          <button
            key={scope.id}
            type="button"
            role="tab"
            className={activeScopeId === scope.id ? "diffScopeTab active" : "diffScopeTab"}
            aria-selected={activeScopeId === scope.id}
            title={scope.userPreview}
            onClick={() => onSelectScope(scope.id)}
          >
            {scope.label}
            <span className="diffScopeCount">{scope.files.length}</span>
          </button>
        ))}
      </div>

      {activeScope?.kind === "turn" && activeScope.userPreview && (
        <p className="diffScopeHint" title={activeScope.userPreview}>
          Turn goal: {activeScope.userPreview}
        </p>
      )}

      {!gitStatus.available ? (
        <p className="muted">{gitStatus.reason ?? "Git is not available for this workspace."}</p>
      ) : (
        <ScopeChangeList
          gitStatus={gitStatus}
          activeScope={activeScope}
          selectedPath={selectedPath}
          onSelectChange={onSelectChange}
        />
      )}
    </section>
  );
}

function ScopeChangeList({
  gitStatus,
  activeScope,
  selectedPath,
  onSelectChange,
}: {
  gitStatus: GitStatusPayload;
  activeScope: TurnDiffScope | undefined;
  selectedPath: string | null;
  onSelectChange: (path: string) => void;
}) {
  const gitChanges = gitStatus.changes ?? [];
  const scopePaths = new Set((activeScope?.files ?? []).map((file) => file.path));

  if (activeScope?.kind === "turn") {
    if (!activeScope.files.length) {
      return <p className="muted">No file changes recorded for this turn.</p>;
    }
    return (
      <div className="gitChangeList">
        {activeScope.files.map((file) => {
          const gitChange = gitChanges.find((change) => change.path === file.path);
          return (
            <TurnScopeRow
              key={file.path}
              path={file.path}
              badge={gitChange ? (STATUS_LABEL[gitChange.status] ?? "~") : "·"}
              status={gitChange?.status ?? "artifact"}
              additions={file.additions}
              deletions={file.deletions}
              active={selectedPath === file.path}
              onSelect={() => onSelectChange(file.path)}
            />
          );
        })}
      </div>
    );
  }

  if (gitChanges.length === 0) {
    return <p className="muted">No uncommitted changes in this workspace.</p>;
  }

  return (
    <div className="gitChangeList">
      {gitChanges.map((change) => (
        <GitChangeRow
          key={change.path}
          change={change}
          active={selectedPath === change.path}
          onSelect={() => onSelectChange(change.path)}
        />
      ))}
    </div>
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

function TurnScopeRow({
  path,
  badge,
  status,
  additions,
  deletions,
  active,
  onSelect,
}: {
  path: string;
  badge: string;
  status: string;
  additions?: number;
  deletions?: number;
  active: boolean;
  onSelect: () => void;
}) {
  const delta =
    additions !== undefined || deletions !== undefined ? (
      <span className="gitChangeDelta">
        {additions !== undefined && additions > 0 ? <span className="deltaAdd">+{additions}</span> : null}
        {deletions !== undefined && deletions > 0 ? <span className="deltaDel">-{deletions}</span> : null}
      </span>
    ) : null;

  return (
    <button type="button" className={active ? "gitChangeRow active" : "gitChangeRow"} onClick={onSelect}>
      <span className={`gitChangeBadge status-${status}`}>{badge}</span>
      <span className="gitChangePath" title={path}>{path}</span>
      {delta}
    </button>
  );
}
