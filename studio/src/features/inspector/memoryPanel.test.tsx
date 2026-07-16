// G14 记忆管理 UI（只读）— the projection must render exactly what the runtime recorded, tolerate
// corruption, and never invent fields. Fixture mirrors a REAL active_goal.json from a live run.
import { describe, expect, it } from "vitest";
import { parseActiveGoalMemory } from "./MemoryPanel";

const REAL_SHAPE = JSON.stringify({
  schema_version: "0.1.0",
  memory_id: "active-goal",
  goal_id: "goal-0001",
  source_run_id: "run-20260717-0005",
  updated_at: "2026-07-17T07:01:49+08:00",
  updated_by: "accept",
  current_goal: "在 calc.py 文件中添加 mod(a, b) 取余函数。",
  current_result: { state: "accepted", review: "not reviewed yet", completion: "accepted" },
  overall_plan: [{ task_id: "task-0001", title: "Implement calc.py", status: "done", summary: "" }],
  completed_work: ["- Implement calc.py", "- Artifact: `calc.py`"],
  current_blockers: [],
  next_task: ["- Review the result and accept it if it matches the goal."],
  watch_items: [],
});

describe("parseActiveGoalMemory", () => {
  it("projects the real recorded shape faithfully (bullet dashes stripped, statuses kept)", () => {
    const view = parseActiveGoalMemory(REAL_SHAPE);
    expect(view).not.toBeNull();
    expect(view!.currentGoal).toContain("mod(a, b)");
    expect(view!.sourceRunId).toBe("run-20260717-0005");
    expect(view!.resultState).toBe("accepted");
    expect(view!.plan).toEqual([{ title: "Implement calc.py", status: "done" }]);
    expect(view!.completedWork).toEqual(["Implement calc.py", "Artifact: `calc.py`"]);
    expect(view!.nextTask).toEqual(["Review the result and accept it if it matches the goal."]);
    expect(view!.blockers).toEqual([]);
  });

  it("returns null on corrupt or non-object input, never throws", () => {
    expect(parseActiveGoalMemory("{nope")).toBeNull();
    expect(parseActiveGoalMemory("[1,2]")).toBeNull();
    expect(parseActiveGoalMemory('"just a string"')).toBeNull();
  });

  it("tolerates missing fields with empty projections (older memory schema)", () => {
    const view = parseActiveGoalMemory("{}");
    expect(view).not.toBeNull();
    expect(view!.currentGoal).toBe("");
    expect(view!.plan).toEqual([]);
    expect(view!.completedWork).toEqual([]);
  });
});
