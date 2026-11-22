import { promises as fs } from "node:fs";
import os from "node:os";
import path from "node:path";
import { expect, test } from "@playwright/test";
import { controlledBinding } from "./review-binding-fixture.mjs";
import {
  RUN_ID,
  createFixtureWorkspace,
  seedSessionOwningRun,
  startStudioServer,
  waitForHealth,
} from "./studio-fixture.mjs";

const port = 18869;
let workspace, runDir, server;

test.beforeAll(async () => {
  ({ workspace, runDir } = await createFixtureWorkspace());
  await seedSessionOwningRun(workspace);
  // These are controlled presentation records, not real model or command execution.
  const session = path.join(workspace, ".asteria/studio/sessions/session-spec-owner/events.jsonl");
  const events = (await fs.readFile(session, "utf8")).trim().split("\n").map(JSON.parse);
  events.splice(1, 0, {
    event_id: "check-control",
    type: "tool_observation",
    run_id: RUN_ID,
    transcript_kind: "verification",
    telemetry: { correctness_status: "pass" },
    status: "completed",
    summary: "Recorded execution check",
    created_at: "2099-01-01T00:00:00.500Z",
  });
  await fs.writeFile(session, events.map(JSON.stringify).join("\n") + "\n");
  server = startStudioServer(workspace, port);
  await waitForHealth(server, port);
});

test.afterAll(async () => {
  if (server && server.exitCode === null) {
    const closed = new Promise((resolve) => server.once("close", resolve));
    server.kill("SIGTERM");
    await closed;
  }
  if (workspace) {
    expect(path.dirname(path.resolve(workspace))).toBe(path.resolve(os.tmpdir()));
    await fs.rm(workspace, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 });
  }
});

test("native Review remains visible beside passing execution checks and preserves an unscored pass", async ({
  page,
}) => {
  await fs.writeFile(path.join(runDir, "task_plan.json"), JSON.stringify({ tasks: [] }));
  const artifactEval = await controlledBinding(workspace, runDir, RUN_ID);
  const writeReview = (status) =>
    fs.writeFile(
      path.join(runDir, "eval_report.json"),
      JSON.stringify({
        run_id: RUN_ID,
        artifact_eval: artifactEval,
        overall: { status, score: null, reason: "A source condition needs independent assessment" },
        goal_eval: { requirement_coverage: null },
        outcome_eval: { verification_pass_rate: 1 },
      }),
    );
  await writeReview("partial");
  await page.goto(`http://127.0.0.1:${port}/`);
  const note = page.locator(".turnUnverifiedNote").last();
  await expect(note).toContainText("评审未通过", { timeout: 15000 });
  await expect(note).toContainText("A source condition needs independent assessment");
  await expect(page.locator(".turnVerifiedBadge").last()).toContainText("执行检查通过");
  await writeReview("pass");
  await page.reload();
  await expect(note).toContainText("评审通过", { timeout: 15000 });
  await expect(note).toContainText("评分未评定");
  await expect(note).toContainText("覆盖率未评定");
  const goalFile = path.join(runDir, "goal_spec.json");
  const originalGoal = await fs.readFile(goalFile, "utf8");
  await fs.writeFile(goalFile, originalGoal + "\n");
  await page.reload();
  await expect(note).toContainText("评审已过期", { timeout: 15000 });
  await expect(note).toContainText("请重新评审");
  await expect(page.locator(".runtimeActionButton").filter({ hasText: "标记完成" })).toHaveCount(0);
});
