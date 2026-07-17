// G6 刀二 — the plan-edit surface. Static-markup harness + pure functions, same as 刀一.
// The interaction itself (typing, Ctrl+Enter) is covered by scripts/plan-edit.spec.mjs — a real
// browser, because this harness renders markup and never fires events.
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { fakeStorage } from "../../testing/fakeStorage";
import { PlanChecklist } from "./PlanChecklist";
import type { PlanModel } from "./planModel";
import { DiffCommentTray, buildFeedbackMessage } from "../../components/DiffCommentTray";
import { addPlanComment, setPlanCommentSession } from "../../session/planComments";
import { setPlanRevision, setPlanRevisionSession, getPlanRevision } from "../../session/planRevision";
import { setDiffCommentSession } from "../../session/diffComments";

const plan: PlanModel = {
  items: [
    { id: "t1", title: "实现 power 函数", state: "pending" },
    { id: "t2", title: "写测试", state: "pending" },
  ],
  done: 0,
  total: 2,
  counts: { pending: 2, in_progress: 0, blocked: 0, done: 0 },
  source: "model_todos",
  updateReason: "",
};

beforeEach(() => {
  vi.stubGlobal("localStorage", fakeStorage());
  for (const setSession of [setDiffCommentSession, setPlanCommentSession, setPlanRevisionSession]) {
    setSession("__reset-revision-test__");
    setSession("session-revision");
  }
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("PlanChecklist plan-edit entry", () => {
  it("offers an edit entry for the plan body", () => {
    const html = renderToStaticMarkup(<PlanChecklist plan={plan} />);
    expect(html).toContain("编辑计划");
  });

  it("shows the real plan even while a rewrite is pending — the checklist never lies", () => {
    // The honesty invariant of this whole knife: the plan does not change until the MODEL changes
    // it. If this ever renders the staged text, a declined rewrite becomes a permanent lie.
    setPlanRevision("完全不同的一步", "实现 power 函数\n写测试");
    const html = renderToStaticMarkup(<PlanChecklist plan={plan} />);
    expect(html).toContain("实现 power 函数");
    expect(html).toContain("写测试");
    expect(html).not.toContain("完全不同的一步");
  });

  it("says a rewrite is waiting, without claiming it took effect", () => {
    setPlanRevision("只留一步", "实现 power 函数\n写测试");
    const html = renderToStaticMarkup(<PlanChecklist plan={plan} />);
    expect(html).toContain("待提交");
  });
});

describe("the shared tray carries the rewrite", () => {
  // The head label is all this harness can see — the per-item rows (which carry "N 处不同") live
  // behind the tray's disclosure, and static markup cannot open it. Rows are covered in
  // scripts/plan-edit.spec.mjs; the count itself in planRevision.test.ts.
  it("appears in the tray on its own", () => {
    setPlanRevision("实现 power 函数\n写测试\n跑一遍", "实现 power 函数\n写测试");
    const html = renderToStaticMarkup(
      <DiffCommentTray isRunning={false} midRunSteer={false} onSend={async () => true} />,
    );
    expect(html).toContain("改过的计划待提交");
  });

  it("joins the existing breakdown rather than rewording it (刀一 copy regression)", () => {
    addPlanComment(1, "实现 power 函数", "别动 schema");
    setPlanRevision("只留一步", "实现 power 函数\n写测试");
    const html = renderToStaticMarkup(
      <DiffCommentTray isRunning={false} midRunSteer={false} onSend={async () => true} />,
    );
    expect(html).toContain("2 条意见待提交（计划 1 · 改过的计划）");
  });

  it("renders nothing when there is no pending feedback at all", () => {
    const html = renderToStaticMarkup(
      <DiffCommentTray isRunning={false} midRunSteer={false} onSend={async () => true} />,
    );
    expect(html).toBe("");
  });
});

describe("buildFeedbackMessage", () => {
  it("puts the rewritten plan after the step comments that constrain it", () => {
    addPlanComment(1, "实现 power 函数", "别动 schema");
    setPlanRevision("先写测试\n再实现", "实现 power 函数\n写测试");
    const message = buildFeedbackMessage([], [{ id: "p1", step: 1, title: "实现", text: "别动 schema" }], getPlanRevision());
    expect(message.indexOf("别动 schema")).toBeLessThan(message.indexOf("todo_write"));
  });

  it("is unchanged for callers with no rewrite (刀一 regression)", () => {
    const message = buildFeedbackMessage([], [{ id: "p1", step: 2, title: "写测试", text: "别动 schema" }]);
    expect(message).toContain("对计划第 2 步");
    expect(message).not.toContain("todo_write");
  });
});
