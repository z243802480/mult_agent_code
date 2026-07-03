import React, { useState } from "react";
import { Check, Copy } from "lucide-react";

type Block =
  | { kind: "heading"; level: number; text: string }
  | { kind: "paragraph"; text: string }
  | { kind: "bullet"; text: string }
  | { kind: "code"; text: string };

function parseMarkdownBlocks(text: string): Block[] {
  const blocks: Block[] = [];
  let inCode = false;
  let codeLines: string[] = [];

  for (const raw of String(text || "").split(/\r?\n/)) {
    if (raw.trim().startsWith("```")) {
      if (inCode) {
        blocks.push({ kind: "code", text: codeLines.join("\n") });
        codeLines = [];
        inCode = false;
      } else {
        inCode = true;
      }
      continue;
    }
    if (inCode) {
      codeLines.push(raw);
      continue;
    }
    const heading = raw.match(/^(#{1,6})\s+(.+?)\s*$/);
    if (heading) {
      blocks.push({ kind: "heading", level: heading[1].length, text: heading[2].trim() });
      continue;
    }
    const bullet = raw.match(/^\s*[-*]\s+(.+)$/);
    if (bullet) {
      blocks.push({ kind: "bullet", text: bullet[1].trim() });
      continue;
    }
    if (raw.trim()) {
      blocks.push({ kind: "paragraph", text: raw.trim() });
    }
  }
  if (codeLines.length) blocks.push({ kind: "code", text: codeLines.join("\n") });
  return blocks;
}

function renderInline(text: string): React.ReactNode[] {
  const parts = text.split(/(`[^`]+`|\*\*[^*]+\*\*)/g);
  return parts.map((part, index) => {
    if (part.startsWith("`") && part.endsWith("`")) {
      return <code key={index}>{part.slice(1, -1)}</code>;
    }
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={index}>{part.slice(2, -2)}</strong>;
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
        title="Copy code"
        aria-label="Copy code"
        onClick={() => void copy()}
      >
        {copied ? <Check size={12} /> : <Copy size={12} />}
        <span>{copied ? "Copied" : "Copy"}</span>
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
          return <p key={index} className="finalBullet">{renderInline(block.text)}</p>;
        }
        if (block.kind === "code") {
          return <CodeBlock key={index} text={block.text} />;
        }
        return <p key={index}>{renderInline(block.text)}</p>;
      })}
    </div>
  );
}
