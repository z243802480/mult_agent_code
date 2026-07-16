import { promises as fs } from "node:fs";
import { expect, test } from "@playwright/test";
import {
  GOAL,
  createFixtureWorkspace,
  seedSessionOwningRun,
  startStudioServer,
  waitForHealth,
} from "./studio-fixture.mjs";

const port = Number(process.env.ASTERIA_STUDIO_INTERACTIVE_PORT || 18860);

let workspace;
let server;

test.beforeEach(async () => {
  ({ workspace } = await createFixtureWorkspace());
  server = startStudioServer(workspace, port);
  await waitForHealth(server, port);
});

test.afterEach(async () => {
  server?.kill("SIGTERM");
  await new Promise((resolve) => setTimeout(resolve, 200));
  if (process.env.KEEP_INTERACTIVE_WORKSPACE) {
    console.log(`Keeping interactive smoke workspace: ${workspace}`);
    return;
  }
  if (workspace) await fs.rm(workspace, { recursive: true, force: true });
});

// A session with no events shows ONLY the welcome prompt. It must never render the workspace's
// leftover run — its review bar, its pending decision, its runtime vocabulary belong to the session
// that actually ran it (Thread.tsx early return; AGENTS.md §9). The previous version of this spec
// asserted the exact opposite, which is why it rotted: it was written against the old "render the
// workspace's latest run anywhere" behaviour that we deliberately removed.
test("an empty session shows the welcome prompt, never the workspace's leftover run", async ({
  page,
}) => {
  await page.goto(`http://127.0.0.1:${port}/`);
  await expect(page.locator(".emptyThread")).toBeVisible();
  await expect(page.locator(".conversationTurn")).toHaveCount(0);
  await expect(page.locator(".runtimeSnapshot")).toHaveCount(0);
});

test("a session that owns a run surfaces its decision, then the next action", async ({ page }) => {
  await seedSessionOwningRun(workspace);
  await page.goto(`http://127.0.0.1:${port}/`);

  await expect(page.locator(".conversationTurn", { hasText: GOAL })).toBeVisible();
  // Maintainer machinery stays off the main thread.
  await expect(page.locator(".workflowMonitorCompact")).toHaveCount(0);
  await expect(page.locator(".threadProcessControls")).toHaveCount(0);
  await expect(page.locator(".runtimeLoopSignals")).toHaveCount(0);

  // The pending decision is surfaced in the user's language, below the turn it belongs to.
  await expect(page.locator(".runtimeSnapshot")).toContainText("有 1 个决定需要你处理。");
  await expect(page.getByText("Choose the next Studio path.")).toBeVisible();
  const actionFollowsTurn = await page.evaluate(() => {
    const turn = document.querySelector(".conversationTurn");
    const action = document.querySelector(".runtimeSnapshot");
    return Boolean(
      turn && action && turn.compareDocumentPosition(action) & Node.DOCUMENT_POSITION_FOLLOWING,
    );
  });
  expect(actionFollowsTurn).toBe(true);

  // Resolving the decision advances the run to its next action.
  await page.locator(".decisionOptions button").filter({ hasText: "Continue" }).click();
  await expect(page.locator(".runtimeActionButton").filter({ hasText: "查看改动" })).toBeVisible({
    timeout: 30_000,
  });
  await expect(page.locator(".runtimeActionButton").filter({ hasText: "标记完成" })).toBeVisible();

  // "Review changes" opens the side panel. NOTE: clicking a next action RUNS it — the click is the
  // consent, so no second permission card appears. An earlier build asked again and reported success
  // without running anything (the "标记完成 lies" bug); do not re-add that gate here.
  await page.getByTitle(/隐藏侧栏/).click();
  await expect(page.locator(".appShell.panelCollapsed")).toBeVisible();
  await page.locator(".runtimeActionButton").filter({ hasText: "查看改动" }).click();
  await expect(page.locator(".appShell.panelOpen")).toBeVisible();
});

test("the composer exposes the product slash actions", async ({ page }) => {
  await page.goto(`http://127.0.0.1:${port}/`);
  // Wait for bootstrap to settle BEFORE typing: the thread only renders the welcome state once
  // sessions/runs have loaded, and that late render remounts the composer — typing into it first
  // (fast enough locally, not on CI) gets the draft wiped and the slash menu never opens.
  await expect(page.locator(".emptyThread")).toBeVisible({ timeout: 15_000 });
  await page.locator(".composer textarea").fill("/");
  await expect(page.locator(".slashMenu")).toBeVisible();
  await expect(page.locator(".slashMenu button").filter({ hasText: "/plan" })).toBeVisible();
  await expect(page.locator(".slashMenu button").filter({ hasText: "/goal" })).toBeVisible();
  await page.locator(".slashMenu button").filter({ hasText: "/plan" }).click();
  await expect(page.locator(".composer textarea")).toHaveValue(/制定计划/);
});
