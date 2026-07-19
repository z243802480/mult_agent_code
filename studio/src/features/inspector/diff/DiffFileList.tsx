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

// Localize the "git unavailable" reason for the Chinese Changes pane. The BFF (studio/lib/git.mjs)
// returns the reason in English (e.g. "not a git repository") — the most common one, when the
// workspace was never `git init`-ed, was leaking English into the pane. A genuine git stderr (git
// installed but failing) is diagnostic and rare, so it passes through as-is.
export function gitUnavailableText(reason: string | null | undefined): string {
  const value = String(reason ?? "").trim();
  if (!value) return "该工作区不支持 Git。";
  if (/not a git repository/i.test(value)) {
    return "当前工作区还不是 Git 仓库——改动审查需要先在此目录执行 git init。";
  }
  return value;
}

export function DiffFileList({
  gitStatus,
  activeScope,
  selectedPath,
  onSelectChange,
  findingCounts = {},
}: {
  gitStatus: GitStatusPayload | null;
  activeScope: TurnDiffScope | undefined;
  selectedPath: string | null;
  onSelectChange: (path: string) => void;
  /** G5 AI 自审: per-file finding counts — rendered as a small badge on the file row. */
  findingCounts?: Record<string, number>;
}) {
  if (!gitStatus) {
    return <p className="muted">加载 git 状态中…</p>;
  }

  if (!gitStatus.available) {
    return <p className="muted">{gitUnavailableText(gitStatus.reason)}</p>;
  }

  return (
    <>
      {gitStatus.mode === "shadow" && (
        <p className="muted" role="note">
          非 Git 工作区——显示的是相对最近一次运行开始时的改动。
        </p>
      )}
      <ScopeChangeList
        gitStatus={gitStatus}
        activeScope={activeScope}
        selectedPath={selectedPath}
        onSelectChange={onSelectChange}
        findingCounts={findingCounts}
      />
    </>
  );
}

function ScopeChangeList({
  gitStatus,
  activeScope,
  selectedPath,
  onSelectChange,
  findingCounts = {},
}: {
  gitStatus: GitStatusPayload;
  activeScope: TurnDiffScope | undefined;
  selectedPath: string | null;
  onSelectChange: (path: string) => void;
  findingCounts?: Record<string, number>;
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
              findingCount={findingCounts[file.path] ?? 0}
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
          findingCount={findingCounts[change.path] ?? 0}
        />
      ))}
    </div>
  );
}

function GitChangeRow({
  change,
  active,
  onSelect,
  findingCount = 0,
}: {
  change: GitChangeEntry;
  active: boolean;
  onSelect: () => void;
  findingCount?: number;
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
      {findingCount > 0 && (
        <span className="gitChangeFindings" title={`AI 自审在这个文件发现 ${findingCount} 条问题`}>
          {findingCount}
        </span>
      )}
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
  findingCount = 0,
}: {
  path: string;
  badge: string;
  status: string;
  additions?: number;
  deletions?: number;
  active: boolean;
  onSelect: () => void;
  findingCount?: number;
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
      {findingCount > 0 && (
        <span className="gitChangeFindings" title={`AI 自审在这个文件发现 ${findingCount} 条问题`}>
          {findingCount}
        </span>
      )}
    </button>
  );
}

function basename(path: string): string {
  const parts = path.split(/[/\\]/);
  return parts[parts.length - 1] || path;
}
