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

  it("registry authority holds in BOTH directions: a live job outranks a dead-looking event log", () => {
    // F2/F3 (dogfood replay 2026-07-19): isSessionLive misread a grinding run as dead for 4.5 of
    // its 5 execute minutes; the old `!eventsLive → idle` first line let that hint veto a registry
    // that KNEW the job was alive — composer flipped idle and live indicators unmounted mid-run.
    expect(deriveRunState({ eventsLive: false, jobsRunning: 1, staleChecks: 0 })).toBe("running");
    expect(deriveRunState({ eventsLive: false, jobsRunning: 3, staleChecks: 99 })).toBe("running");
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

  it("never reports interrupted for a SETTLED run, even past the debounce (completion race)", () => {
    // THE FALSE-POSITIVE THIS FIXES: a cleanly-finished job flips terminal in the registry a beat
    // before its final_answer event flushes to disk. In that window eventsLive is still true and
    // jobsRunning is 0 — the debounced check would eventually mislabel it "已中断" (a crash). But the
    // registry says the run SETTLED, not vanished, so it is finishing, not dead: report "running"
    // (it flips to idle the instant the final event lands), never "interrupted".
    expect(
      deriveRunState({
        eventsLive: true,
        jobsRunning: 0,
        staleChecks: STALE_CHECKS_BEFORE_DEAD,
        settled: true,
      }),
    ).toBe("running");
  });

  it("still reports interrupted for a jobless registry (no settle evidence) past the debounce", () => {
    // The distinction that keeps the fix honest: settled=false means there is NO job record at all
    // (server restarted / pruned), which is a genuine lost-track — the interruption verdict stands.
    expect(
      deriveRunState({
        eventsLive: true,
        jobsRunning: 0,
        staleChecks: STALE_CHECKS_BEFORE_DEAD,
        settled: false,
      }),
    ).toBe("interrupted");
  });

  it("reports waiting (not interrupted) when parked on a pending approval with no live job", () => {
    // THE BUG THIS FIXES: a run paused at an approval gate (e.g. the initial goal-start permission)
    // has no live subprocess, so the jobs-registry miss used to survive the debounce and label it
    // "已中断" — a crash — while the thread simultaneously showed "待你处理". A deliberate wait is not
    // a death: waitingForUser is authoritative over the registry miss.
    expect(
      deriveRunState({
        eventsLive: true,
        jobsRunning: 0,
        staleChecks: STALE_CHECKS_BEFORE_DEAD,
        waitingForUser: true,
      }),
    ).toBe("waiting");
  });

  it("still reports idle when nothing is live, even if a stale waiting flag lingers", () => {
    // Not-live wins: no active gate to wait on.
    expect(
      deriveRunState({ eventsLive: false, jobsRunning: 0, staleChecks: 0, waitingForUser: true }),
    ).toBe("idle");
  });
});
