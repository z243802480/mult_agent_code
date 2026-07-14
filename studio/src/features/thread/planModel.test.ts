import { describe, expect, it } from "vitest";
import { derivePlan } from "./planModel";
import { buildRunNarrative } from "../../narrative";
import type { RunDetailPayload, StudioEvent } from "../../types";

// B6: the checklist used to read ONLY the planner's static task_plan, while the model quietly kept
// its own todo list (todo_write → model_todos.json) that nothing ever read. Precedence mirrors the
// runtime's own todo_read: the model's list wins, task_plan is the fallback.
const MODEL_TODOS = {
  source: "model_todo_surface",
  update_reason: "测试比预想的多,先补测试再改实现",
  items: [
    { id: "todo-0001", content: "读现有代码", status: "completed" },
    { id: "todo-0002", content: "补测试", status: "in_progress" },
    { id: "todo-0003", content: "改实现", status: "pending" },
  ],
};
const TASK_PLAN = {
  tasks: [{ task_id: "task-0001", title: "创建 notes 模块", status: "pending" }],
};

describe("derivePlan", () => {
  it("prefers the model's own todo list over the planner's static plan", () => {
    const plan = derivePlan({
      ok: true,
      model_todos: MODEL_TODOS,
      task_plan: TASK_PLAN,
    } as RunDetailPayload);
    expect(plan?.source).toBe("model_todos");
    expect(plan?.items.map((i) => i.title)).toEqual(["读现有代码", "补测试", "改实现"]);
    expect(plan?.done).toBe(1);
    expect(plan?.total).toBe(3);
    expect(plan?.counts.in_progress).toBe(1);
    // The one thing a static plan can never carry: why the model changed its mind.
    expect(plan?.updateReason).toContain("先补测试");
  });

  it("falls back to task_plan when the model kept no todos", () => {
    const plan = derivePlan({ ok: true, task_plan: TASK_PLAN } as RunDetailPayload);
    expect(plan?.source).toBe("task_plan");
    expect(plan?.items).toHaveLength(1);
    expect(plan?.updateReason).toBe("");
  });

  it("renders nothing rather than a fake shell when there is no plan at all", () => {
    expect(derivePlan({ ok: true } as RunDetailPayload)).toBeNull();
    expect(derivePlan(null)).toBeNull();
  });

  it("ignores an empty todo list and still falls back", () => {
    const plan = derivePlan({
      ok: true,
      model_todos: { items: [] },
      task_plan: TASK_PLAN,
    } as unknown as RunDetailPayload);
    expect(plan?.source).toBe("task_plan");
  });
});

describe("raw todo_write tool row", () => {
  it("is kept off the main thread (the plan card + checklist already show it, without jargon)", () => {
    const toolRow = {
      event_id: "upe-0003",
      type: "tool_use",
      status: "completed",
      title: "使用 todo write",
      transcript_kind: "tool_use",
      display_level: "main",
      created_at: "2026-07-14T10:00:00Z",
      data: { tool_name: "todo_write", ok: true },
    } as unknown as StudioEvent;
    expect(buildRunNarrative([toolRow]).steps).toHaveLength(0);
  });

  it("keeps the todo_update card itself (it carries no tool_name)", () => {
    const card = {
      event_id: "upe-0004",
      type: "message",
      status: "running",
      title: "更新计划",
      summary: "把目标拆成三步",
      transcript_kind: "todo_update",
      display_level: "main",
      created_at: "2026-07-14T10:00:01Z",
      data: { todo_items: MODEL_TODOS.items },
    } as unknown as StudioEvent;
    expect(buildRunNarrative([card]).steps).toHaveLength(1);
  });
});
