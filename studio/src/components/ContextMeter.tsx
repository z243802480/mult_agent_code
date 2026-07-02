import React from "react";
import { Gauge } from "lucide-react";
import type { ContextUsage } from "../features/inspector/inspectorUtils";

function fmt(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(n >= 10_000 ? 0 : 1)}k`;
  return String(Math.round(n));
}

// Glanceable, honest context-window meter (I4). Fills proportionally to the estimated context ratio,
// turns amber past the compaction threshold (0.75, matching policy), and labels tokens "(est.)".
// Never shows a monetary cost. The parent only renders it when readContextUsage returned data.
export function ContextMeter({ usage }: { usage: ContextUsage }) {
  const ratio = usage.ratio != null ? Math.max(0, Math.min(1, usage.ratio)) : null;
  const warn = ratio != null && ratio >= 0.75;
  const pct = ratio != null ? Math.round(ratio * 100) : null;
  const io = [
    usage.inputTokens != null ? `${fmt(usage.inputTokens)} in` : null,
    usage.outputTokens != null ? `${fmt(usage.outputTokens)} out` : null,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <div
      className={`contextMeter ${warn ? "warn" : ""}`}
      title="Estimated context-window usage (not billed). Turns amber near the compaction threshold."
    >
      <Gauge size={12} className="contextMeterIcon" />
      {ratio != null && (
        <span className="contextMeterBar">
          <span className="contextMeterFill" style={{ width: `${Math.round(ratio * 100)}%` }} />
        </span>
      )}
      <span className="contextMeterText">
        {pct != null ? `${pct}% context` : "context"}
        {usage.usedTokens != null && usage.windowTokens ? ` · ${fmt(usage.usedTokens)}/${fmt(usage.windowTokens)}` : ""}
        {io ? ` · ${io} (est.)` : " (est.)"}
      </span>
    </div>
  );
}
