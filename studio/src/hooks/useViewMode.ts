import React from "react";

export type StudioViewMode = "focus" | "normal" | "verbose";

const STORAGE_KEY = "asteria.studio.viewMode";
const ORDER: StudioViewMode[] = ["focus", "normal", "verbose"];

const LABELS: Record<StudioViewMode, string> = {
  focus: "Focus",
  normal: "Normal",
  verbose: "Verbose",
};

function loadMode(): StudioViewMode {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw === "focus" || raw === "normal" || raw === "verbose") return raw;
  } catch {
    // ignore
  }
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
