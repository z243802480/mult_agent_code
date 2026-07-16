import React from "react";
import { Sparkles } from "lucide-react";
import type { FilePreview, GitDiffPayload } from "../../types";
import type { ReviewFinding } from "../../session/aiReview";
import { DiffPreview, type DiffLayout, type DiffStage } from "../../components/DiffPreview";
import { addDiffComment, removeDiffComment, useDiffComments } from "../../session/diffComments";

export type DiffPreviewSectionProps = {
  preview: FilePreview | null;
  gitSelectedPath: string | null;
  diffStage: DiffStage;
  diffLayout: DiffLayout;
  gitDiffPayload: GitDiffPayload | null;
  gitActionLoading: boolean;
  onSelectDiffStage: (stage: DiffStage) => void;
  onSelectDiffLayout: (layout: DiffLayout) => void;
  onStageFile: () => void;
  onDiscardFile: () => void;
  /** G5 AI 自审: the latest review round's findings for THIS file, listed above its diff. */
  findings?: ReviewFinding[];
};

export function DiffPreviewSection({
  preview,
  gitSelectedPath,
  diffStage,
  diffLayout,
  gitDiffPayload,
  gitActionLoading,
  onSelectDiffStage,
  onSelectDiffLayout,
  onStageFile,
  onDiscardFile,
  findings = [],
}: DiffPreviewSectionProps) {
  // G4 评论即指令: same shared store as the thread's inline diffs — hooks must run unconditionally.
  const allComments = useDiffComments();
  if (!preview) return null;
  const isDiff = Boolean(preview.path && (preview.content ?? "").includes("@@"));
  const pendingComments = allComments.filter((item) => item.file === preview.path);
  return (
    <section className="inspectorDiffPreview">
      {!isDiff && preview.ok && (
        <>
          <strong>{preview.path ?? "预览"}</strong>
          <pre className="filePreviewBody">{(preview.content ?? "").slice(0, 12000)}</pre>
        </>
      )}
      {!preview.ok && <p className="muted">{preview.error}</p>}
      {preview.ok && isDiff && (
        <>
          {findings.length > 0 && (
            <ul className="aiReviewFindingList" aria-label="AI 自审对这个文件的发现">
              {findings.map((finding, index) => (
                <li key={`${finding.line}-${index}`} className="aiReviewFinding">
                  <Sparkles size={12} />
                  <span className="aiReviewFindingLine">
                    {finding.line != null ? `第 ${finding.line} 行` : "文件级"}
                  </span>
                  <span className="aiReviewFindingNote">{finding.note}</span>
                </li>
              ))}
            </ul>
          )}
          <div className="diffViewControls">
            <div className="diffStageTabs" role="tablist" aria-label="改动暂存状态">
              {(["all", "staged", "unstaged"] as DiffStage[]).map((stage) => (
                <button
                  key={stage}
                  type="button"
                  role="tab"
                  className={diffStage === stage ? "diffStageTab active" : "diffStageTab"}
                  aria-selected={diffStage === stage}
                  onClick={() => onSelectDiffStage(stage)}
                >
                  {stage === "all" ? "全部" : stage === "staged" ? "已暂存" : "未暂存"}
                </button>
              ))}
            </div>
            <div className="diffLayoutTabs">
              <button
                type="button"
                className={diffLayout === "unified" ? "active" : ""}
                onClick={() => onSelectDiffLayout("unified")}
              >
                合并视图
              </button>
              <button
                type="button"
                className={diffLayout === "split" ? "active" : ""}
                onClick={() => onSelectDiffLayout("split")}
              >
                并排视图
              </button>
            </div>
          </div>
          <DiffPreview
            path={preview.path}
            diff={preview.content}
            staged={gitDiffPayload?.staged}
            unstaged={gitDiffPayload?.unstaged}
            stage={diffStage}
            layout={diffLayout}
            onStageFile={gitSelectedPath ? onStageFile : undefined}
            onDiscardFile={gitSelectedPath ? onDiscardFile : undefined}
            staging={gitActionLoading}
            comments={pendingComments}
            onAddComment={addDiffComment}
            onRemoveComment={removeDiffComment}
          />
        </>
      )}
    </section>
  );
}
