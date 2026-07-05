import React from "react";
import type { FilePreview, GitDiffPayload, GitStatusPayload } from "../../types";
import type { DiffLayout, DiffStage } from "../../components/DiffPreview";
import type { TurnDiffScope } from "../../turnDiff";
import { DiffScopeToolbar } from "./diff/DiffScopeToolbar";
import { DiffFileList } from "./diff/DiffFileList";
import { DiffPreviewSection } from "./DiffPreviewSection";

export type DiffReviewPaneProps = {
  gitStatus: GitStatusPayload | null;
  gitLoading: boolean;
  gitSelectedPath: string | null;
  diffScopes: TurnDiffScope[];
  diffScopeId: string;
  onSelectDiffScope: (scopeId: string) => void;
  onRefreshGit: () => void;
  onSelectGitChange: (path: string) => void;
  preview: FilePreview | null;
  diffStage: DiffStage;
  diffLayout: DiffLayout;
  gitDiffPayload: GitDiffPayload | null;
  gitActionLoading: boolean;
  onSelectDiffStage: (stage: DiffStage) => void;
  onSelectDiffLayout: (layout: DiffLayout) => void;
  onStageFile: () => void;
  onDiscardFile: () => void;
};

export function DiffReviewPane({
  gitStatus,
  gitLoading,
  gitSelectedPath,
  diffScopes,
  diffScopeId,
  onSelectDiffScope,
  onRefreshGit,
  onSelectGitChange,
  preview,
  diffStage,
  diffLayout,
  gitDiffPayload,
  gitActionLoading,
  onSelectDiffStage,
  onSelectDiffLayout,
  onStageFile,
  onDiscardFile,
}: DiffReviewPaneProps) {
  const activeScope = diffScopes.find((scope) => scope.id === diffScopeId) ?? diffScopes[0];

  return (
    <section className="diffReviewPane gitChangesPanel">
      <DiffScopeToolbar
        gitStatus={gitStatus}
        loading={gitLoading}
        scopes={diffScopes}
        activeScopeId={diffScopeId}
        onSelectScope={onSelectDiffScope}
        onRefresh={onRefreshGit}
      />
      <div className="diffReviewBody">
        <div className="diffReviewFiles">
          <DiffFileList
            gitStatus={gitStatus}
            activeScope={activeScope}
            selectedPath={gitSelectedPath}
            onSelectChange={onSelectGitChange}
          />
        </div>
        <div className="diffReviewPreview">
          {preview ? (
            <DiffPreviewSection
              preview={preview}
              gitSelectedPath={gitSelectedPath}
              diffStage={diffStage}
              diffLayout={diffLayout}
              gitDiffPayload={gitDiffPayload}
              gitActionLoading={gitActionLoading}
              onSelectDiffStage={onSelectDiffStage}
              onSelectDiffLayout={onSelectDiffLayout}
              onStageFile={onStageFile}
              onDiscardFile={onDiscardFile}
            />
          ) : (
            <div className="diffReviewPreviewEmpty">
              <p className="muted">选择一个文件以查看改动。</p>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
