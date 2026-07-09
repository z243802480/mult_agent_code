import React, { useMemo, useState } from "react";
import { Copy, Check } from "lucide-react";

export function ClampedOutput({
  text,
  className,
  maxLines = 8,
  defaultExpanded = false,
}: {
  text: string;
  className?: string;
  maxLines?: number;
  defaultExpanded?: boolean;
}) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const [copied, setCopied] = useState(false);
  const trimmed = String(text ?? "").trim();
  const lineCount = useMemo(() => trimmed.split(/\r?\n/).length, [trimmed]);
  const long = lineCount > maxLines || trimmed.length > 480;

  if (!trimmed) return null;

  async function copyText(event: React.MouseEvent) {
    event.stopPropagation();
    try {
      await navigator.clipboard.writeText(trimmed);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard unavailable */
    }
  }

  return (
    <div
      className={[
        "clampedOutput",
        long ? "clamped" : "",
        expanded ? "expanded" : "",
        className ?? "",
      ]
        .filter(Boolean)
        .join(" ")}
      style={{ ["--clamp-lines" as string]: String(maxLines) }}
    >
      <pre>{trimmed}</pre>
      <div className="clampedOutputActions">
        <button
          type="button"
          className="clampedOutputCopy"
          onClick={(event) => void copyText(event)}
        >
          {copied ? <Check size={12} /> : <Copy size={12} />}
          <span>{copied ? "已复制" : "复制"}</span>
        </button>
        {long && (
          <button
            type="button"
            className="clampedOutputToggle"
            onClick={(event) => {
              event.stopPropagation();
              setExpanded((value) => !value);
            }}
          >
            {expanded ? "收起" : `展开更多（共 ${lineCount} 行）`}
          </button>
        )}
      </div>
    </div>
  );
}
