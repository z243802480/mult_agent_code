import React, { useState } from "react";
import { ChevronRight } from "lucide-react";
import { api } from "../../api";
import type { GitDiffPayload } from "../../types";
import { DiffPreview } from "../../components/DiffPreview";
import { fileChangeBasename } from "../../fileChanges";
import { gitUnavailableText } from "../inspector/diff/DiffFileList";
import { addDiffComment, removeDiffComment, useDiffComments } from "../../session/diffComments";

const OPERATION_BADGE: Record<string, string> = {
  create: "新增",
  created: "新增",
  add: "新增",
  write: "写入",
  modify: "修改",
  modified: "修改",
  edit: "修改",
  update: "修改",
  delete: "删除",
  deleted: "删除",
  remove: "删除",
};

function operationLabel(operation?: string): string {
  const key = String(operation ?? "").toLowerCase();
  return OPERATION_BADGE[key] ?? "改动";
}

/**
 * A changed file the model touched, expandable to show its diff INLINE — no trip to the Inspector.
 * This is the Claude Code / Cursor-in-chat affordance: read the edit right where it happened. The
 * diff is fetched lazily on first expand (the working-tree git diff for this path) and cached, so a
 * long turn with many files stays cheap until you actually open one. Collapsed by default keeps the
 * thread compact; the consolidated Changes pane still exists for reviewing everything at once.
 */
export function InlineFileDiff({
  path,
  additions,
  deletions,
  operation,
}: {
  path: string;
  additions?: number;
  deletions?: number;
  operation?: string;
}) {
  const [open, setOpen] = useState(false);
  const [payload, setPayload] = useState<GitDiffPayload | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // G4 评论即指令: pending line comments live in the shared per-session store — the inline diff and
  // the Inspector pane see the same list, and the tray above the composer submits them all at once.
  const pendingComments = useDiffComments().filter((item) => item.file === path);

  async function toggle() {
    const next = !open;
    setOpen(next);
    if (next && !payload && !loading) {
      setLoading(true);
      setError(null);
      try {
        const result = await api.gitDiff(path, "all");
        if (result.ok) {
          setPayload(result);
        } else {
          // The BFF returns git errors in English (e.g. "not a git repository" when the workspace was
          // never `git init`-ed). Localize to an actionable Chinese message, same guard as the pane.
          setError(gitUnavailableText(result.error));
        }
      } catch {
        setError("无法加载这个文件的改动——请重试。");
      } finally {
        setLoading(false);
      }
    }
  }

  return (
    <div className={`inlineFileDiff${open ? " open" : ""}`}>
      <button type="button" className="inlineFileDiffHead" onClick={toggle} aria-expanded={open}>
        <ChevronRight size={13} className={`chevron ${open ? "open" : ""}`} />
        <span className="inlineFileDiffOp">{operationLabel(operation)}</span>
        <span className="inlineFileDiffPath" title={path}>
          {fileChangeBasename(path)}
        </span>
        <span className="inlineFileDiffDelta">
          {additions !== undefined && additions > 0 ? (
            <span className="deltaAdd">+{additions}</span>
          ) : null}
          {deletions !== undefined && deletions > 0 ? (
            <span className="deltaDel">-{deletions}</span>
          ) : null}
        </span>
      </button>
      {open && (
        <div className="inlineFileDiffBody">
          {loading && <p className="muted">加载改动…</p>}
          {error && <p className="muted">{error}</p>}
          {payload && !loading && (
            <DiffPreview
              path={path}
              diff={payload.diff}
              staged={payload.staged}
              unstaged={payload.unstaged}
              stage="all"
              layout="unified"
              comments={pendingComments}
              onAddComment={addDiffComment}
              onRemoveComment={removeDiffComment}
            />
          )}
          {payload &&
            !loading &&
            !error &&
            !(payload.diff || payload.staged || payload.unstaged) && (
              <p className="muted">没有可显示的文本改动(可能是二进制文件或已提交)。</p>
            )}
        </div>
      )}
    </div>
  );
}
