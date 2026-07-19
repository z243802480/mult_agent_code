import { describe, expect, it } from "vitest";
import { isSessionLive } from "./narrative";
import type { StudioEvent } from "./types";

// F2/F3 regression pins (dogfood replay 2026-07-19, run-20260719-0001): the server tail forwards a
// runtime burst within the same millisecond, so the burst's closing "Thinking (running)" TIED with
// its neighbouring completed events on `created_at`. The old strict-`>` comparison lost every tie
// and read a grinding run as DEAD for 4.5 of its 5-minute execute window.

function evt(partial: Partial<StudioEvent> & { seq?: number }): StudioEvent {
  return {
    event_id: `evt-${Math.random().toString(16).slice(2)}`,
    type: "assistant_delta",
    ...partial,
  } as StudioEvent;
}

const T = "2026-07-19T14:58:06.123+08:00"; // one shared millisecond — the tail-burst shape

describe("isSessionLive tie-breaking", () => {
  it("a running event that TIES with completed neighbours on time still reads live (seq order decides)", () => {
    const events = [
      evt({ created_at: T, seq: 10, status: "completed", title: "已关联任务上下文" }),
      evt({ created_at: T, seq: 11, status: "running", title: "Worker action requested" }),
      evt({ created_at: T, seq: 12, status: "running", title: "Thinking" }),
    ];
    expect(isSessionLive(events)).toBe(true);
  });

  it("array order breaks the tie when seq is absent", () => {
    const events = [
      evt({ created_at: T, status: "completed" }),
      evt({ created_at: T, status: "running" }),
    ];
    expect(isSessionLive(events)).toBe(true);
  });

  it("a burst that genuinely ENDS with completed reads dead", () => {
    const events = [
      evt({ created_at: T, seq: 10, status: "running", title: "Thinking" }),
      evt({ created_at: T, seq: 11, status: "completed", title: "Draft complete" }),
    ];
    expect(isSessionLive(events)).toBe(false);
  });

  it("a strictly newer completed event still ends the session (original semantics preserved)", () => {
    const events = [
      evt({ created_at: "2026-07-19T14:58:06.123+08:00", seq: 10, status: "running" }),
      evt({ created_at: "2026-07-19T14:58:07.000+08:00", seq: 11, status: "completed" }),
    ];
    expect(isSessionLive(events)).toBe(false);
  });

  it("a final_answer cuts off everything before it (unchanged)", () => {
    const events = [
      evt({ created_at: "2026-07-19T14:58:06.000+08:00", seq: 10, status: "running" }),
      evt({ created_at: "2026-07-19T14:58:08.000+08:00", seq: 11, type: "final_answer", status: "completed" }),
    ];
    expect(isSessionLive(events)).toBe(false);
  });
});
