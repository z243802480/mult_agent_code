import React from "react";
import type { SessionListFilter } from "../features/sidebar/sessionListUtils";

const STORAGE_KEY = "asteria.studio.sessionFilter";

function loadFilter(): SessionListFilter {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw === "all" || raw === "recent") return raw;
  } catch {
    // ignore
  }
  return "all";
}

function saveFilter(filter: SessionListFilter) {
  try {
    localStorage.setItem(STORAGE_KEY, filter);
  } catch {
    // ignore
  }
}

export function useSessionListFilter() {
  const [filter, setFilterState] = React.useState<SessionListFilter>(() => loadFilter());

  function setFilter(next: SessionListFilter) {
    setFilterState(next);
    saveFilter(next);
  }

  return { filter, setFilter };
}
