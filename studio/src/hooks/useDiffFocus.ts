import React from "react";

const STORAGE_KEY = "asteria.studio.diffFocus";

function loadDiffFocus(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

function saveDiffFocus(active: boolean) {
  try {
    localStorage.setItem(STORAGE_KEY, active ? "1" : "0");
  } catch {
    // ignore
  }
}

export function useDiffFocus() {
  const [diffFocus, setDiffFocusState] = React.useState(() => loadDiffFocus());

  function setDiffFocus(active: boolean) {
    setDiffFocusState(active);
    saveDiffFocus(active);
  }

  const toggleDiffFocus = React.useCallback(() => {
    setDiffFocusState((current) => {
      const next = !current;
      saveDiffFocus(next);
      return next;
    });
  }, []);

  return { diffFocus, setDiffFocus, toggleDiffFocus };
}
