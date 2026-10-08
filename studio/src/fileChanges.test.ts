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

describe("R2-10 — a failed call's planned paths are not changes", () => {
  const toolEvent = (over: Partial<StudioEvent>): StudioEvent =>
    event({
      type: "tool_start",
      transcript_kind: "tool_use",
      tool_call_id: "toolcall-0005",
      file_changes: [{ path: "taskman.py", operation: "modify" }] as never,
      ...over,
    }) as StudioEvent;

  it("drops the planned paths of a call whose terminal event failed (the real dogfood shape)", () => {
    // run-20260720-0001: tool_start(toolcall-0005, running, planned taskman.py) +
    // tool_end(toolcall-0005, failed, "File exists and overwrite is false"). The card claimed
    // 「2 个文件 修改」 right beside rows reading 「写入 taskman.py 失败」.
    const changes = extractFileChangesFromEvents([
      toolEvent({ event_id: "s1", status: "running" }),
      toolEvent({
        event_id: "e1",
        type: "tool_end",
        transcript_kind: "tool_result",
        status: "failed",
        title: "写入 taskman.py",
        summary: "File exists and overwrite is false: taskman.py",
        file_changes: [{ path: "taskman.py", operation: "modify" }] as never,
      }),
    ]);
    expect(changes).toEqual([]);
  });

  it("keeps the planned paths of calls that completed", () => {
    const changes = extractFileChangesFromEvents([
      toolEvent({ event_id: "s1", status: "running" }),
      toolEvent({
        event_id: "e1",
        type: "tool_end",
        transcript_kind: "tool_result",
        status: "completed",
        file_changes: [{ path: "taskman.py", operation: "modify" }] as never,
      }),
    ]);
    expect(changes.map((c) => c.path)).toEqual(["taskman.py"]);
  });

  it("still drops paths when only data.ok is false (status not yet failed)", () => {
    const changes = extractFileChangesFromEvents([
      toolEvent({
        event_id: "e1",
        type: "tool_end",
        status: "completed",
        data: { ok: false },
        file_changes: [{ path: "taskman.py" }] as never,
      }),
    ]);
    expect(changes).toEqual([]);
  });

  it("a still-running call keeps its planned path (live view shows work in progress)", () => {
    // Only DEMONSTRABLE failure drops a planned path. A call whose terminal event has not arrived
    // may still succeed — the live thread legitimately shows it as in-progress work.
    const changes = extractFileChangesFromEvents([
      event({ event_id: "f1", data: { path: "real.py", operation: "modify" } }),
      toolEvent({ event_id: "s1", status: "running" }),
    ]);
    expect(changes.map((c) => c.path)).toEqual(["real.py", "taskman.py"]);
  });
});
