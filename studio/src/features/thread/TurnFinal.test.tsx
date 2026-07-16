import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import type { NarrativeStep, StudioEvent } from "../../types";
import { TurnFinal } from "./TurnFinal";

function finalStep(contentDelta: string): NarrativeStep {
  const event = {
    event_id: "e-final",
    session_id: "s",
    type: "assistant_delta",
    status: "completed",
    title: "",
    summary: "",
    created_at: "2026-07-16T10:00:00.000Z",
    content_delta: contentDelta,
  } as StudioEvent;
  return {
    id: "step-final",
    kind: "final",
    label: "final",
    title: "",
    summary: "",
    status: "completed",
    events: [event],
    defaultOpen: false,
  } as NarrativeStep;
}

function html(text: string): string {
  return renderToStaticMarkup(<TurnFinal step={finalStep(text)} middleSteps={[]} />);
}

describe("TurnFinal lead/details split (answers are never amputated)", () => {
  it("renders a multi-section model answer in full — no disclosure, every section visible", () => {
    // The old heuristic ("≥2 headings → collapse everything after the first section") hid the
    // actual answer body behind a disclosure labeled 运行详情.
    const out = html(
      "# 快速排序详解\n\n## 一、原理\n\n分治法。\n\n## 二、步骤\n\n选基准、分区、递归。",
    );
    expect(out).not.toContain("turnFinalDetails");
    expect(out).toContain("一、原理");
    expect(out).toContain("分治法。");
    expect(out).toContain("二、步骤");
    expect(out).toContain("选基准、分区、递归。");
  });

  it("still folds a legacy harness-authored tail (known section names only)", () => {
    const out = html(
      "已完成本次任务。\n\n## 验证\n\n- pytest 2 passed\n\n## 执行过程\n\n步骤记录。",
    );
    expect(out).toContain("turnFinalDetails");
    expect(out).toContain("运行详情");
    expect(out).toContain("已完成本次任务。");
    // The tail content lives inside the disclosure, after the summary label.
    const detailsStart = out.indexOf("turnFinalDetails");
    expect(out.indexOf("pytest 2 passed")).toBeGreaterThan(detailsStart);
    expect(out.indexOf("执行过程")).toBeGreaterThan(detailsStart);
  });

  it("keeps a plain conversational final untouched", () => {
    const out = html("已在 mathf.py 中实现 factorial(n)，测试通过。");
    expect(out).not.toContain("turnFinalDetails");
    expect(out).toContain("factorial(n)");
  });
});
