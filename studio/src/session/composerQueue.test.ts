import { describe, expect, it } from "vitest";
import { MAX_QUEUED, loadQueue, queueKey, saveQueue } from "./composerQueue";

function fakeStore(seed: Record<string, string> = {}) {
  const data = new Map(Object.entries(seed));
  return {
    getItem: (key: string) => data.get(key) ?? null,
    setItem: (key: string, value: string) => void data.set(key, value),
    removeItem: (key: string) => void data.delete(key),
    data,
  };
}

describe("composer queue persistence", () => {
  it("round-trips a queue for a session", () => {
    const store = fakeStore();
    saveQueue("s1", ["first", "second"], store);
    expect(loadQueue("s1", store)).toEqual(["first", "second"]);
  });

  it("keeps sessions separate", () => {
    const store = fakeStore();
    saveQueue("s1", ["for A"], store);
    saveQueue("s2", ["for B"], store);
    expect(loadQueue("s1", store)).toEqual(["for A"]);
    expect(loadQueue("s2", store)).toEqual(["for B"]);
  });

  it("clears the entry when the queue drains, instead of leaving an empty array behind", () => {
    const store = fakeStore();
    saveQueue("s1", ["only"], store);
    saveQueue("s1", [], store);
    expect(store.data.has(queueKey("s1"))).toBe(false);
    expect(loadQueue("s1", store)).toEqual([]);
  });

  it("survives a corrupt entry instead of throwing", () => {
    const store = fakeStore({ [queueKey("s1")]: "{not json" });
    expect(loadQueue("s1", store)).toEqual([]);
  });

  it("ignores a non-array payload and non-string items", () => {
    const store = fakeStore({ [queueKey("s1")]: '{"a":1}' });
    expect(loadQueue("s1", store)).toEqual([]);
    saveQueue("s2", ["keep"], store);
    store.setItem(queueKey("s2"), JSON.stringify(["keep", 42, "", null]));
    expect(loadQueue("s2", store)).toEqual(["keep"]);
  });

  it("bounds how much it will store", () => {
    const store = fakeStore();
    saveQueue(
      "s1",
      Array.from({ length: MAX_QUEUED + 10 }, (_, i) => `msg-${i}`),
      store,
    );
    expect(loadQueue("s1", store)).toHaveLength(MAX_QUEUED);
  });

  it("is a no-op without a session id or storage", () => {
    const store = fakeStore();
    saveQueue("", ["x"], store);
    expect(store.data.size).toBe(0);
    expect(loadQueue("s1", null)).toEqual([]);
    expect(() => saveQueue("s1", ["x"], null)).not.toThrow();
  });
});
