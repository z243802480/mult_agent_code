import { describe, expect, it } from "vitest";
import type { NarrativeStep, StudioEvent } from "../../types";
import { earliestEventMs, formatRunElapsed } from "./LiveStream";

function step(kind: NarrativeStep["kind"], createdAts: string[]): NarrativeStep {
  return {
    id: `s-${kind}-${createdAts.join(",")}`,
    kind,
    label: kind,
    title: "",
    summary: "",
    status: "running",
    events: createdAts.map(
      (created_at, i) =>
        ({
          event_id: `${kind}-${i}`,
          session_id: "s",
          type: "model_delta",
          created_at,
        }) as StudioEvent,
    ),
    defaultOpen: false,
  } as NarrativeStep;
}

describe("formatRunElapsed", () => {
  it("shows bare seconds under a minute", () => {
    expect(formatRunElapsed(0)).toBe("0s");
    expect(formatRunElapsed(12.9)).toBe("12s"); // floors, never rounds up past real elapsed
    expect(formatRunElapsed(59)).toBe("59s");
  });

  it("folds to m:ss at a minute or more, zero-padding the seconds", () => {
    expect(formatRunElapsed(60)).toBe("1m00s");
    expect(formatRunElapsed(187)).toBe("3m07s");
  });

  it("never goes negative on clock skew", () => {
    expect(formatRunElapsed(-5)).toBe("0s");
  });
});

describe("earliestEventMs", () => {
  it("returns the earliest parseable created_at across all steps and events", () => {
    const steps = [
      step("thinking", ["2026-07-15T10:00:05.000Z", "2026-07-15T10:00:09.000Z"]),
      step("tool", ["2026-07-15T10:00:02.000Z"]), // earliest lives on a later step
    ];
    expect(earliestEventMs(steps)).toBe(Date.parse("2026-07-15T10:00:02.000Z"));
  });

  it("ignores unparseable timestamps instead of yielding NaN", () => {
    const steps = [step("thinking", ["not-a-date", "2026-07-15T10:00:04.000Z"])];
    expect(earliestEventMs(steps)).toBe(Date.parse("2026-07-15T10:00:04.000Z"));
  });

  it("returns undefined when no event carries a timestamp", () => {
    expect(earliestEventMs([step("thinking", [])])).toBeUndefined();
    expect(earliestEventMs([step("thinking", ["", "garbage"])])).toBeUndefined();
  });
});
