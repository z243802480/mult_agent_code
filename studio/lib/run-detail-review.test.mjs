import { mkdtemp, mkdir, writeFile, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { expect, it } from "vitest";
import { createRunDetailReader } from "./run-detail-reader.mjs";

it("reads the native Review independently of an earlier final summary", async () => {
  const workspace = await mkdtemp(path.join(os.tmpdir(), "asteria-review-reader-"));
  try {
    const runId = "run-review-control";
    const runDir = path.join(workspace, ".asteria", "runs", runId);
    await mkdir(runDir, { recursive: true });
    const report = {
      run_id: runId,
      overall: { status: "partial", score: null, reason: "A condition is unchecked" },
      goal_eval: { requirement_coverage: null },
      outcome_eval: { verification_pass_rate: 1 },
    };
    await writeFile(path.join(runDir, "eval_report.json"), JSON.stringify(report));
    await writeFile(
      path.join(runDir, "final_report_summary.json"),
      JSON.stringify({ review_status: "pass" }),
    );
    const reader = createRunDetailReader({
      getWorkspace: () => workspace,
      python: "python",
      moduleName: "asteria_runtime",
    });
    const detail = await reader.readRunDetail(runId);
    expect(detail.eval_report).toEqual(report);
    expect(detail.final_report_summary.review_status).toBe("pass");
  } finally {
    // Only the unique directory created by this test is owned and removed here.
    expect(path.dirname(path.resolve(workspace))).toBe(path.resolve(os.tmpdir()));
    await rm(workspace, { recursive: true, force: true });
  }
});
