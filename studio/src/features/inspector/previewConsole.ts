/**
 * G10 预览控制台 — pure pieces of the Preview tab's error bar.
 *
 * The preview server's injected client posts page errors (window.onerror / unhandledrejection /
 * console.error) to the embedding Studio via postMessage; the pane validates and accumulates them
 * here. Static-preview mode only — proxy mode passes the dev server through untouched, which owns
 * its own error overlay (Vite/Next), so we never double-report there.
 */

export const MAX_PREVIEW_ERRORS = 20;

export type PreviewErrorMessage = { __asteriaPreview: "error"; message: string };

/** True when a window message is the injected preview client's error envelope. */
export function isPreviewErrorMessage(data: unknown): data is PreviewErrorMessage {
  if (!data || typeof data !== "object") return false;
  const record = data as Record<string, unknown>;
  return record.__asteriaPreview === "error" && typeof record.message === "string";
}

/** Bounded accumulate (latest kept), collapsing an immediate duplicate into one entry. */
export function pushPreviewError(errors: string[], message: string): string[] {
  const text = message.trim();
  if (!text) return errors;
  if (errors[errors.length - 1] === text) return errors;
  return [...errors, text].slice(-MAX_PREVIEW_ERRORS);
}

/** Device-width presets for responsive checks (mainstream embedded-browser sizes). */
export const DEVICE_PRESETS = [
  { id: "fit", label: "自适应", width: null },
  { id: "mobile", label: "375", width: 375 },
  { id: "tablet", label: "768", width: 768 },
  { id: "desktop", label: "1280", width: 1280 },
] as const;

export type DevicePresetId = (typeof DEVICE_PRESETS)[number]["id"];
