import React from "react";
import { GitBranch, RefreshCw } from "lucide-react";
import type { GitStatusPayload } from "../../../types";
import type { TurnDiffScope } from "../../../turnDiff";

export function DiffScopeToolbar({
  gitStatus,
  loading,
  scopes,
  activeScopeId,
  onSelectScope,
  onRefresh,
}: {
  gitStatus: GitStatusPayload | null;
  loading: boolean;
  scopes: TurnDiffScope[];
  activeScopeId: string;
  onSelectScope: (scopeId: string) => void;
  onRefresh: () => void;
}) {
  const activeScope = scopes.find((scope) => scope.id === activeScopeId) ?? scopes[0];
  const turnScopes = scopes.filter((scope) => scope.kind === "turn");

  return (
    <>
      <div className="gitChangesHeader">
        <div>
          <h2>改动查看</h2>
          {gitStatus?.available && (
            <p className="gitBranchLine">
              <GitBranch size={13} />
              <span>{gitStatus.branch ?? "HEAD"}</span>
              <span className="muted">
                {gitStatus.clean ? "· 干净" : `· ${gitStatus.change_count ?? gitStatus.changes?.length ?? 0} 处改动`}
              </span>
            </p>
          )}
        </div>
        <button type="button" className="iconButton" title="刷新 git 状态" onClick={onRefresh} disabled={loading}>
          <RefreshCw size={14} className={loading ? "spinning" : ""} />
        </button>
      </div>

      <div className="diffScopeTabs" role="tablist" aria-label="改动范围">
        <button
          type="button"
          role="tab"
          className={activeScopeId === "current" ? "diffScopeTab active" : "diffScopeTab"}
          aria-selected={activeScopeId === "current"}
          onClick={() => onSelectScope("current")}
        >
          当前
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
          本轮目标: {activeScope.userPreview}
        </p>
      )}
    </>
  );
}
