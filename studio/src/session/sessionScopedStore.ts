/**
 * The per-session localStorage module store behind the "评论即指令" trays.
 *
 * diffComments (G4) and planComments (G6 刀一) each had their own byte-identical copy of this:
 * the storage guard, the key builder, the bounded load/save, and the listener set that
 * `useSyncExternalStore` subscribes to. Only the item shape ever differed. A third comment surface
 * would have made a third copy — and a fix applied to one copy silently misses the others.
 *
 * What stays in the caller: the item type, its sanitizer, and the domain mutators (addDiffComment
 * takes an anchor; addPlanComment takes a step). Only the mechanism is shared.
 */

export type StorageLike = Pick<Storage, "getItem" | "setItem" | "removeItem">;

/** localStorage, or null when it is absent or throws (Safari private mode, blocked contexts). */
export function safeStorage(): StorageLike | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null;
  }
}

export type SessionScopedStore<T> = {
  key(sessionId: string): string;
  load(sessionId: string, store?: StorageLike | null): T[];
  save(sessionId: string, items: T[], store?: StorageLike | null): void;
  /** Point the store at a session; reloads its items. No-op when already active. */
  setSession(sessionId: string): void;
  getItems(): T[];
  /** Replace the items, persist them, and notify subscribers. */
  setItems(next: T[]): void;
  subscribe(listener: () => void): () => void;
  /** Stable across unchanged state — useSyncExternalStore loops forever on a fresh array. */
  getSnapshot(): T[];
};

export function createSessionScopedStore<T>(options: {
  keyPrefix: string;
  /** Drops malformed entries and clamps bounds. Runs on both load and save. */
  sanitize: (raw: unknown) => T[];
}): SessionScopedStore<T> {
  const key = (sessionId: string) => `${options.keyPrefix}${sessionId}`;

  function load(sessionId: string, store: StorageLike | null = safeStorage()): T[] {
    if (!sessionId || !store) return [];
    try {
      const raw = store.getItem(key(sessionId));
      if (!raw) return [];
      return options.sanitize(JSON.parse(raw));
    } catch {
      // A corrupt entry behaves as "nothing pending" rather than taking the view down.
      return [];
    }
  }

  function save(sessionId: string, items: T[], store: StorageLike | null = safeStorage()): void {
    if (!sessionId || !store) return;
    try {
      if (!items.length) {
        store.removeItem(key(sessionId));
        return;
      }
      store.setItem(key(sessionId), JSON.stringify(options.sanitize(items)));
    } catch {
      // Quota exceeded / storage disabled: the items still work in memory for this tab.
    }
  }

  let activeSessionId = "";
  let current: T[] = [];
  const listeners = new Set<() => void>();
  const emit = () => {
    for (const listener of listeners) listener();
  };

  return {
    key,
    load,
    save,
    setSession(sessionId: string) {
      if (sessionId === activeSessionId) return;
      activeSessionId = sessionId;
      current = load(sessionId);
      emit();
    },
    getItems: () => current,
    setItems(next: T[]) {
      current = next;
      save(activeSessionId, current);
      emit();
    },
    subscribe(listener: () => void) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    getSnapshot: () => current,
  };
}
