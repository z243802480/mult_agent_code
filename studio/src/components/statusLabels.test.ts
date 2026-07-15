import { describe, expect, it } from "vitest";
import { statusLabel } from "./Shared";
import { tierLabel } from "./NarrativeStep";
import { schedulingModeLabel } from "./WorkerProgressBar";

describe("statusLabel — no raw English enum leaks in the Chinese UI", () => {
  it("localizes the core event statuses", () => {
    expect(statusLabel("running")).toBe("运行中");
    expect(statusLabel("completed")).toBe("已完成");
    expect(statusLabel("waiting_user")).toBe("待你处理");
  });

  it("localizes the worker/step statuses that reach it via inspector casts", () => {
    // These used to fall through the `?? status` fallback and render the raw English word.
    expect(statusLabel("success")).toBe("成功");
    expect(statusLabel("pending")).toBe("等待中");
    expect(statusLabel("in_progress")).toBe("进行中");
    expect(statusLabel("cancelled")).toBe("已取消");
    expect(statusLabel("skipped")).toBe("已跳过");
  });

  it("falls back to a neutral Chinese label, never the raw English enum, for an unseen value", () => {
    expect(statusLabel("some_future_status")).toBe("未知");
    expect(statusLabel("")).toBe("未知");
  });
});

describe("tierLabel — model tier chips read as Chinese", () => {
  it("localizes the real model tiers", () => {
    expect(tierLabel("strong")).toBe("强档");
    expect(tierLabel("standard")).toBe("标准档");
    expect(tierLabel("medium")).toBe("中档");
    expect(tierLabel("cheap")).toBe("经济档");
  });

  it("falls back to a raw label for an unmapped tier (all real values are mapped)", () => {
    expect(tierLabel("exotic")).toBe("exotic 档");
  });
});

describe("schedulingModeLabel — worker scheduling modes read as Chinese", () => {
  it("localizes the real scheduling modes", () => {
    expect(schedulingModeLabel("parallel")).toBe("并行");
    expect(schedulingModeLabel("sequential")).toBe("串行");
    expect(schedulingModeLabel("isolated")).toBe("隔离");
  });

  it("returns empty for an absent mode (chip is hidden) and passes an unmapped mode through", () => {
    expect(schedulingModeLabel("")).toBe("");
    expect(schedulingModeLabel("  ")).toBe("");
    expect(schedulingModeLabel("staged")).toBe("staged");
  });
});
