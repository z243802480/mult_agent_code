import React from "react";
import type { GitChangeEntry, GitStatusPayload } from "../../../types";
import type { TurnDiffScope } from "../../../turnDiff";

const STATUS_LABEL: Record<string, string> = {
  modified: "M",
  added: "A",
  deleted: "D",
  untracked: "?",
  renamed: "R",
  changed: "~",
};

export function DiffFileList({
  gitStatus,
  activeScope,
  selectedPath,
  onSelectChange,
}: {
  gitStatus: GitStatusPayload | null;
  activeScope: TurnDiffScope | undefined;
  selectedPath: string | null;
  onSelectChange: (path: string) => void;
}) {
  if (!gitStatus) {
    return <p className="muted">加载 git 状态中…</p>;
  }

  if (!gitStatus.available) {
    return <p className="muted">{gitStatus.reason ?? "该工作区不支持 Git。"}</p>;
  }

  return (
    <ScopeChangeList
      gitStatus={gitStatus}
      activeScope={activeScope}
      selectedPath={selectedPath}
      onSelectChange={onSelectChange}
    />
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

  if (activeScope?.kind === "turn") {
    if (!activeScope.files.length) {
      return <p className="muted">本轮未记录文件改动。</p>;
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
    return <p className="muted">该工作区没有未提交的改动。</p>;
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
    <button
      type="button"
      className={active ? "gitChangeRow active" : "gitChangeRow"}
      onClick={onSelect}
    >
      <span className={`gitChangeBadge status-${change.status}`}>{badge}</span>
      <span className="gitChangePath" title={change.path}>
        {basename(change.path)}
      </span>
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
        {additions !== undefined && additions > 0 ? (
          <span className="deltaAdd">+{additions}</span>
        ) : null}
        {deletions !== undefined && deletions > 0 ? (
          <span className="deltaDel">-{deletions}</span>
        ) : null}
      </span>
    ) : null;

  return (
    <button
      type="button"
      className={active ? "gitChangeRow active" : "gitChangeRow"}
      onClick={onSelect}
    >
      <span className={`gitChangeBadge status-${status}`}>{badge}</span>
      <span className="gitChangePath" title={path}>
        {basename(path)}
      </span>
      {delta}
    </button>
  );
}

function basename(path: string): string {
  const parts = path.split(/[/\\]/);
  return parts[parts.length - 1] || path;
}
