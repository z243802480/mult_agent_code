import React, { useMemo, useState } from "react";

export function ClampedOutput({
  text,
  className,
  maxLines = 5,
}: {
  text: string;
  className?: string;
  maxLines?: number;
}) {
  const [expanded, setExpanded] = useState(false);
  const trimmed = String(text ?? "").trim();
  const lineCount = useMemo(() => trimmed.split(/\r?\n/).length, [trimmed]);
  const long = lineCount > maxLines || trimmed.length > 360;

  if (!trimmed) return null;

  return (
    <div
      className={[
        "clampedOutput",
        long ? "clamped" : "",
        expanded ? "expanded" : "",
        className ?? "",
      ].filter(Boolean).join(" ")}
      style={{ ["--clamp-lines" as string]: String(maxLines) }}
    >
      <pre>{trimmed}</pre>
      {long && (
        <button
          type="button"
          className="clampedOutputToggle"
          onClick={(event) => {
            event.stopPropagation();
            setExpanded((value) => !value);
          }}
        >
          {expanded ? "Show less" : `Show more (${lineCount} lines)`}
        </button>
      )}
    </div>
  );
}
