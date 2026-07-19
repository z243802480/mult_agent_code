import { describe, expect, it } from "vitest";
import { isBookkeepingTitle, projectSummary, projectTitle } from "./titleProjection";

describe("projectSummary — no English leak on the Chinese thread", () => {
  it("localizes the plan/workspace binding summary observed leaking live", () => {
    expect(
      projectSummary("Runtime bound this plan to the selected workspace and output scope."),
    ).toBe("已把本次计划绑定到当前工作区与输出范围。");
  });

  it("localizes the permission-mode summary and the mode token", () => {
    expect(projectSummary("Permission mode is auto.")).toBe("权限模式：全自动");
    expect(projectSummary("Permission mode is reviewed_auto.")).toBe("权限模式：自动编辑");
    expect(projectSummary("Permission mode is ask_everything.")).toBe("权限模式：逐步询问");
  });

  it("still neutralizes raw task ids in unmapped summaries", () => {
    expect(projectSummary("did something with task-0007 here")).toBe(
      "did something with 任务 here",
    );
  });

  it("passes genuine human text through unchanged", () => {
    expect(projectSummary("我已经实现了 is_prime 函数。")).toBe("我已经实现了 is_prime 函数。");
  });
});

describe("projectTitle", () => {
  it("projects a known internal title, passes others through", () => {
    expect(projectTitle("Workspace selected")).toBe("已选定工作区");
    expect(projectTitle("写入 primes.py")).toBe("写入 primes.py");
  });
});

describe("isBookkeepingTitle — persistence noise off the main thread (F4)", () => {
  it("flags the runtime's own persistence/setup milestones by RAW English literal", () => {
    // dogfood run-20260719-0001: this one landed as the plan-completion narrative title.
    expect(isBookkeepingTitle("Cost report written")).toBe(true);
    expect(isBookkeepingTitle("GoalSpec file written")).toBe(true);
    expect(isBookkeepingTitle("Task plan files written")).toBe(true);
    expect(isBookkeepingTitle("Validation results recorded")).toBe(true);
    expect(isBookkeepingTitle("Workspace selected")).toBe(true);
  });

  it("does NOT flag user-meaningful milestones (plan, promotion, verification, final)", () => {
    expect(isBookkeepingTitle("Task plan built")).toBe(false);
    expect(isBookkeepingTitle("Candidate promoted")).toBe(false);
    expect(isBookkeepingTitle("Validation conclusion")).toBe(false);
    expect(isBookkeepingTitle("Final report written")).toBe(false);
    expect(isBookkeepingTitle("Thinking")).toBe(false);
    expect(isBookkeepingTitle("我已实现 stats 子命令。")).toBe(false);
  });

  it("is robust to null/undefined", () => {
    expect(isBookkeepingTitle(null)).toBe(false);
    expect(isBookkeepingTitle(undefined)).toBe(false);
  });
});
