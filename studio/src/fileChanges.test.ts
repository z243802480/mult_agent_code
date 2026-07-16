import { describe, expect, it } from "vitest";
import type { StudioEvent } from "./types";
import { extractFileChangesFromEvents } from "./fileChanges";

const event = (over: Partial<StudioEvent>): StudioEvent =>
  ({
    event_id: "e1",
    session_id: "s1",
    type: "file_changed",
    status: "completed",
    title: "",
    summary: "",
    ...over,
  }) as StudioEvent;

describe("extractFileChangesFromEvents", () => {
  it("reads structured data payloads and dedupes", () => {
    const changes = extractFileChangesFromEvents([
      event({ data: { path: "src/app.ts", operation: "modify" } }),
      event({ event_id: "e2", data: { path: "src/app.ts" } }),
    ]);
    expect(changes).toEqual([{ path: "src/app.ts", operation: "modify" }]);
  });

  it("falls back to artifact_refs when file_changed carries an empty data payload", () => {
    // Observed live (2026-07-17): a real run emitted file_changed with data {} and the touched
    // path only in artifact_refs — the Preview tab then claimed the session had no artifacts.
    const changes = extractFileChangesFromEvents([
      event({ data: {}, artifact_refs: ["demo.html"] } as Partial<StudioEvent>),
    ]);
    expect(changes.map((c) => c.path)).toEqual(["demo.html"]);
  });

  it("never surfaces .asteria runtime bookkeeping as file changes", () => {
    const changes = extractFileChangesFromEvents([
      event({
        data: { path: ".asteria/runs/run-1/task_plan.json" },
        artifact_refs: [".asteria/runs/run-1/cost_report.json", "real.py"],
      } as Partial<StudioEvent>),
    ]);
    expect(changes.map((c) => c.path)).toEqual(["real.py"]);
  });
});
