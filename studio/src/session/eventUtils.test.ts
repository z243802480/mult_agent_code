import { describe, expect, it } from "vitest";
import type { StudioEvent } from "../types";
import { mergeEventLists } from "./eventUtils";

function event(partial: Partial<StudioEvent>): StudioEvent {
  return {
    event_id: "event",
    session_id: "session",
    type: "assistant_delta",
    status: "completed",
    title: "",
    summary: "",
    created_at: "2026-10-15T06:55:00Z",
    ...partial,
  };
}

describe("live permission resolution", () => {
  it("removes only the approved job's stale card when its resolution arrives", () => {
    const first = event({
      event_id: "ask-1",
      type: "permission_request",
      status: "waiting_user",
      job_id: "job-1",
    });
    const second = event({
      event_id: "ask-2",
      type: "permission_request",
      status: "waiting_user",
      job_id: "job-2",
    });
    const resolved = event({ event_id: "allowed", resolved_job_id: "job-1" });
    const merged = mergeEventLists([first, second], [resolved]);
    expect(merged.map((item) => item.event_id)).toEqual(["ask-2", "allowed"]);
    expect(mergeEventLists(merged, [first]).map((item) => item.event_id)).toEqual([
      "ask-2",
      "allowed",
    ]);
  });

  it("keeps an unresolved permission request actionable", () => {
    const pending = event({
      event_id: "ask",
      type: "permission_request",
      status: "waiting_user",
      job_id: "job-1",
    });
    expect(mergeEventLists([], [pending])).toEqual([pending]);
  });
});
