import { describe, expect, it } from "vitest";
import { projectSummary, projectTitle } from "./titleProjection";

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
