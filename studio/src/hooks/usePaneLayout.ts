import React from "react";

const STORAGE_KEY = "asteria.studio.paneLayout";
const SIDEBAR_MIN = 180;
const SIDEBAR_MAX = 340;
const SIDEBAR_RAIL = 52;
const PANEL_MIN = 240;
const PANEL_MAX = 520;

type PaneLayout = {
  sidebar: number;
  panel: number;
  sidebarCollapsed?: boolean;
};

function loadLayout(): Required<PaneLayout> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return { sidebar: 220, panel: 300, sidebarCollapsed: false };
    const parsed = JSON.parse(raw) as Partial<PaneLayout>;
    return {
      sidebar: clamp(Number(parsed.sidebar) || 220, SIDEBAR_MIN, SIDEBAR_MAX),
      panel: clamp(Number(parsed.panel) || 300, PANEL_MIN, PANEL_MAX),
      sidebarCollapsed: Boolean(parsed.sidebarCollapsed),
    };
  } catch {
    return { sidebar: 220, panel: 300, sidebarCollapsed: false };
  }
}

function saveLayout(layout: Required<PaneLayout>) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(layout));
  } catch {
    // ignore quota / private mode
  }
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

export function usePaneLayout() {
  const initial = React.useMemo(() => loadLayout(), []);
  const [sidebarWidth, setSidebarWidth] = React.useState(initial.sidebar);
  const [panelWidth, setPanelWidth] = React.useState(initial.panel);
  const [sidebarCollapsed, setSidebarCollapsed] = React.useState(initial.sidebarCollapsed);
  const layoutRef = React.useRef(initial);
  const dragRef = React.useRef<{ kind: "sidebar" | "panel"; startX: number; startWidth: number } | null>(null);

  layoutRef.current = { sidebar: sidebarWidth, panel: panelWidth, sidebarCollapsed };

  const effectiveSidebarWidth = sidebarCollapsed ? SIDEBAR_RAIL : sidebarWidth;

  React.useEffect(() => {
    function onMove(event: MouseEvent) {
      const drag = dragRef.current;
      if (!drag) return;
      const delta = event.clientX - drag.startX;
      if (drag.kind === "sidebar") {
        setSidebarWidth(clamp(drag.startWidth + delta, SIDEBAR_MIN, SIDEBAR_MAX));
        return;
      }
      setPanelWidth(clamp(drag.startWidth - delta, PANEL_MIN, PANEL_MAX));
    }

    function onUp() {
      if (!dragRef.current) return;
      dragRef.current = null;
      document.body.classList.remove("paneDragging");
      saveLayout(layoutRef.current);
    }

    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
      document.body.classList.remove("paneDragging");
    };
  }, []);

  function startDrag(kind: "sidebar" | "panel", event: React.MouseEvent) {
    if (kind === "sidebar" && sidebarCollapsed) return;
    event.preventDefault();
    dragRef.current = {
      kind,
      startX: event.clientX,
      startWidth: kind === "sidebar" ? layoutRef.current.sidebar : layoutRef.current.panel,
    };
    document.body.classList.add("paneDragging");
  }

  function resetSidebar() {
    setSidebarWidth(220);
    saveLayout({ ...layoutRef.current, sidebar: 220 });
  }

  function resetPanel() {
    setPanelWidth(300);
    saveLayout({ ...layoutRef.current, panel: 300 });
  }

  const toggleSidebarCollapsed = React.useCallback(() => {
    setSidebarCollapsed((collapsed) => {
      const next = !collapsed;
      saveLayout({ ...layoutRef.current, sidebarCollapsed: next });
      return next;
    });
  }, []);

  function setPanelWidthAndSave(width: number) {
    const next = clamp(width, PANEL_MIN, PANEL_MAX);
    setPanelWidth(next);
    saveLayout({ ...layoutRef.current, panel: next });
  }

  return {
    sidebarWidth,
    panelWidth,
    sidebarCollapsed,
    effectiveSidebarWidth,
    toggleSidebarCollapsed,
    setPanelWidth: setPanelWidthAndSave,
    startSidebarDrag: (event: React.MouseEvent) => startDrag("sidebar", event),
    startPanelDrag: (event: React.MouseEvent) => startDrag("panel", event),
    resetSidebar,
    resetPanel,
    PANEL_MIN,
    PANEL_MAX,
  };
}
