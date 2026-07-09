import React, { useMemo } from "react";

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
}) {
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
          {visibleLines.map((line, index) => (
            <div key={`${index}-${line.kind}`} className={`diffPreviewRow kind-${line.kind}`}>
              <span className="diffGutter old">{line.oldNo ?? ""}</span>
              <span className="diffGutter new">{line.newNo ?? ""}</span>
              <code className="diffLineText">{line.text || " "}</code>
            </div>
          ))}
        </div>
      )}
      {clipped && <p className="diffPreviewTruncated">仅显示前 {maxLines} 行差异。</p>}
    </div>
  );
}
