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
  // NOTE (ADR-0021): the goal is process-visible-by-default ("normal"), but non-focus modes still
  // surface internal lifecycle steps masquerading as tool cards ("工具结果"/"已选择权限模式"/"Starting").
  // Flip the default to "normal" only after slice 2 cleans that noise, so the default view is real
  // process — not a noisy dump. Until then keep "focus" as the default.
  return "focus";
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
