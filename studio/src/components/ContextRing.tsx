import React from "react";
import type { ContextUsage } from "../features/inspector/inspectorUtils";

// Ambient context-usage ring (G2 — Claude Code keeps a usage ring next to the model selector;
// VS Code builds a context indicator into the prompt box). Renders ONLY when the run reported a
// usable ratio — the ring IS a ratio, token counts alone stay in the Inspector. All numbers are
// runtime estimates (no pricing data), so the tooltip says "est." and nothing is ever in currency.

function formatTokens(value: number | null): string {
  if (value === null) return "?";
  if (value >= 1000) return `${(value / 1000).toFixed(value >= 10000 ? 0 : 1)}k`;
  return String(value);
}

export function ContextRing({
  usage,
  onClick,
}: {
  usage: ContextUsage | null;
  onClick: () => void;
}) {
  if (!usage || usage.ratio === null) return null;
  const ratio = Math.min(1, Math.max(0, usage.ratio));
  const pct = Math.round(ratio * 100);
  const level = ratio >= 0.9 ? "critical" : ratio >= 0.75 ? "elevated" : "normal";
  const radius = 6.5;
  const circumference = 2 * Math.PI * radius;
  const tokens =
    usage.usedTokens !== null || usage.windowTokens !== null
      ? ` · ${formatTokens(usage.usedTokens)}/${formatTokens(usage.windowTokens)} tokens`
      : "";
  return (
    <button
      type="button"
      className={`contextRing ${level}`}
      title={`上下文占用 ~${pct}%${tokens}（est.）· 点击查看明细`}
      aria-label={`上下文占用约 ${pct}%，点击查看明细`}
      onClick={onClick}
    >
      <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
        <circle className="contextRingTrack" cx="8" cy="8" r={radius} />
        <circle
          className="contextRingFill"
          cx="8"
          cy="8"
          r={radius}
          strokeDasharray={`${circumference * ratio} ${circumference}`}
          transform="rotate(-90 8 8)"
        />
      </svg>
      <span className="contextRingPct">{pct}%</span>
    </button>
  );
}
