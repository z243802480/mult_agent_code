/**
 * Queued messages, persisted per session.
 *
 * Lining up follow-up instructions while a long run is in flight is the whole point of the queue —
 * and it lived in a plain useState, so a refresh (or a crashed tab) dropped them SILENTLY. The user
 * had no way to know what was lost. Mainstream agents keep pending input across a reload; so do we.
 *
 * localStorage, not the server: the queue is UI intent that has not been sent yet. It belongs to the
 * browser that typed it, and persisting it needs no round-trip and no new endpoint.
 */

const KEY_PREFIX = "asteria.composerQueue.";

/** Bounded so a runaway loop or a pathological paste cannot blow the storage quota. */
export const MAX_QUEUED = 50;
export const MAX_QUEUED_CHARS = 20_000;

type StorageLike = Pick<Storage, "getItem" | "setItem" | "removeItem">;

function storage(): StorageLike | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    // Storage can throw outright (Safari private mode, blocked third-party contexts).
    return null;
  }
}

export function queueKey(sessionId: string): string {
  return `${KEY_PREFIX}${sessionId}`;
}

export function loadQueue(sessionId: string, store: StorageLike | null = storage()): string[] {
  if (!sessionId || !store) return [];
  try {
    const raw = store.getItem(queueKey(sessionId));
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter((item): item is string => typeof item === "string" && item.trim().length > 0)
      .slice(0, MAX_QUEUED)
      .map((item) => item.slice(0, MAX_QUEUED_CHARS));
  } catch {
    // Corrupt entry: behave as if nothing was queued rather than taking the composer down with it.
    return [];
  }
}

export function saveQueue(
  sessionId: string,
  queue: string[],
  store: StorageLike | null = storage(),
): void {
  if (!sessionId || !store) return;
  try {
    if (!queue.length) {
      store.removeItem(queueKey(sessionId));
      return;
    }
    const bounded = queue.slice(0, MAX_QUEUED).map((item) => item.slice(0, MAX_QUEUED_CHARS));
    store.setItem(queueKey(sessionId), JSON.stringify(bounded));
  } catch {
    // Quota exceeded / storage disabled: the queue still works in memory for this tab. Never let
    // persistence failure break sending.
  }
}
