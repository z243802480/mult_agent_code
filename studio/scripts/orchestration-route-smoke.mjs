/**
 * Orchestration route smoke — model-readable catalog drives Studio routing.
 */
import { spawn } from "node:child_process";
import { promises as fs } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const studioDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = path.resolve(studioDir, "..");
const python = process.env.ASTERIA_PYTHON || "python";
const workspace = await fs.mkdtemp(path.join(os.tmpdir(), "asteria-orchestration-route-"));

await setupAcceptedWorkspace(workspace);

const routed = JSON.parse(
  await runPythonCapture([
    "-m",
    "asteria_runtime",
    "route",
    "--root",
    workspace,
    "--rules-only",
    "--json",
    "再给 greet_cli 增加 --quiet 参数并补测试",
  ]),
);

assert(
  routed.capability_id === "session_continue_execute",
  `expected warm continue, got ${routed.capability_id}`,
);
assert(routed.studio_mode === "continue", `expected continue mode, got ${routed.studio_mode}`);
assert(
  Array.isArray(routed.catalog?.capabilities),
  "catalog should expose capabilities to callers",
);

console.log("Orchestration route smoke passed");

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

async function setupAcceptedWorkspace(target) {
  const repo = repoRoot.replace(/\\/g, "/");
  const script = `
from pathlib import Path
import sys
root = Path(sys.argv[1])
repo = Path("${repo}")
sys.path.insert(0, str(repo))
from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.commands.plan_command import PlanCommand
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.run_store import RunStore
from asteria_runtime.storage.schema_validator import SchemaValidator
from tests.integration.test_plan_command import FakePlanClient

InitCommand(root).run()
plan = PlanCommand(root, "Add --version", model_client=FakePlanClient()).run()
validator = SchemaValidator(repo / "schemas")
run_store = RunStore(root / ".asteria", validator)
store = JsonStore(validator)
run_dir = run_store.run_dir(plan.run_id)
run = run_store.load_run(plan.run_id)
run["status"] = "completed"
run["current_phase"] = "ACCEPTED"
run_store.update_run(run)
task_plan = store.read(run_dir / "task_plan.json", "task_board")
for task in task_plan.get("tasks") or []:
    task["status"] = "done"
store.write(run_dir / "task_plan.json", task_plan, "task_board")
run_store.set_current_session(plan.run_id, "orchestration_route_smoke")
`;
  const completed = await runCommand([python, "-c", script, target], repoRoot);
  if (completed.code !== 0) {
    throw new Error(`workspace setup failed: ${completed.stderr || completed.stdout}`);
  }
}

function runCommand(command, cwd) {
  return new Promise((resolve) => {
    const child = spawn(command[0], command.slice(1), { cwd, env: process.env, windowsHide: true });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => {
      stdout += chunk.toString("utf8");
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk.toString("utf8");
    });
    child.on("close", (code) => resolve({ code, stdout, stderr }));
  });
}

async function runPythonCapture(args) {
  const completed = await runCommand([python, ...args], repoRoot);
  if (completed.code !== 0) throw new Error(completed.stderr || completed.stdout);
  return completed.stdout;
}
