import React, { useMemo, useState } from "react";
import { MessageSquarePlus, X } from "lucide-react";
import type { DiffComment, DiffCommentAnchor } from "../session/diffComments";

type DiffLine = {
  kind: "add" | "del" | "hunk" | "meta" | "context";
  text: string;
  oldNo?: number;
  newNo?: number;
};

type SplitRow = {
  kind: "add" | "del" | "context" | "hunk" | "meta";
  left: string;
  right: string;
  oldNo?: number;
  newNo?: number;
};

export type DiffStage = "all" | "staged" | "unstaged";
export type DiffLayout = "unified" | "split";

function parseUnifiedDiff(text: string): DiffLine[] {
  const lines: DiffLine[] = [];
  let oldLine = 0;
  let newLine = 0;

  for (const raw of String(text || "").split(/\r?\n/)) {
    if (raw.startsWith("--- staged ---") || raw.startsWith("--- unstaged ---")) {
      lines.push({ kind: "meta", text: raw });
      continue;
    }
    if (
      raw.startsWith("diff --git") ||
      raw.startsWith("index ") ||
      raw.startsWith("new file mode")
    ) {
      lines.push({ kind: "meta", text: raw });
      continue;
    }
    if (raw.startsWith("+++ ") || raw.startsWith("--- ")) {
      lines.push({ kind: "meta", text: raw });
      continue;
    }
    if (raw.startsWith("@@")) {
      const match = raw.match(/@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/);
      if (match) {
        oldLine = Number(match[1]);
        newLine = Number(match[2]);
      }
      lines.push({ kind: "hunk", text: raw });
      continue;
    }
    if (raw.startsWith("+")) {
      lines.push({ kind: "add", text: raw, newNo: newLine });
      newLine += 1;
      continue;
    }
    if (raw.startsWith("-")) {
      lines.push({ kind: "del", text: raw, oldNo: oldLine });
      oldLine += 1;
      continue;
    }
    if (raw.startsWith(" ") || raw === "") {
      lines.push({ kind: "context", text: raw || " ", oldNo: oldLine, newNo: newLine });
      oldLine += 1;
      newLine += 1;
      continue;
    }
    lines.push({ kind: "context", text: raw });
  }
  return lines;
}

function toSplitRows(lines: DiffLine[]): SplitRow[] {
  const rows: SplitRow[] = [];
  for (const line of lines) {
    if (line.kind === "meta" || line.kind === "hunk") {
      rows.push({
        kind: line.kind,
        left: line.text,
        right: line.text,
        oldNo: line.oldNo,
        newNo: line.newNo,
      });
      continue;
    }
    if (line.kind === "del") {
      rows.push({ kind: "del", left: line.text.slice(1), right: "", oldNo: line.oldNo });
      continue;
    }
    if (line.kind === "add") {
      rows.push({ kind: "add", left: "", right: line.text.slice(1), newNo: line.newNo });
      continue;
    }
    const body = line.text.startsWith(" ") ? line.text.slice(1) : line.text;
    rows.push({ kind: "context", left: body, right: body, oldNo: line.oldNo, newNo: line.newNo });
  }
  return rows;
}

/**
 * The comment anchor a diff row can carry (G4 评论即指令): added/context lines anchor on the NEW
 * line number, deleted lines on the OLD one. Meta/hunk rows are not commentable.
 * Exported for tests (the test harness renders static markup, so anchoring is verified directly).
 */
export function rowAnchor(line: DiffLine, file: string): DiffCommentAnchor | null {
  if (line.kind === "meta" || line.kind === "hunk") return null;
  if (line.kind === "del") {
    return { file, line: line.oldNo ?? null, side: "old", excerpt: line.text };
  }
  const no = line.newNo ?? line.oldNo ?? null;
  return { file, line: no, side: line.newNo != null ? "new" : "old", excerpt: line.text };
}

function commentsForAnchor(
  comments: DiffComment[],
  anchor: DiffCommentAnchor | null,
): DiffComment[] {
  if (!anchor || anchor.line == null) return [];
  return comments.filter((item) => item.side === anchor.side && item.line === anchor.line);
}

function CommentEditor({
  onSave,
  onCancel,
}: {
  onSave: (text: string) => void;
  onCancel: () => void;
}) {
  const [draft, setDraft] = useState("");
  return (
    <div className="diffCommentEditor">
      <textarea
        autoFocus
        value={draft}
        placeholder="对这一行写意见…（Ctrl+Enter 保存）"
        rows={2}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
            e.preventDefault();
            if (draft.trim()) onSave(draft);
          }
          if (e.key === "Escape") onCancel();
        }}
      />
      <div className="diffCommentEditorActions">
        <button type="button" className="diffActionButton" onClick={onCancel}>
          取消
        </button>
        <button
          type="button"
          className="diffActionButton primary"
          disabled={!draft.trim()}
          onClick={() => onSave(draft)}
        >
          添加评论
        </button>
      </div>
    </div>
  );
}

function pickStageText(
  diff: string,
  staged?: string,
  unstaged?: string,
  stage: DiffStage = "all",
): string {
  if (stage === "staged") return staged ?? "";
  if (stage === "unstaged") return unstaged ?? "";
  if (staged && unstaged) return [staged, unstaged].filter(Boolean).join("\n\n--- unstaged ---\n");
  return diff;
}

export function DiffPreview({
  path,
  diff,
  staged,
  unstaged,
  stage = "all",
  layout = "unified",
  error,
  maxLines = 400,
  onStageFile,
  onDiscardFile,
  staging = false,
  comments = [],
  onAddComment,
  onRemoveComment,
}: {
  path?: string;
  diff?: string;
  staged?: string;
  unstaged?: string;
  stage?: DiffStage;
  layout?: DiffLayout;
  error?: string;
  maxLines?: number;
  onStageFile?: () => void;
  onDiscardFile?: () => void;
  staging?: boolean;
  /** Pending line comments for THIS file (G4). Rendered under their anchored rows (unified layout). */
  comments?: DiffComment[];
  /** Enables the per-line comment affordance; needs `path` to build the anchor. */
  onAddComment?: (anchor: DiffCommentAnchor, text: string) => void;
  onRemoveComment?: (id: string) => void;
}) {
  const [editorAt, setEditorAt] = useState<number | null>(null);
  const stageText = pickStageText(diff ?? "", staged, unstaged, stage);
  const lines = useMemo(() => parseUnifiedDiff(stageText), [stageText]);
  const splitRows = useMemo(() => toSplitRows(lines), [lines]);
  const clipped = lines.length > maxLines;
  const visibleLines = clipped ? lines.slice(0, maxLines) : lines;
  const visibleSplit = clipped ? splitRows.slice(0, maxLines) : splitRows;

  if (error) {
    return <p className="diffPreviewError">{error}</p>;
  }
  if (!stageText.trim()) {
    return <p className="muted">此视图暂无改动内容。</p>;
  }

  return (
    <div className="diffPreview">
      <div className="diffPreviewToolbar">
        {path && <div className="diffPreviewPath">{path}</div>}
        <div className="diffPreviewActions">
          {onStageFile && (
            <button
              type="button"
              className="diffActionButton"
              disabled={staging}
              onClick={onStageFile}
            >
              暂存文件
            </button>
          )}
          {onDiscardFile && (
            <button
              type="button"
              className="diffActionButton danger"
              disabled={staging}
              onClick={onDiscardFile}
            >
              丢弃改动
            </button>
          )}
        </div>
      </div>
      {layout === "split" ? (
        <div className="diffSplitTable" role="region" aria-label="并排显示的 git diff">
          <div className="diffSplitHeader">
            <span>修改前</span>
            <span>修改后</span>
          </div>
          {visibleSplit.map((row, index) => (
            <div key={`${index}-${row.kind}`} className={`diffSplitRow kind-${row.kind}`}>
              <div className="diffSplitCell">
                <span className="diffGutter old">{row.oldNo ?? ""}</span>
                <code>{row.left}</code>
              </div>
              <div className="diffSplitCell">
                <span className="diffGutter new">{row.newNo ?? ""}</span>
                <code>{row.right}</code>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="diffPreviewTable" role="region" aria-label="Git diff（差异）">
          {visibleLines.map((line, index) => {
            const anchor = path && onAddComment ? rowAnchor(line, path) : null;
            const canComment = Boolean(anchor && anchor.line != null);
            const lineComments = commentsForAnchor(comments, anchor);
            return (
              <React.Fragment key={`${index}-${line.kind}`}>
                <div
                  className={`diffPreviewRow kind-${line.kind}${canComment ? " commentable" : ""}`}
                >
                  <span className="diffGutter old">{line.oldNo ?? ""}</span>
                  <span className="diffGutter new">{line.newNo ?? ""}</span>
                  <code className="diffLineText">{line.text || " "}</code>
                  {canComment && (
                    <button
                      type="button"
                      className="diffCommentAdd"
                      title="对此行添加评论"
                      aria-label={`对第 ${anchor?.line} 行添加评论`}
                      onClick={() => setEditorAt(editorAt === index ? null : index)}
                    >
                      <MessageSquarePlus size={12} />
                    </button>
                  )}
                </div>
                {lineComments.map((item) => (
                  <div key={item.id} className="diffCommentCard">
                    <span className="diffCommentText">{item.text}</span>
                    {onRemoveComment && (
                      <button
                        type="button"
                        className="diffCommentRemove"
                        title="删除这条评论"
                        aria-label="删除这条评论"
                        onClick={() => onRemoveComment(item.id)}
                      >
                        <X size={12} />
                      </button>
                    )}
                  </div>
                ))}
                {editorAt === index && anchor && (
                  <CommentEditor
                    onSave={(text) => {
                      onAddComment?.(anchor, text);
                      setEditorAt(null);
                    }}
                    onCancel={() => setEditorAt(null)}
                  />
                )}
              </React.Fragment>
            );
          })}
        </div>
      )}
      {clipped && <p className="diffPreviewTruncated">仅显示前 {maxLines} 行差异。</p>}
    </div>
  );
}
