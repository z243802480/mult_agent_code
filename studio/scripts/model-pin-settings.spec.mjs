// G8-b knife two: the per-tier model pin, exercised the way a user actually uses it.
//
// Why Playwright and not a unit test: the pin commits on BLUR, and blur/focusout only fire in a
// document that genuinely has focus. Nothing else in this repo can prove the handler runs — the
// settings smoke proves the ENDPOINT, run-flags-unit proves the COLD/WARM agreement, and neither
// would notice if the input never called save at all. That gap is exactly the shape of 1.2.103
// (a component verified, a system claimed).
import { spawn } from "node:child_process";
import { promises as fs } from "node:fs";
import path from "node:path";
import { expect, test } from "@playwright/test";
import { createFixtureWorkspace, startStudioServer, waitForHealth } from "./studio-fixture.mjs";

const port = Number(process.env.ASTERIA_STUDIO_MODEL_PIN_PORT || 18862);

let workspace;
let server;

// The tier rows render from `doctor.routes`, and `doctor` exits non-zero on an uninitialised
// workspace — the BFF then drops the whole payload, so the rows (and these inputs) never appear.
// The shared fixture writes its config by hand and never inits, hence this extra step here rather
// than in studio-fixture.mjs, where it would slow every other spec down for nothing.
function initWorkspace(root) {
  return new Promise((resolve, reject) => {
    const init = spawn("python", ["-m", "asteria_runtime", "init", "--root", root], {
      cwd: path.resolve(path.dirname(new URL(import.meta.url).pathname.slice(1)), ".."),
      stdio: "ignore",
    });
    init.on("exit", (code) => (code === 0 ? resolve() : reject(new Error(`init exit ${code}`))));
    init.on("error", reject);
  });
}

test.beforeEach(async () => {
  ({ workspace } = await createFixtureWorkspace());
  await initWorkspace(workspace);
  server = startStudioServer(workspace, port);
  await waitForHealth(server, port);
});

test.afterEach(async () => {
  server?.kill("SIGTERM");
  await new Promise((resolve) => setTimeout(resolve, 200));
  if (workspace) await fs.rm(workspace, { recursive: true, force: true });
});

async function openModelSettings(page) {
  await page.goto(`http://127.0.0.1:${port}/`);
  await page.locator('button[aria-label="设置"], button[title="设置"]').first().click();
  await page.getByRole("button", { name: "模型与提供方", exact: true }).click();
  await expect(page.locator(".settingsRowInput").first()).toBeVisible();
}

function persistedSettings() {
  return fs
    .readFile(path.join(workspace, ".asteria", "studio", "settings.json"), "utf8")
    .then(JSON.parse)
    .catch(() => ({}));
}

test("typing a model name pins that tier, and only that tier", async ({ page }) => {
  await openModelSettings(page);
  const strong = page.locator(".settingsRowInput").first();

  await strong.fill("glm-4.5-air");
  await strong.blur();

  // The file the run path actually reads — not just the panel's own state.
  await expect.poll(async () => (await persistedSettings()).modelNames).toEqual({
    strong: "glm-4.5-air",
  });
  await expect(strong).toHaveValue("glm-4.5-air");
});

test("clearing the box unpins the tier instead of storing an empty model name", async ({ page }) => {
  await openModelSettings(page);
  const strong = page.locator(".settingsRowInput").first();

  await strong.fill("glm-4.5-air");
  await strong.blur();
  await expect.poll(async () => (await persistedSettings()).modelNames?.strong).toBe("glm-4.5-air");

  await strong.fill("");
  await strong.blur();
  // A model literally named "" would be sent to the provider as the model to call.
  await expect.poll(async () => (await persistedSettings()).modelNames).toEqual({});
});

test("a pin does not disturb the permission tier or the model strategy", async ({ page }) => {
  await openModelSettings(page);
  await page.getByRole("radio", { name: /重节省/ }).click();
  await expect
    .poll(async () => (await persistedSettings()).modelStrategy)
    .toBe("economy");

  await page.locator(".settingsRowInput").first().fill("glm-4.5-air");
  await page.locator(".settingsRowInput").first().blur();

  await expect.poll(async () => (await persistedSettings()).modelNames?.strong).toBe("glm-4.5-air");
  // The settings endpoint is a patch: each panel writes its own field and leaves the rest alone.
  expect((await persistedSettings()).modelStrategy).toBe("economy");
});

test("the placeholder shows the model the tier resolves to today", async ({ page }) => {
  await openModelSettings(page);
  // An empty box must say what "leave it alone" means, rather than making the user guess.
  const placeholder = await page.locator(".settingsRowInput").first().getAttribute("placeholder");
  expect(placeholder).toBeTruthy();
  expect(placeholder).not.toBe("");
});
