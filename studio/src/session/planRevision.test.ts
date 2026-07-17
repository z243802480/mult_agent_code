// G6 刀二 — the pending plan rewrite: staged locally, delivered as words, never written to a plan
// file. Pure functions + the session-scoped store, same shape as planComments.test.ts.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fakeStorage } from "../testing/fakeStorage";
import {
  MAX_PLAN_REVISION_CHARS,
  clearPlanRevision,
  countChangedLines,
  formatPlanRevisionMessage,
  getPlanRevision,
  loadPlanRevision,
  planAsText,
  planRevisionKey,
  setPlanRevision,
  setPlanRevisionSession,
} from "./planRevision";

beforeEach(() => {
  vi.stubGlobal("localStorage", fakeStorage());
  setPlanRevisionSession("__reset__");
  setPlanRevisionSession("session-a");
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("planAsText", () => {
  it("is the plan as editable lines — order is the only structure", () => {
    expect(planAsText(["实现 power 函数", "写测试"])).toBe("实现 power 函数\n写测试");
  });

  it("drops empty titles rather than emitting blank lines to edit around", () => {
    expect(planAsText(["写测试", "  ", ""])).toBe("写测试");
  });
});

describe("setPlanRevision", () => {
  it("stages an edited plan", () => {
    setPlanRevision("a\nb\nc", "a\nb");
    expect(getPlanRevision()).toEqual({ text: "a\nb\nc", original: "a\nb" });
  });

  it("an edit that lands back on the real plan is not a revision", () => {
    // Otherwise submitting would spend a turn asking the model to re-plan into what it already has.
    setPlanRevision("a\nb", "a\nb");
    expect(getPlanRevision()).toBeNull();
  });

  it("ignores cosmetic whitespace when deciding whether anything changed", () => {
    setPlanRevision("  a  \n\n b \n", "a\nb");
    expect(getPlanRevision()).toBeNull();
  });

  it("clears an existing draft when the edit is reverted", () => {
    setPlanRevision("a\nb\nc", "a\nb");
    setPlanRevision("a\nb", "a\nb");
    expect(getPlanRevision()).toBeNull();
  });

  it("an empty edit is a clear, not a plan with no steps", () => {
    setPlanRevision("a\nb\nc", "a\nb");
    setPlanRevision("   ", "a\nb");
    expect(getPlanRevision()).toBeNull();
  });

  it("clamps a pathological paste", () => {
    setPlanRevision("x".repeat(MAX_PLAN_REVISION_CHARS + 500), "a");
    expect(getPlanRevision()?.text.length).toBe(MAX_PLAN_REVISION_CHARS);
  });
});

describe("session scoping", () => {
  it("a draft belongs to its session and does not leak into the next", () => {
    setPlanRevision("a\nb\nc", "a\nb");
    setPlanRevisionSession("session-b");
    expect(getPlanRevision()).toBeNull();
    setPlanRevisionSession("session-a");
    expect(getPlanRevision()?.text).toBe("a\nb\nc");
  });

  it("persists under a session-scoped key", () => {
    setPlanRevision("a\nb\nc", "a\nb");
    expect(localStorage.getItem(planRevisionKey("session-a"))).toContain("a\\nb\\nc");
  });

  it("a corrupt entry reads as nothing pending rather than taking the view down", () => {
    localStorage.setItem(planRevisionKey("session-x"), "{not json");
    expect(loadPlanRevision("session-x")).toEqual([]);
  });

  it("keeps only one draft — there is one plan, so a second entry is corruption not history", () => {
    localStorage.setItem(
      planRevisionKey("session-y"),
      JSON.stringify([
        { text: "first", original: "o" },
        { text: "second", original: "o" },
      ]),
    );
    expect(loadPlanRevision("session-y")).toEqual([{ text: "first", original: "o" }]);
  });

  it("clearPlanRevision empties it", () => {
    setPlanRevision("a\nb\nc", "a\nb");
    clearPlanRevision();
    expect(getPlanRevision()).toBeNull();
  });
});

describe("countChangedLines", () => {
  it("counts an added step", () => {
    expect(countChangedLines({ text: "a\nb\nc", original: "a\nb" })).toBe(1);
  });

  it("counts a rewritten step", () => {
    expect(countChangedLines({ text: "a\nB", original: "a\nb" })).toBe(1);
  });

  it("counts a removed step", () => {
    expect(countChangedLines({ text: "a", original: "a\nb" })).toBe(1);
  });
});

describe("formatPlanRevisionMessage", () => {
  const message = formatPlanRevisionMessage({ text: "先写测试\n再实现", original: "实现\n测试" });

  it("asks the MODEL to re-plan with its own tool — the harness never writes the plan", () => {
    expect(message).toContain("todo_write");
  });

  it("keeps the model's judgement while ruling out silent divergence", () => {
    expect(message).toContain("不可行");
    expect(message).toContain("不要默默跳过");
  });

  it("numbers the steps in the order the user left them", () => {
    expect(message).toContain("1. 先写测试");
    expect(message).toContain("2. 再实现");
  });

  it("does not double-number a user who typed their own numbers", () => {
    const numbered = formatPlanRevisionMessage({ text: "1. 先写测试\n2) 再实现", original: "x" });
    expect(numbered).toContain("1. 先写测试");
    expect(numbered).toContain("2. 再实现");
    expect(numbered).not.toContain("1. 1.");
  });
});
