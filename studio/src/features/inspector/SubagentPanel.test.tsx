import { describe, expect, it } from "vitest";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import type { StudioEvent } from "../../types";
import { SubagentPanel, buildExpertRows, expertDepth } from "./SubagentPanel";

// NOTE: no run in practice has produced delegated experts yet (every real run is a flat single-lead
// loop), so this is exercised with synthetic events shaped exactly like the runtime's dispatch/result
// cards (execute_command._run_child): transcript_kind="subagent_summary", data.task_id = delegator,
// data.child_task_id = `<parent>-sub-NN`. When concurrent experts do run, this is what renders.
function summary(over: Record<string, unknown>): StudioEvent {
  return {
    event_id: String(over.event_id ?? Math.random()),
    transcript_kind: "subagent_summary",
    summary: String(over.summary ?? ""),
    data: over.data,
  } as unknown as StudioEvent;
}

// Lead task-0001 delegates to a reviewer; that reviewer itself delegates to a researcher (depth 2).
const events: StudioEvent[] = [
  summary({
    data: {
      task_id: "task-0001",
      child_task_id: "task-0001-sub-01",
      subagent_role: "reviewer",
      subagent_phase: "dispatch",
    },
    summary: "委派 reviewer 专家",
  }),
  summary({
    data: {
      task_id: "task-0001",
      child_task_id: "task-0001-sub-01",
      subagent_role: "reviewer",
      subagent_phase: "result",
      ok: true,
      iterations: 3,
    },
    summary: "reviewer 完成",
  }),
  summary({
    data: {
      task_id: "task-0001-sub-01",
      child_task_id: "task-0001-sub-01-sub-01",
      subagent_role: "researcher",
      subagent_phase: "dispatch",
    },
    summary: "委派 researcher 专家",
  }),
  summary({
    data: {
      task_id: "task-0001-sub-01",
      child_task_id: "task-0001-sub-01-sub-01",
      subagent_role: "researcher",
      subagent_phase: "result",
      ok: false,
    },
    summary: "researcher 未完成",
  }),
];

describe("expertDepth", () => {
  it("counts the -sub- recursion levels in the child task id", () => {
    expect(expertDepth("task-0001-sub-01")).toBe(1);
    expect(expertDepth("task-0001-sub-01-sub-02")).toBe(2);
    expect(expertDepth("task-0001")).toBe(0);
  });
});

describe("buildExpertRows lineage", () => {
  it("stamps depth and resolves the parent role for nested sub-experts", () => {
    const rows = buildExpertRows(events);
    expect(rows).toHaveLength(2);
    const reviewer = rows.find((r) => r.role === "reviewer")!;
    const researcher = rows.find((r) => r.role === "researcher")!;
    // Top-level expert: parent is a lead task (not an expert) → depth 1, no parentRole.
    expect(reviewer.depth).toBe(1);
    expect(reviewer.parentTaskId).toBe("task-0001");
    expect(reviewer.parentRole).toBe("");
    expect(reviewer.status).toBe("done");
    // Nested sub-expert: parent IS the reviewer expert → depth 2, parentRole resolved.
    expect(researcher.depth).toBe(2);
    expect(researcher.parentTaskId).toBe("task-0001-sub-01");
    expect(researcher.parentRole).toBe("reviewer");
    expect(researcher.status).toBe("failed");
  });
});

describe("SubagentPanel render", () => {
  it("renders the delegation tree with the nested lineage chip", () => {
    const html = renderToStaticMarkup(React.createElement(SubagentPanel, { events }));
    expect(html).toContain("reviewer");
    expect(html).toContain("researcher");
    // The nested researcher shows who delegated it and is marked nested.
    expect(html).toContain("↳ reviewer");
    expect(html).toContain("isNested");
  });

  it("shows the empty state when no experts were delegated (the common case today)", () => {
    const html = renderToStaticMarkup(React.createElement(SubagentPanel, { events: [] }));
    expect(html).toContain("还没有委派子 agent");
  });
});
