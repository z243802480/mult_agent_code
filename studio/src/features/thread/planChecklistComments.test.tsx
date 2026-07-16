// G6 刀一 — plan-step comments: the checklist carries a per-step comment entry, pending comments
// render under their step, and the shared tray batches them (alone or together with diff line
// comments) into one structured message. Static-markup harness + pure functions, same as G4.
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { PlanChecklist } from "./PlanChecklist";
import type { PlanModel } from "./planModel";
import { DiffCommentTray, buildFeedbackMessage } from "../../components/DiffCommentTray";
import { addDiffComment, setDiffCommentSession } from "../../session/diffComments";
import { addPlanComment, setPlanCommentSession } from "../../session/planComments";

function fakeStorage(): Storage {
  const map = new Map<string, string>();
  return {
    getItem: (k: string) => map.get(k) ?? null,
    setItem: (k: string, v: string) => void map.set(k, v),
    removeItem: (k: string) => void map.delete(k),
    clear: () => map.clear(),
    key: (i: number) => [...map.keys()][i] ?? null,
    get length() {
      return map.size;
    },
  } as Storage;
}

const plan: PlanModel = {
  items: [
    { id: "t1", title: "实现 power 函数", state: "pending" },
    { id: "t2", title: "写测试", state: "pending" },
  ],
  done: 0,
  total: 2,
  counts: { pending: 2, in_progress: 0, blocked: 0, done: 0 },
  source: "task_plan",
  updateReason: "",
};

beforeEach(() => {
  vi.stubGlobal("localStorage", fakeStorage());
  setDiffCommentSession("__reset-plan-test__");
  setDiffCommentSession("session-plan");
  setPlanCommentSession("__reset-plan-test__");
  setPlanCommentSession("session-plan");
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("PlanChecklist step comments", () => {
  it("renders a per-step comment entry and pending comments under their step", () => {
    addPlanComment(2, "写测试", "不要动 schema");
    const html = renderToStaticMarkup(<PlanChecklist plan={plan} defaultOpen />);
    expect(html).toContain("对计划第 1 步写意见");
    expect(html).toContain("对计划第 2 步写意见");
    expect(html).toContain("不要动 schema");
    expect(html).toContain("删除这条计划意见");
  });
});

describe("shared tray with plan comments", () => {
  it("labels a plan-only batch honestly and a mixed batch with both counts", () => {
    addPlanComment(2, "写测试", "不要动 schema");
    let html = renderToStaticMarkup(
      <DiffCommentTray isRunning={false} midRunSteer onSend={vi.fn()} />,
    );
    expect(html).toContain("1 条计划意见待提交");
    addDiffComment({ file: "a.ts", line: 3, side: "new", excerpt: "+x" }, "改名");
    html = renderToStaticMarkup(<DiffCommentTray isRunning={false} midRunSteer onSend={vi.fn()} />);
    expect(html).toContain("2 条意见待提交（diff 1 · 计划 1）");
  });
});

describe("buildFeedbackMessage", () => {
  it("joins both sections; a single kind keeps its own exact format", () => {
    const diff = [
      { id: "c-1", file: "a.ts", line: 3, side: "new" as const, excerpt: "+x", text: "改名" },
    ];
    const planOnly = buildFeedbackMessage(
      [],
      [{ id: "p-1", step: 2, title: "写测试", text: "别动 schema" }],
    );
    expect(planOnly.startsWith("请在执行时遵守下面这些对当前计划的意见：")).toBe(true);
    const both = buildFeedbackMessage(diff, [
      { id: "p-1", step: 2, title: "写测试", text: "别动 schema" },
    ]);
    expect(both).toContain("行级评论修改代码");
    expect(both).toContain("对计划第 2 步「写测试」：别动 schema");
    expect(buildFeedbackMessage(diff, [])).not.toContain("计划");
  });
});
