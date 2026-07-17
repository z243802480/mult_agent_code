// G6 刀二 — editing the plan body and asking the model to re-plan from it.
//
// Why a real browser: the whole surface is interaction (type into a textarea, Ctrl+Enter, submit)
// and the vitest harness renders static markup — it can assert the button exists but never that
// pressing it does anything. That gap is the shape of 1.2.103 (a component verified, a system
// claimed), so the flow is pinned here instead.
import { promises as fs } from "node:fs";
import path from "node:path";
import { expect, test } from "@playwright/test";
import {
  RUN_ID,
  createFixtureWorkspace,
  seedSessionOwningRun,
  startStudioServer,
  waitForHealth,
} from "./studio-fixture.mjs";

const port = Number(process.env.ASTERIA_STUDIO_PLAN_EDIT_PORT || 18863);

let workspace;
let server;

/**
 * The checklist renders from the run's own model_todos.json (planModel.derivePlan's first source).
 * Written here rather than in studio-fixture.mjs: a plan in the SHARED fixture would put a
 * checklist into every other spec's thread, and none of them asked for one.
 */
async function seedPlan(root) {
  const runDir = path.join(root, ".asteria", "runs", RUN_ID);
  await fs.mkdir(runDir, { recursive: true });
  await fs.writeFile(
    path.join(runDir, "model_todos.json"),
    JSON.stringify({
      schema_version: "0.1.0",
      run_id: RUN_ID,
      update_reason: "",
      items: [
        { id: "todo-1", content: "实现 power 函数", status: "pending" },
        { id: "todo-2", content: "写测试", status: "pending" },
      ],
    }),
    "utf8",
  );
}

test.beforeEach(async () => {
  ({ workspace } = await createFixtureWorkspace());
  await seedPlan(workspace);
  await seedSessionOwningRun(workspace);
  server = startStudioServer(workspace, port);
  await waitForHealth(server, port);
});

test.afterEach(async () => {
  server?.kill("SIGTERM");
  await new Promise((resolve) => setTimeout(resolve, 200));
  // Windows releases handles lazily; without the retries teardown fails on EBUSY and reds a green
  // test. See 1.2.106 — the same flake, already paid for once.
  if (workspace) {
    await fs.rm(workspace, { recursive: true, force: true, maxRetries: 10, retryDelay: 250 });
  }
});

async function openPlanEditor(page) {
  await page.goto(`http://127.0.0.1:${port}/`);
  const checklist = page.locator(".planChecklist");
  await expect(checklist).toBeVisible();
  if ((await checklist.getAttribute("class"))?.includes("open") === false) {
    await page.locator(".planChecklistHead").click();
  }
  await page.getByRole("button", { name: "编辑计划" }).click();
  return page.locator(".planRevisionEditor textarea");
}

test("the editor opens prefilled with the plan that is actually there", async ({ page }) => {
  const editor = await openPlanEditor(page);
  // Editing means editing, not retyping — and the prefill must be the REAL plan, not a placeholder.
  await expect(editor).toHaveValue("实现 power 函数\n写测试");
});

test("an edited plan lands in the tray and the checklist keeps showing the real plan", async ({
  page,
}) => {
  const editor = await openPlanEditor(page);
  await editor.fill("先写测试\n再实现 power 函数\n跑一遍");
  await editor.press("Control+Enter");

  await expect(page.locator(".diffCommentTray")).toContainText("改过的计划待提交");
  // The honesty invariant: nothing has re-planned yet, so the list must still be the old one.
  const items = page.locator(".planItemText");
  await expect(items.nth(0)).toHaveText("实现 power 函数");
  await expect(items.nth(1)).toHaveText("写测试");
  await expect(page.locator(".planItems")).not.toContainText("跑一遍");
});

test("an untouched plan is not a revision — it never reaches the tray", async ({ page }) => {
  const editor = await openPlanEditor(page);
  // Re-saving the plan unchanged must not spend a turn asking the model to re-plan into what it has.
  await editor.press("Control+Enter");
  await expect(page.locator(".diffCommentTray")).toHaveCount(0);
});

test("submitting sends the rewrite to the model as words, through the normal turn", async ({
  page,
}) => {
  const editor = await openPlanEditor(page);
  await editor.fill("先写测试\n再实现 power 函数");
  await editor.press("Control+Enter");

  const sent = page.waitForRequest(
    (request) => request.url().includes("/messages") && request.method() === "POST",
  );
  await page.getByRole("button", { name: "提交意见" }).click();
  const body = (await sent).postDataJSON();

  // The model is asked to re-plan with its own tool — the harness writes no plan file (ADR-0016).
  expect(body.message).toContain("todo_write");
  expect(body.message).toContain("1. 先写测试");
  expect(body.message).toContain("2. 再实现 power 函数");
  expect(body.message).toContain("不要默默跳过");
});
