import React, { useState } from "react";
import { Check, Copy } from "lucide-react";

type Block =
  | { kind: "heading"; level: number; text: string }
  | { kind: "paragraph"; text: string }
  | { kind: "bullet"; text: string }
  | { kind: "ordered"; num: number; text: string }
  | { kind: "table"; header: string[]; rows: string[][] }
  | { kind: "code"; text: string };

// Split a GitHub-flavored pipe-table row into trimmed cells, tolerating optional leading/trailing pipes.
function splitTableRow(line: string): string[] {
  let s = line.trim();
  if (s.startsWith("|")) s = s.slice(1);
  if (s.endsWith("|")) s = s.slice(0, -1);
  return s.split("|").map((cell) => cell.trim());
}

function isSeparatorRow(line: string): boolean {
  if (!/-/.test(line)) return false;
  const cells = splitTableRow(line);
  return cells.length > 0 && cells.every((cell) => /^:?-{1,}:?$/.test(cell));
}

function isPipeRow(line: string): boolean {
  return line.includes("|");
}

function parseMarkdownBlocks(text: string): Block[] {
  const blocks: Block[] = [];
  const lines = String(text || "").split(/\r?\n/);
  let i = 0;
  let inCode = false;
  let codeLines: string[] = [];

  while (i < lines.length) {
    const raw = lines[i];
    if (raw.trim().startsWith("```")) {
      if (inCode) {
        blocks.push({ kind: "code", text: codeLines.join("\n") });
        codeLines = [];
        inCode = false;
      } else {
        inCode = true;
      }
      i += 1;
      continue;
    }
    if (inCode) {
      codeLines.push(raw);
      i += 1;
      continue;
    }
    // Table: a pipe row immediately followed by a separator row (| --- | :-: |), then body rows.
    if (isPipeRow(raw) && i + 1 < lines.length && isSeparatorRow(lines[i + 1])) {
      const header = splitTableRow(raw);
      i += 2;
      const rows: string[][] = [];
      while (
        i < lines.length &&
        lines[i].trim() &&
        isPipeRow(lines[i]) &&
        !isSeparatorRow(lines[i])
      ) {
        rows.push(splitTableRow(lines[i]));
        i += 1;
      }
      blocks.push({ kind: "table", header, rows });
      continue;
    }
    const heading = raw.match(/^(#{1,6})\s+(.+?)\s*$/);
    if (heading) {
      blocks.push({ kind: "heading", level: heading[1].length, text: heading[2].trim() });
      i += 1;
      continue;
    }
    const ordered = raw.match(/^\s*(\d+)\.\s+(.+)$/);
    if (ordered) {
      blocks.push({ kind: "ordered", num: Number(ordered[1]), text: ordered[2].trim() });
      i += 1;
      continue;
    }
    const bullet = raw.match(/^\s*[-*]\s+(.+)$/);
    if (bullet) {
      blocks.push({ kind: "bullet", text: bullet[1].trim() });
      i += 1;
      continue;
    }
    if (raw.trim()) {
      blocks.push({ kind: "paragraph", text: raw.trim() });
    }
    i += 1;
  }
  if (codeLines.length) blocks.push({ kind: "code", text: codeLines.join("\n") });
  return blocks;
}

function renderInline(text: string): React.ReactNode[] {
  const parts = text.split(/(`[^`]+`|\*\*[^*]+\*\*|\[[^\]]+\]\([^)]+\))/g);
  return parts.map((part, index) => {
    if (part.startsWith("`") && part.endsWith("`")) {
      return <code key={index}>{part.slice(1, -1)}</code>;
    }
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={index}>{part.slice(2, -2)}</strong>;
    }
    const link = part.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
    if (link) {
      const label = link[1];
      const url = link[2].trim();
      // Only follow safe schemes — never render javascript:/data: as a live link.
      if (/^(https?:\/\/|mailto:|\/|#)/i.test(url)) {
        return (
          <a key={index} href={url} target="_blank" rel="noopener noreferrer">
            {label}
          </a>
        );
      }
      return <React.Fragment key={index}>{label}</React.Fragment>;
    }
    return <React.Fragment key={index}>{part}</React.Fragment>;
  });
}

function CodeBlock({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard unavailable (headless / insecure context) — no-op */
    }
  }
  return (
    <div className="markdownCodeWrap">
      <button
        type="button"
        className="markdownCodeCopy"
        title="复制代码"
        aria-label="复制代码"
        onClick={() => void copy()}
      >
        {copied ? <Check size={12} /> : <Copy size={12} />}
        <span>{copied ? "已复制" : "复制"}</span>
      </button>
      <pre className="markdownCode">{text}</pre>
    </div>
  );
}

export function MarkdownBody({ text }: { text: string }) {
  const blocks = parseMarkdownBlocks(text);
  return (
    <div className="markdownBody">
      {blocks.map((block, index) => {
        if (block.kind === "heading") {
          if (block.level <= 2) return <h3 key={index}>{renderInline(block.text)}</h3>;
          return <h4 key={index}>{renderInline(block.text)}</h4>;
        }
        if (block.kind === "bullet") {
          return (
            <p key={index} className="finalBullet">
              {renderInline(block.text)}
            </p>
          );
        }
        if (block.kind === "ordered") {
          return (
            <p key={index} className="finalOrdered">
              <span className="finalOrderedNum">{block.num}.</span>
              {renderInline(block.text)}
            </p>
          );
        }
        if (block.kind === "table") {
          return (
            <div key={index} className="markdownTableWrap">
              <table className="markdownTable">
                <thead>
                  <tr>
                    {block.header.map((cell, c) => (
                      <th key={c}>{renderInline(cell)}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {block.rows.map((row, r) => (
                    <tr key={r}>
                      {row.map((cell, c) => (
                        <td key={c}>{renderInline(cell)}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          );
        }
        if (block.kind === "code") {
          return <CodeBlock key={index} text={block.text} />;
        }
        return <p key={index}>{renderInline(block.text)}</p>;
      })}
    </div>
  );
}
