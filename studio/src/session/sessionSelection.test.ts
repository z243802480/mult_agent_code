import { describe, expect, it } from "vitest";
import { shouldResetForSession } from "./sessionSelection";

describe("shouldResetForSession", () => {
  it("switching sessions resets the transcript and the evidence selection", () => {
    expect(shouldResetForSession("s1", "s2")).toBe(true);
  });

  it("re-selecting the ACTIVE session keeps them", () => {
    // The regression: clearing here emptied the thread while the id stayed put, so the id-keyed
    // subscription effect never re-ran and the dedup set blocked any refill. Permanent empty state
    // until the user switched away and back — hit on every reload.
    expect(shouldResetForSession("s1", "s1")).toBe(false);
  });

  it("first selection with no active session is a real switch", () => {
    expect(shouldResetForSession(null, "s1")).toBe(true);
    expect(shouldResetForSession(undefined, "s1")).toBe(true);
    expect(shouldResetForSession("", "s1")).toBe(true);
  });
});
