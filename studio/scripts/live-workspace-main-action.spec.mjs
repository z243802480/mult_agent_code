import { spawn } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";

const studioDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const workspace = path.resolve(studioDir, "..");
const port = Number(process.env.ASTERIA_STUDIO_LIVE_PORT || 18795);

let server;

test.beforeAll(async () => {
  server = spawn(
    process.execPath,
    ["server.mjs", "--workspace", workspace, "--port", String(port)],
    {
      cwd: studioDir,
      stdio: ["ignore", "pipe", "pipe"],
      env: { ...process.env, ASTERIA_STUDIO_CHAT_BACKEND: "local" },
    },
  );
  await waitForHealth();
});

test.afterAll(async () => {
  server?.kill("SIGTERM");
  await new Promise((resolve) => setTimeout(resolve, 200));
});

test("Studio live workspace main action matches runtime evidence", async ({ page }) => {
  const overview = await fetchJson(`http://127.0.0.1:${port}/api/overview`);
  const latestRunId = String(overview.runs?.[0]?.run_id ?? "");
  test.skip(!latestRunId, "live workspace has no runtime run to inspect");

  const detail = await fetchJson(
    `http://127.0.0.1:${port}/api/runs/${encodeURIComponent(latestRunId)}`,
  );
  const action = detail.main_action ?? {};
  const label = String(action.label ?? "").trim();
  if (!label) throw new Error("latest live run did not expose main_action.label");

  await page.goto(`http://127.0.0.1:${port}/`);
  await expect(
    page.locator(".conversationTurn", { hasText: runtimeGoalTitle(detail) }),
  ).toBeVisible({ timeout: 15_000 });
  if (label.toLowerCase() !== "done" && String(action.kind ?? "").toLowerCase() !== "done") {
    await expect(page.locator(".runtimeActionButton").filter({ hasText: label })).toBeVisible({
      timeout: 15_000,
    });
  }
  await expect(page.locator(".conversationTurn")).toBeVisible({ timeout: 15_000 });
  await expect(page.locator(".turnMiddleBadge")).toBeVisible({ timeout: 15_000 });

  await page.getByText("Debug / Ops Console").click();
  await expect(page.getByText("Main action source")).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText(`kind=${String(action.kind ?? "unknown")}`)).toBeVisible();

  const progressButton = page
    .locator(".evidenceBlock", { hasText: "User progress" })
    .locator(".evidenceSelectableList button")
    .last();
  await expect(progressButton).toBeVisible({ timeout: 15_000 });
  await progressButton.click();
  await expect(page.locator(".evidenceDetailPanel", { hasText: "progress" })).toBeVisible();
  await expect(page.locator(".detailTitle")).toBeVisible();

  const workerButton = page.locator(".workerTopologyItem").first();
  await expect(workerButton).toBeVisible({ timeout: 15_000 });
  await workerButton.click();
  await expect(page.locator(".evidenceDetailPanel", { hasText: "worker" })).toBeVisible();

  const runFileButton = page.locator(".runFiles button").first();
  await expect(runFileButton).toBeVisible({ timeout: 15_000 });
  await runFileButton.click();
  await expect(page.locator(".preview pre, .preview p")).toBeVisible({ timeout: 15_000 });
});

function runtimeGoalTitle(detail) {
  return String(
    detail.goal_spec?.normalized_goal ??
      detail.goal_spec?.original_goal ??
      detail.run?.goal ??
      detail.run?.summary ??
      "No goal selected yet",
  );
}

async function waitForHealth() {
  const deadline = Date.now() + 10_000;
  let stderr = "";
  server.stderr.on("data", (chunk) => {
    stderr += String(chunk);
  });
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`http://127.0.0.1:${port}/api/health`);
      const health = await response.json();
      if (health.ok) return;
    } catch {}
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(`Studio live server did not become healthy. stderr=${stderr}`);
}

async function fetchJson(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${url} returned ${response.status}: ${await response.text()}`);
  return response.json();
}
