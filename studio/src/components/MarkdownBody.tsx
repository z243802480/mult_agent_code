import React, { useState } from "react";
import { Check, Copy } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

// Full GFM rendering (react-markdown + remark-gfm) instead of the previous hand-rolled line parser.
// The hand parser flattened every heading to h3/h4, faked lists as <p> rows (no nesting, no
// multi-line items), and rendered `---`, `> quote` and *emphasis* as literal text — the main-thread
// answer read a tier below Claude Code / ChatGPT. Mainstream correctness is exactly the case for a
// battle-tested parser (reference-first: don't reinvent wheels).
// Safety posture is unchanged: react-markdown never renders raw HTML without rehype-raw (we don't
// add it), and its default urlTransform drops javascript:/data: link targets — the same guard the
// old renderer applied by hand.

function flattenToText(node: React.ReactNode): string {
  if (node == null || typeof node === "boolean") return "";
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(flattenToText).join("");
  if (React.isValidElement<{ children?: React.ReactNode }>(node)) {
    return flattenToText(node.props.children);
  }
  return "";
}

// Hover-revealed copy button on code blocks (mainstream: ChatGPT/Claude/Cursor).
function CodeBlockPre({ children }: { children?: React.ReactNode }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(flattenToText(children).replace(/\n$/, ""));
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
      <pre className="markdownCode">{children}</pre>
    </div>
  );
}

const components = {
  pre: CodeBlockPre,
  // Wide tables horizontal-scroll inside their own container so they never break the thread layout.
  table: (props: React.TableHTMLAttributes<HTMLTableElement>) => (
    <div className="markdownTableWrap">
      <table className="markdownTable" {...props} />
    </div>
  ),
  a: (props: React.AnchorHTMLAttributes<HTMLAnchorElement>) => (
    <a target="_blank" rel="noopener noreferrer" {...props} />
  ),
};

export function MarkdownBody({ text }: { text: string }) {
  return (
    <div className="markdownBody">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {String(text || "")}
      </ReactMarkdown>
    </div>
  );
}
