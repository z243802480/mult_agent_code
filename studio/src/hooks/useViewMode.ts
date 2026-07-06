import React from "react";

export type StudioViewMode = "focus" | "normal" | "verbose";

const STORAGE_KEY = "asteria.studio.viewMode";
const ORDER: StudioViewMode[] = ["focus", "normal", "verbose"];

const LABELS: Record<StudioViewMode, string> = {
  focus: "专注",
  normal: "常规",
  verbose: "详尽",
};

function loadMode(): StudioViewMode {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw === "focus" || raw === "normal" || raw === "verbose") return raw;
  } catch {
    // ignore
  }
  // ADR-0021: process-visible-by-default. The loop's own lifecycle wrappers (turn_start/turn_end/
  // tool_observation → "Agent 回合"/"工具结果") are now demoted to the Inspector, and each real tool
  // renders as a single card carrying its true target ("写入 square.py", "$ pytest …"). So "normal"
  // is a clean, real process stream — the default. "focus" remains for a deliberately minimal view.
  return "normal";
}

function saveMode(mode: StudioViewMode) {
  try {
    localStorage.setItem(STORAGE_KEY, mode);
  } catch {
    // ignore
  }
}

export function viewModeLabel(mode: StudioViewMode): string {
  return LABELS[mode];
}

export function useViewMode() {
  const [viewMode, setViewModeState] = React.useState<StudioViewMode>(() => loadMode());

  function setViewMode(mode: StudioViewMode) {
    setViewModeState(mode);
    saveMode(mode);
  }

  function cycleViewMode() {
    setViewModeState((current) => {
      const index = ORDER.indexOf(current);
      const next = ORDER[(index + 1) % ORDER.length];
      saveMode(next);
      return next;
    });
  }

  return { viewMode, setViewMode, cycleViewMode };
}
