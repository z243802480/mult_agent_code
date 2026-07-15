import { describe, expect, it } from "vitest";
import { turnVerifiedBadge } from "./runtimeNarrative";

describe("turnVerifiedBadge", () => {
  it("shows when the turn's own verdict passed and it is not actively streaming", () => {
    expect(
      turnVerifiedBadge({ isLast: true, isRunning: false, hasResponse: true, turnVerdict: "pass" }),
    ).toBe(true);
  });

  it("shows on a completed follow-up turn even while a later turn runs (per-turn, not run-global)", () => {
    // Regression: previously required the run-GLOBAL verdict too, which lagged a follow-up run and left
    // a genuinely-verified turn with neither badge nor nag (live is_even/is_odd test).
    expect(
      turnVerifiedBadge({ isLast: false, isRunning: true, hasResponse: true, turnVerdict: "pass" }),
    ).toBe(true);
  });

  it("is suppressed on the last turn while it is still streaming", () => {
    expect(
      turnVerifiedBadge({ isLast: true, isRunning: true, hasResponse: true, turnVerdict: "pass" }),
    ).toBe(false);
  });

  it("never inherits — a turn with no verdict of its own gets no badge", () => {
    for (const v of ["fail", "unrun", null] as const) {
      expect(
        turnVerifiedBadge({ isLast: true, isRunning: false, hasResponse: true, turnVerdict: v }),
      ).toBe(false);
    }
  });

  it("never shows without a response step", () => {
    expect(
      turnVerifiedBadge({
        isLast: false,
        isRunning: false,
        hasResponse: false,
        turnVerdict: "pass",
      }),
    ).toBe(false);
  });
});
