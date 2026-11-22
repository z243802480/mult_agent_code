import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { NarrativeStep, RunDetailPayload, StudioEvent } from "../../types";
import { ConversationTurn } from "./ConversationTurn";
import { runVerificationHint } from "./runtimeNarrative";

const checked = [
  {
    events: [
      {
        transcript_kind: "verification",
        telemetry: { correctness_status: "pass" },
      } as unknown as StudioEvent,
    ],
  },
];
function detail(status: string, score: number | null = null): RunDetailPayload {
  return {
    ok: true,
    run_id: "run-consumption",
    run: { status: "completed" },
    final_report_summary: { review_status: "unknown" },
    eval_report: {
      run_id: "run-consumption",
      overall: { status, score, reason: "A required condition is not covered" },
      goal_eval: { requirement_coverage: null },
      outcome_eval: { verification_pass_rate: 1 },
    },
  } as unknown as RunDetailPayload;
}

describe("Review consumption keeps execution evidence and requirement judgments separate", () => {
  it("does not present a historical pass as current after content changes", () => {
    const d = detail("pass", 1);
    d.review_freshness = { status: "changed" };
    expect(runVerificationHint(d, checked)).toContain("评审已过期");
    expect(runVerificationHint(d, checked)).toContain("请重新评审");
  });
  it.each(["partial", "fail"])("does not hide %s review behind passing checks", (status) => {
    const text = runVerificationHint(detail(status), checked);
    expect(text).toContain("评审未通过");
    expect(text).toContain("A required condition is not covered");
  });
  it("shows unassessed score and coverage without downgrading semantic pass", () => {
    const text = runVerificationHint(detail("pass"), checked);
    expect(text).toContain("评审通过");
    expect(text).toContain("评分未评定");
    expect(text).toContain("覆盖率未评定");
    expect(text).not.toContain("100%");
  });
  it("keeps an unreviewed qualification even after execution checks passed", () => {
    const d = detail("unknown");
    delete (d as unknown as Record<string, unknown>).eval_report;
    expect(runVerificationHint(d, checked)).toContain("尚未评审");
  });
  it("prefers a native partial verdict over an earlier summary pass even when the run is blocked", () => {
    const d = detail("partial");
    d.run = { status: "blocked" };
    d.final_report_summary = { review_status: "pass" };
    expect(runVerificationHint(d, checked)).toContain("评审未通过");
  });
  it("labels a numeric coverage value as a model assessment", () => {
    const d = detail("pass", 0.8);
    d.eval_report!.goal_eval = { requirement_coverage: 0.6 };
    const text = runVerificationHint(d, checked);
    expect(text).toContain("评分 0.80");
    expect(text).toContain("模型评估覆盖率 60%");
    expect(text).toContain("非运行时独立核实");
  });
  it("uses a same-run persisted projection when native evidence is unavailable", () => {
    const d = detail("unknown");
    delete d.eval_report;
    d.final_report_summary = {
      review_status: "pass",
      review: {
        run_id: d.run_id,
        status: "pass",
        score: null,
        requirement_coverage: null,
        reason: "Stored judgment",
      },
    };
    expect(runVerificationHint(d, checked)).toContain("Stored judgment");
  });
  it("does not inherit another run's judgment", () => {
    const d = detail("pass");
    (d as unknown as { eval_report: { run_id: string } }).eval_report.run_id = "run-other";
    expect(runVerificationHint(d, checked)).toContain("尚未评审");
  });
  it("labels the existing badge as execution checks rather than all requirements", () => {
    const steps = [
      {
        id: "check",
        kind: "verification",
        title: "检查",
        status: "completed",
        events: checked[0].events,
      },
      {
        id: "final",
        kind: "final",
        title: "完成",
        summary: "交付结果",
        status: "completed",
        events: [{ event_id: "final", type: "final_answer", content_delta: "交付结果" }],
      },
    ] as unknown as NarrativeStep[];
    const html = renderToStaticMarkup(
      React.createElement(ConversationTurn, {
        steps,
        selected: null,
        onSelect: () => {},
        onPermit: async () => {},
        isLast: true,
        isRunning: false,
        expandSignal: null,
        runDetail: detail("partial"),
      }),
    );
    expect(html).toContain("执行检查通过");
    expect(html).toContain("评审未通过");
  });
});
