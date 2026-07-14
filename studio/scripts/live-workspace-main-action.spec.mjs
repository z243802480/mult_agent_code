// Inspector evidence surfaces.
//
// This spec used to read the DEVELOPER'S OWN .asteria/runs (workspace = the repo itself) and assert
// the workspace's latest run appeared on the main thread. Both halves were dead: a run only reaches
// the thread through the session that owns it, and a spec keyed to whatever run happens to be on the
// local machine can never run in CI — with no runs it just skips, i.e. covers nothing. Rewritten
// hermetic: seed a known run, then assert the Inspector really renders that run's evidence (the
// evidence surface is the one thing this spec covered that nothing else does).
import { promises as fs } from "node:fs";
import { expect, test } from "@playwright/test";
import {
  RUN_ID,
  createFixtureWorkspace,
  seedSessionOwningRun,
  startStudioServer,
  waitForHealth,
} from "./studio-fixture.mjs";

const port = Number(process.env.ASTERIA_STUDIO_LIVE_PORT || 18795);

let workspace;
let server;

test.beforeAll(async () => {
  ({ workspace } = await createFixtureWorkspace());
  await seedSessionOwningRun(workspace);
  server = startStudioServer(workspace, port);
  await waitForHealth(server, port);
});

test.afterAll(async () => {
  server?.kill("SIGTERM");
  await new Promise((resolve) => setTimeout(resolve, 200));
  if (workspace) await fs.rm(workspace, { recursive: true, force: true });
});

test("the Inspector renders the run's evidence", async ({ page }) => {
  await page.goto(`http://127.0.0.1:${port}/`);

  const evidenceTab = page.locator(".inspectorTab", { hasText: "证据" });
  await expect(evidenceTab).toBeVisible({ timeout: 15_000 });
  await evidenceTab.click();

  // Evidence blocks are built from the run's real artifacts (user_progress / workers / cost / ...).
  await expect(page.locator(".evidenceBlock").first()).toBeVisible({ timeout: 15_000 });

  // Selecting a piece of evidence opens its detail — the raw-evidence path the Inspector exists for.
  const progressButton = page
    .locator(".evidenceBlock", { hasText: "用户进度" })
    .locator(".evidenceSelectableList button")
    .first();
  await expect(progressButton).toBeVisible({ timeout: 15_000 });
  await progressButton.click();
  await expect(page.locator(".evidenceDetailPanel")).toBeVisible();

  // The run's files are listed and readable straight from the run directory — the raw artifact, not
  // a summary of it. Clicking one loads its actual contents into the detail panel.
  const runFileButton = page.locator(".runFiles button").first();
  await expect(runFileButton).toBeVisible({ timeout: 15_000 });
  const fileName = (await runFileButton.innerText()).trim();
  await runFileButton.click();
  const detail = page.locator(".evidenceDetailPanel");
  await expect(detail).toContainText(fileName, { timeout: 15_000 });
  await expect(detail).toContainText(`.asteria/runs/${RUN_ID}/`);
  await expect(detail.locator(".copyablePre")).toBeVisible();
});
