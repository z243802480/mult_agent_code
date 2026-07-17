import { describe, expect, it } from "vitest";
import type { StudioEvent } from "../../types";
import { turnSnapshotMap } from "./turnRewind";

const event = (over: Partial<StudioEvent>): StudioEvent =>
  ({
    event_id: "e1",
    session_id: "s1",
    type: "tool_end",
    status: "completed",
    title: "",
    summary: "",
    ...over,
  }) as StudioEvent;

describe("turnSnapshotMap (G7) — raw-event anchors matched to turns by time window", () => {
  it("assigns each snapshot to the turn it settled in, even when narrative dropped its event", () => {
    // Real failure shape: the settle event carrying the hash is a pointer-only final_report that
    // the narrative hides — so the anchor must come from raw events, not rendered steps.
    const raw = [
      event({ created_at: "2026-07-17T10:00:05Z", data: { workspace_snapshot: "turn1snap" } }),
      event({
        event_id: "e2",
        created_at: "2026-07-17T10:01:10Z",
        data: { workspace_snapshot: "turn2snap" },
      }),
    ];
    const map = turnSnapshotMap(["2026-07-17T10:00:00Z", "2026-07-17T10:01:00Z"], raw);
    expect(map).toEqual(["turn1snap", "turn2snap"]);
  });

  it("latest snapshot in a window wins; turns without one stay null", () => {
    const raw = [
      event({ created_at: "2026-07-17T10:00:05Z", data: { workspace_snapshot: "early" } }),
      event({
        event_id: "e2",
        created_at: "2026-07-17T10:00:30Z",
        data: { workspace_snapshot: "late" },
      }),
    ];
    const map = turnSnapshotMap(["2026-07-17T10:00:00Z", "2026-07-17T10:05:00Z"], raw);
    expect(map).toEqual(["late", null]);
  });

  it("tolerates unparseable turn starts and event stamps", () => {
    const raw = [event({ created_at: "not-a-date", data: { workspace_snapshot: "x" } })];
    expect(turnSnapshotMap([undefined, "garbage"], raw)).toEqual([null, null]);
  });
});
