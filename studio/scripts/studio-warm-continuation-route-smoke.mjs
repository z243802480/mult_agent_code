/**
 * Studio warm-workspace routing smoke — a NEW goal in an accepted workspace must start a FRESH run,
 * NOT hijack the previous task via the old `--continue-session` shortcut.
 *
 * This smoke used to assert the opposite (`command.includes("--continue-session")`). That shortcut
 * skipped GoalSpec/Plan and reused the last task's scope, so an unrelated new goal got misrouted into
 * the finished task and thrashed/blocked — the exact bug that was later fixed (chat-routes.mjs
 * orchestrationCommandFor / resolveStudioExecutionRouteFallback: a completed/accepted run is idle, so
 * a new message is a new goal planned cold). The smoke now guards the FIX instead of the defect.
 * (Genuinely in-progress runs still resume via the separate "resume" path — not exercised here.)
 */
import { spawn } from "node:child_process";
import { promises as fs } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const studioDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = path.resolve(studioDir, "..");
const python = process.env.ASTERIA_PYTHON || "python";
const workspace = await fs.mkdtemp(path.join(os.tmpdir(), "asteria-studio-warm-route-"));
const port = Number(process.env.ASTERIA_STUDIO_WARM_ROUTE_PORT || 18796);

await setupAcceptedWorkspace(workspace);

const server = spawn(
  process.execPath,
  [
    "server.mjs",
    "--workspace",
    workspace,
    "--runtime-root",
    repoRoot,
    "--port",
    String(port),
    "--python",
    python,
  ],
  {
    cwd: studioDir,
    stdio: ["ignore", "pipe", "pipe"],
    env: { ...process.env, ASTERIA_STUDIO_CHAT_BACKEND: "local" },
  },
);

let stdout = "";
let stderr = "";
server.stdout.on("data", (chunk) => {
  stdout += String(chunk);
});
server.stderr.on("data", (chunk) => {
  stderr += String(chunk);
});

try {
  await waitForHealth();
  const { session } = await postJson("/api/studio/sessions", {});
  const sessionId = session?.session_id;
  assert(sessionId, "session should be created");

  await postJson(`/api/studio/sessions/${encodeURIComponent(sessionId)}/messages`, {
    message: "给 greet_cli 增加 --quiet 参数并补测试",
    mode: "run",
    permission: "allow",
  });

  // Non-empty command only: the merged view time-interleaves runtime user-progress rows (which can
  // carry `command: []`) with the session's launch row. The assertion's target is the LAUNCH
  // command; grabbing "first tool_start with any array" depended on the old (string-compare,
  // wrong) event ordering that happened to push runtime rows to the end.
  const { events } = await fetchEventsUntil(sessionId, (items) =>
    items.some(
      (event) =>
        event.type === "tool_start" && Array.isArray(event.command) && event.command.length > 0,
    ),
  );
  const toolStart = events.find(
    (event) =>
      event.type === "tool_start" && Array.isArray(event.command) && event.command.length > 0,
  );
  const command = toolStart?.command || [];
  assert(
    command.includes("run"),
    `a new goal should start a fresh run, got ${JSON.stringify(command)}`,
  );
  assert(
    !command.includes("--continue-session"),
    `a new goal must NOT hijack the finished task via --continue-session, got ${JSON.stringify(command)}`,
  );
  assert(
    command[command.length - 1] === "给 greet_cli 增加 --quiet 参数并补测试",
    `the fresh run must carry the new goal verbatim, got ${JSON.stringify(command)}`,
  );

  const routeEvent = events.find((event) => event.type === "intent_route");
  assert(Boolean(routeEvent), "an intent_route audit event should be emitted");

  console.log("Studio warm-workspace fresh-run route smoke passed");
} finally {
  server.kill("SIGTERM");
  await new Promise((resolve) => setTimeout(resolve, 200));
  await fs.rm(workspace, { recursive: true, force: true });
}

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
run_store.set_current_session(plan.run_id, "warm_route_smoke")
print(plan.run_id)
`;
  const completed = await runCommand([python, "-c", script, target], repoRoot);
  if (completed.code !== 0) {
    throw new Error(`workspace setup failed: ${completed.stderr || completed.stdout}`);
  }
}

function runCommand(command, cwd, envOverrides = {}) {
  return new Promise((resolve) => {
    const child = spawn(command[0], command.slice(1), {
      cwd,
      env: { ...process.env, ...envOverrides },
      windowsHide: true,
    });
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

async function waitForHealth() {
  const deadline = Date.now() + 10_000;
  let lastError;
  while (Date.now() < deadline) {
    try {
      const health = await fetchJson("/api/health");
      if (health.ok) return;
    } catch (error) {
      lastError = error;
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(
    `Studio server did not become healthy. stdout=${stdout} stderr=${stderr} last=${lastError}`,
  );
}

async function fetchJson(route) {
  const response = await fetch(`http://127.0.0.1:${port}${route}`);
  if (!response.ok) throw new Error(`${route} returned ${response.status}`);
  return response.json();
}

async function postJson(route, body) {
  const response = await fetch(`http://127.0.0.1:${port}${route}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok)
    throw new Error(`${route} returned ${response.status}: ${await response.text()}`);
  return response.json();
}

async function fetchEventsUntil(sessionId, predicate) {
  const route = `/api/studio/sessions/${encodeURIComponent(sessionId)}/events`;
  const deadline = Date.now() + 10_000;
  let latest = { events: [] };
  while (Date.now() < deadline) {
    latest = await fetchJson(route);
    if (predicate(latest.events || [])) return latest;
    if (server.exitCode !== null)
      throw new Error(`Studio server exited early. stdout=${stdout} stderr=${stderr}`);
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(
    `Timed out waiting for warm route tool_start. events=${(latest.events || []).length}`,
  );
}
