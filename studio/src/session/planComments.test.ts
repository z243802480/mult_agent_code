import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  addPlanComment,
  clearPlanComments,
  formatPlanCommentsMessage,
  getPlanComments,
  loadPlanComments,
  MAX_PLAN_COMMENTS,
  planCommentsKey,
  removePlanComment,
  savePlanComments,
  setPlanCommentSession,
} from "./planComments";

function fakeStorage() {
  const map = new Map<string, string>();
  return {
    getItem: (key: string) => map.get(key) ?? null,
    setItem: (key: string, value: string) => void map.set(key, value),
    removeItem: (key: string) => void map.delete(key),
    dump: () => map,
  };
}

describe("planComments persistence", () => {
  it("round-trips per session, drops malformed entries, never throws on corrupt JSON", () => {
    const store = fakeStorage();
    savePlanComments("s1", [{ id: "p-1", step: 2, title: "写测试", text: "不要动 schema" }], store);
    expect(loadPlanComments("s1", store)).toHaveLength(1);
    expect(loadPlanComments("s2", store)).toHaveLength(0);
    store.setItem(
      planCommentsKey("s1"),
      JSON.stringify([
        { step: 0, text: "步号非法" },
        { step: 1 },
        "junk",
        { step: 3, text: "好的" },
      ]),
    );
    const loaded = loadPlanComments("s1", store);
    expect(loaded).toHaveLength(1);
    expect(loaded[0].step).toBe(3);
    store.setItem(planCommentsKey("s1"), "{nope");
    expect(loadPlanComments("s1", store)).toEqual([]);
  });
});

describe("planComments module store", () => {
  beforeEach(() => {
    vi.stubGlobal("localStorage", fakeStorage());
    setPlanCommentSession("__reset__");
    setPlanCommentSession("session-a");
  });

  it("add/remove/clear mutate the active session's list and enforce the cap", () => {
    addPlanComment(2, "写测试", "不要动 schema");
    addPlanComment(3, "跑验证", "  ");
    expect(getPlanComments()).toHaveLength(1);
    for (let i = 0; i < MAX_PLAN_COMMENTS + 5; i++) addPlanComment(1, "t", `第 ${i} 条`);
    expect(getPlanComments()).toHaveLength(MAX_PLAN_COMMENTS);
    removePlanComment(getPlanComments()[0].id);
    expect(getPlanComments()).toHaveLength(MAX_PLAN_COMMENTS - 1);
    clearPlanComments();
    expect(getPlanComments()).toEqual([]);
  });

  it("switching sessions swaps the visible list", () => {
    addPlanComment(1, "步骤", "意见 A");
    setPlanCommentSession("session-b");
    expect(getPlanComments()).toEqual([]);
    setPlanCommentSession("session-a");
    expect(getPlanComments()).toHaveLength(1);
  });
});

describe("formatPlanCommentsMessage", () => {
  it("renders a numbered structured reference with step number and title", () => {
    const message = formatPlanCommentsMessage([
      { id: "p-1", step: 2, title: "写测试", text: "不要动 schema" },
      { id: "p-2", step: 4, title: "", text: "这一步可以跳过" },
    ]);
    expect(message).toContain("请在执行时遵守下面这些对当前计划的意见：");
    expect(message).toContain("1. 对计划第 2 步「写测试」：不要动 schema");
    expect(message).toContain("2. 对计划第 4 步：这一步可以跳过");
  });
});
