import { describe, expect, it } from "vitest";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import type { RunDetailPayload } from "../types";
import { contextBudgetSnapshot } from "../contextSummary";
import { ContextPanel } from "./ContextPanel";

// A realistic context_budget payload as produced by run-detail-reader.buildContextBudget from the
// runtime's context_budget_snapshots.jsonl (B10-a). Mirrors real test_project data (run-20260713-0003).
function budgetPayload(over: Record<string, unknown> = {}): RunDetailPayload {
  return {
    ok: true,
    run_id: "run-x",
    context_budget: {
      available: true,
      count: 1,
      latest: {
        task_id: "task-0001",
        scope: "task_context",
        estimated_tokens: 3446,
        window_tokens: 200000,
        ratio: 0.017,
        pressure_status: "within_budget",
        compaction_threshold: 0.75,
        hard_stop_threshold: 0.9,
        duplicate_estimated_tokens: 1097,
        duplicate_ref_count: 5,
        top_sections: [
          { name: "root_guidance", tokens: 1051 },
          { name: "recent_events", tokens: 426 },
        ],
        compact_boundary: {
          status: "not_required",
          recommended_action: "continue",
          estimated_tokens_delta: 2091,
        },
        ...(over.latest as Record<string, unknown>),
      },
      peak: {
        task_id: "task-0001",
        ratio: 0.017,
        pressure_status: "within_budget",
        ...(over.peak as Record<string, unknown>),
      },
    },
    ...over,
  } as unknown as RunDetailPayload;
}

describe("contextBudgetSnapshot", () => {
  it("projects the persisted snapshot (dedupe savings, sections, peak)", () => {
    const snap = contextBudgetSnapshot(budgetPayload());
    expect(snap).not.toBeNull();
    expect(snap?.duplicateRefs).toBe(5);
    expect(snap?.duplicateTokens).toBe(1097);
    expect(snap?.estimatedTokens).toBe(3446);
    expect(snap?.topSections[0]?.id).toBe("root_guidance");
    // not_required compaction is not treated as an actionable recommendation
    expect(snap?.compaction?.status).toBe("not_required");
    expect(snap?.peak?.ratio).toBe(0.017);
  });

  it("returns null when no budget snapshot was persisted", () => {
    expect(contextBudgetSnapshot({ ok: true, run_id: "r" } as RunDetailPayload)).toBeNull();
  });
});

describe("ContextPanel budget block", () => {
  it("renders the dedupe fact when there is duplicated context to reclaim", () => {
    const html = renderToStaticMarkup(
      React.createElement(ContextPanel, { runDetail: budgetPayload(), isRunning: false }),
    );
    expect(html).toContain("预算快照");
    expect(html).toMatch(/5 处重复/);
    expect(html).toMatch(/去重可省/);
  });

  it("surfaces the budget even when the run-level cost_report rollup is absent", () => {
    // The budget snapshot is independent evidence — it must not vanish just because contextWindowSummary
    // (cost_report) is null. This is the exact regression B10-a's render restructure guards against.
    const html = renderToStaticMarkup(
      React.createElement(ContextPanel, { runDetail: budgetPayload(), isRunning: false }),
    );
    expect(html).toContain("contextBudgetSnapshot");
  });

  it("stays silent for a healthy run with nothing actionable", () => {
    const clean = budgetPayload({
      latest: { duplicate_ref_count: 0, duplicate_estimated_tokens: 0 },
      peak: { ratio: 0.02 },
    });
    const html = renderToStaticMarkup(
      React.createElement(ContextPanel, { runDetail: clean, isRunning: false }),
    );
    expect(html).not.toContain("预算快照");
  });

  it("recommends compaction when the runtime's boundary says so", () => {
    const pressured = budgetPayload({
      latest: {
        duplicate_ref_count: 0,
        duplicate_estimated_tokens: 0,
        compact_boundary: {
          status: "recommended",
          recommended_action: "compact",
          estimated_tokens_delta: 8200,
        },
      },
    });
    const html = renderToStaticMarkup(
      React.createElement(ContextPanel, { runDetail: pressured, isRunning: false }),
    );
    expect(html).toContain("建议压缩");
  });
});
