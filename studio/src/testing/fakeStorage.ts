/**
 * In-memory localStorage double for the per-session stores.
 *
 * Six test files had their own copy of this Map-backed shim, each slightly different (some accept a
 * seed, some expose the Map, some cast to Storage). Test infrastructure drifting per-file is how a
 * store's behaviour ends up asserted against six subtly different fakes.
 */

export type FakeStorage = Storage & { dump: () => Map<string, string> };

export function fakeStorage(seed: Record<string, string> = {}): FakeStorage {
  const map = new Map<string, string>(Object.entries(seed));
  return {
    getItem: (key: string) => map.get(key) ?? null,
    setItem: (key: string, value: string) => void map.set(key, value),
    removeItem: (key: string) => void map.delete(key),
    clear: () => map.clear(),
    key: (index: number) => Array.from(map.keys())[index] ?? null,
    get length() {
      return map.size;
    },
    dump: () => map,
  } as FakeStorage;
}
