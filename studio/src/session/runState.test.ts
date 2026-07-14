import { describe, expect, it } from "vitest";
import { deriveRunState, STALE_CHECKS_BEFORE_DEAD } from "./runState";

describe("deriveRunState", () => {
  it("is idle when the event log shows nothing live", () => {
    expect(deriveRunState({ eventsLive: false, jobsRunning: 0, staleChecks: 99 })).toBe("idle");
    expect(deriveRunState({ eventsLive: false, jobsRunning: null, staleChecks: 0 })).toBe("idle");
  });

  it("is running when the registry confirms a live job", () => {
    expect(deriveRunState({ eventsLive: true, jobsRunning: 1, staleChecks: 0 })).toBe("running");
  });

  it("trusts the event log when the registry cannot be reached", () => {
    // Not being able to ask is NOT evidence of death — never fabricate an interruption.
    expect(
      deriveRunState({
        eventsLive: true,
        jobsRunning: null,
        staleChecks: STALE_CHECKS_BEFORE_DEAD,
      }),
    ).toBe("running");
  });

  it("does not call a run dead on a single stale probe (completion race)", () => {
    // A job that finishes normally leaves the running set a beat before its final event lands.
    expect(deriveRunState({ eventsLive: true, jobsRunning: 0, staleChecks: 1 })).toBe("running");
  });

  it("reports interrupted once the discrepancy survives the debounce", () => {
    // THE BUG THIS FIXES: events look live, no job is alive (server restarted / process killed).
    // Old behaviour spun "运行中" forever and Stop answered "no running job".
    expect(
      deriveRunState({
        eventsLive: true,
        jobsRunning: 0,
        staleChecks: STALE_CHECKS_BEFORE_DEAD,
      }),
    ).toBe("interrupted");
  });
});
