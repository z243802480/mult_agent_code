import { promises as fs } from "node:fs";
import path from "node:path";
import os from "node:os";
import { controlledBinding } from "../scripts/review-binding-fixture.mjs";
import { afterEach, expect, it } from "vitest";
import { reviewFreshness } from "./review-freshness.mjs";

const owned = [];
afterEach(async () => {
  for (const root of owned.splice(0)) {
    expect(path.dirname(path.resolve(root))).toBe(path.resolve(os.tmpdir()));
    await fs.rm(root, { recursive: true, force: true, maxRetries: 5 });
  }
});

async function fixture() {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), "asteria-review-binding-"));
  owned.push(root);
  const runId = "run-binding",
    runDir = path.join(root, ".asteria/runs", runId);
  await fs.mkdir(runDir, { recursive: true });
  await fs.writeFile(path.join(runDir, "goal_spec.json"), JSON.stringify({ goal: "Original" }));
  await fs.writeFile(path.join(runDir, "task_plan.json"), JSON.stringify({ tasks: [] }));
  const report = {
    run_id: runId,
    overall: { status: "pass" },
    artifact_eval: await controlledBinding(root, runDir, runId),
  };
  return { root, runDir, runId, report };
}

it("binds current contents, ignores mtime and detects same-sized replacement", async () => {
  const f = await fixture(),
    file = path.join(f.runDir, "goal_spec.json");
  const check = () => reviewFreshness(f.root, f.runDir, f.runId, f.report);
  await fs.utimes(file, 1700000000, 1700000000);
  expect((await check()).status).toBe("current");
  const original = await fs.readFile(file);
  await fs.writeFile(file, original.toString().replace("Original", "Modified"));
  expect((await check()).status).toBe("changed");
  await fs.writeFile(file, original);
  expect((await check()).status).toBe("current");
});

it.each([
  "unbound",
  "cross-run",
  "duplicate",
  "missing-input",
  "incomplete",
  "protected",
  "traversal",
])("does not approve %s evidence", async (defect) => {
  const f = await fixture(),
    b = f.report.artifact_eval.review_binding;
  if (defect === "unbound") delete f.report.artifact_eval.review_binding;
  else if (defect === "cross-run") b.run_id = "run-other";
  else if (defect === "duplicate") b.files.push({ ...b.files[0] });
  else if (defect === "missing-input") b.files.shift();
  else if (defect === "incomplete") b.complete = false;
  else
    b.files.push({
      root: "workspace",
      path: defect === "protected" ? ".env" : "../outside",
      exists: false,
      bytes: 0,
      sha256: null,
    });
  expect((await reviewFreshness(f.root, f.runDir, f.runId, f.report)).status).not.toBe("current");
});

it("does not bind a missing required runtime input even when its absence is recorded", async () => {
  const f = await fixture();
  await fs.unlink(path.join(f.runDir, "task_plan.json"));
  Object.assign(
    f.report.artifact_eval.review_binding.files.find((row) => row.path === "task_plan.json"),
    { exists: false, bytes: 0, sha256: null },
  );
  expect((await reviewFreshness(f.root, f.runDir, f.runId, f.report)).status).toBe("unavailable");
});

it("maps an absolute artifact within the captured source root to its relative binding", async () => {
  const f = await fixture();
  await fs.writeFile(path.join(f.root, "AGENTS.md"), "Guidance\n");
  f.report.artifact_eval = await controlledBinding(f.root, f.runDir, f.runId);
  const file = path.join(f.runDir, "review-artifacts-control.json");
  const snapshot = JSON.parse(await fs.readFile(file, "utf8"));
  snapshot.workspace_root = f.root;
  snapshot.files = [{ path: path.join(f.root, "AGENTS.md") }];
  await fs.writeFile(file, JSON.stringify(snapshot));
  expect((await reviewFreshness(f.root, f.runDir, f.runId, f.report)).status).toBe("current");
});
