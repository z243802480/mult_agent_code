import { useCallback, useEffect, useState } from "react";

// Manual theme control (System / Light / Dark). The dark palette is the :root default; the light
// palette lives under :root[data-theme="light"]. "system" is resolved to a concrete light/dark at
// runtime (matchMedia) and re-resolved live when the OS theme changes. A tiny inline script in
// index.html applies the stored choice before the bundle paints, so there is no theme flash.

export type ThemeSetting = "system" | "light" | "dark";

export const THEME_STORAGE_KEY = "asteria.studio.theme";

function prefersLight(): boolean {
  return typeof window !== "undefined" && typeof window.matchMedia === "function"
    ? window.matchMedia("(prefers-color-scheme: light)").matches
    : false;
}

export function resolveTheme(setting: ThemeSetting): "light" | "dark" {
  if (setting === "light" || setting === "dark") return setting;
  return prefersLight() ? "light" : "dark";
}

export function applyTheme(setting: ThemeSetting): void {
  if (typeof document === "undefined") return;
  document.documentElement.setAttribute("data-theme", resolveTheme(setting));
}

function loadSetting(): ThemeSetting {
  try {
    const raw = localStorage.getItem(THEME_STORAGE_KEY);
    if (raw === "light" || raw === "dark" || raw === "system") return raw;
  } catch {
    // ignore
  }
  return "system";
}

export function useTheme() {
  const [theme, setThemeState] = useState<ThemeSetting>(() => loadSetting());

  const setTheme = useCallback((next: ThemeSetting) => {
    setThemeState(next);
    try {
      localStorage.setItem(THEME_STORAGE_KEY, next);
    } catch {
      // ignore
    }
    applyTheme(next);
  }, []);

  useEffect(() => {
    applyTheme(theme);
    // Only "system" needs to track live OS changes; explicit light/dark are fixed.
    if (theme !== "system" || typeof window === "undefined" || !window.matchMedia) return;
    const mq = window.matchMedia("(prefers-color-scheme: light)");
    const onChange = () => applyTheme("system");
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [theme]);

  return { theme, setTheme };
}
