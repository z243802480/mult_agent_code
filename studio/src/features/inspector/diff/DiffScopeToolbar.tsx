import React from "react";
import { GitBranch, Loader2, RefreshCw, Sparkles } from "lucide-react";
import type { GitStatusPayload } from "../../../types";
import type { TurnDiffScope } from "../../../turnDiff";

export function DiffScopeToolbar({
  gitStatus,
  loading,
  scopes,
  activeScopeId,
  onSelectScope,
  onRefresh,
  onAiReview,
  aiReviewBusy = false,
  aiReviewPending = false,
}: {
  gitStatus: GitStatusPayload | null;
  loading: boolean;
  scopes: TurnDiffScope[];
  activeScopeId: string;
  onSelectScope: (scopeId: string) => void;
  onRefresh: () => void;
  /** G5: ask the model to review the current workspace diff (only reports high-signal problems). */
  onAiReview?: () => void;
  aiReviewBusy?: boolean;
  aiReviewPending?: boolean;
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
                {gitStatus.clean
                  ? "· 干净"
                  : `· ${gitStatus.change_count ?? gitStatus.changes?.length ?? 0} 处改动`}
              </span>
            </p>
          )}
        </div>
        <div className="gitChangesHeaderActions">
          {onAiReview && gitStatus?.available && !gitStatus.clean && (
            <button
              type="button"
              className="aiReviewButton"
              title={
                aiReviewBusy
                  ? "有任务在运行——等本轮结束后再自审。"
                  : "让模型评审当前改动，只报高信号问题"
              }
              onClick={onAiReview}
              disabled={aiReviewBusy || aiReviewPending}
            >
              {aiReviewPending ? (
                <Loader2 size={13} className="spinning" />
              ) : (
                <Sparkles size={13} />
              )}
              AI 自审
            </button>
          )}
          <button
            type="button"
            className="iconButton"
            title="刷新 git 状态"
            onClick={onRefresh}
            disabled={loading}
          >
            <RefreshCw size={14} className={loading ? "spinning" : ""} />
          </button>
        </div>
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
