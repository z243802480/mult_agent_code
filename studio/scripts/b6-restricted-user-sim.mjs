/**
 * B6 restricted user simulation — fresh workspace, Studio API + user-doc CLI accept.
 */
import { copyFileSync, existsSync, readFileSync, rmSync } from "node:fs";
import { spawn } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const studioDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = path.resolve(studioDir, "..");
const workspace = process.env.B6_SIM_WORKSPACE || "h:/beta_user_sim/workspace";
const port = Number(process.env.B6_SIM_PORT || 8700 + Math.floor(Math.random() * 200));
const python = process.env.ASTERIA_PYTHON || "python";
const taskPack = JSON.parse(
  readFileSync(path.join(repoRoot, "benchmarks/beta_user_tasks.json"), "utf8"),
);
const taskId = process.env.B6_TASK_ID || "small_code_change";
const task = taskPack.tasks.find((item) => item.id === taskId);
if (!task) throw new Error(`unknown B6_TASK_ID: ${taskId}`);
const goalText = process.env.B6_GOAL_TEXT || task.goal;
const startedAt = Date.now();
const log = [];
const friction = { decide: 0, debug: 0, resume: 0 };

function note(step, detail) {
  const entry = { step, detail, elapsed_s: Math.round((Date.now() - startedAt) / 1000) };
  log.push(entry);
  console.log(`[${entry.elapsed_s}s] ${step}: ${detail}`);
}

if (existsSync(workspace)) {
  rmSync(workspace, { recursive: true, force: true });
}

await runPython([
  "-m",
  "asteria_runtime",
  "init",
  "--root",
  workspace,
  "--north-star-title",
  "Beta sim",
]);
note("A4", "init fresh workspace");

if (taskId === "small_code_change") {
  copyFileSync(
    path.join(repoRoot, "benchmarks/fixtures/s13_clean_run/greet_cli.py"),
    path.join(workspace, "greet_cli.py"),
  );
  note("A4b", "starter greet_cli.py (maintainer-provided)");
} else {
  note("A4b", `blank workspace for ${taskId}`);
}

for (const tier of ["strong", "medium"]) {
  const check = JSON.parse(
    await runPythonCapture([
      "-m",
      "asteria_runtime",
      "model-check",
      "--root",
      workspace,
      "--tier",
      tier,
      "--json",
    ]),
  );
  if (!check.call_ok) throw new Error(`model-check ${tier} failed`);
}
note("A3", "model routes ok");

const preview = JSON.parse(
  await runPythonCapture(["-m", "asteria_runtime", "studio", "--root", workspace, "--json"]),
);
if (!preview.studio_dir) throw new Error("studio preview failed");
note("A5", `studio preview ${preview.ui_url}`);

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
  { cwd: studioDir, stdio: ["ignore", "pipe", "pipe"] },
);
let boot = "";
server.stdout.on("data", (c) => {
  boot += c;
});
server.stderr.on("data", (c) => {
  boot += c;
});
try {
  await waitFor(() => boot.includes("Asteria Studio listening"), 20000, "studio API failed");

  const base = `http://127.0.0.1:${port}`;
  const { session } = await postJson(`${base}/api/studio/sessions`, {});
  const submit = await postJson(`${base}/api/studio/sessions/${session.session_id}/messages`, {
    message: goalText,
    mode: "run",
    permission: "ask",
  });
  if (!submit.needs_permission) throw new Error("expected Studio permission card (B3)");
  await patchJson(
    `${base}/api/studio/sessions/${session.session_id}/jobs/${submit.job_id}/permission`,
    { action: "allow" },
  );
  note("B3", "Studio permission_request → Allow");
  note("B1", "Studio run job started (wait for ready_for_accept)");

  await waitForReadyOrAssist(base, session.session_id);

  const { events } = await getJson(`${base}/api/studio/sessions/${session.session_id}/events`);
  const types = new Set(events.map((e) => e.type));
  if (!types.has("permission_request")) throw new Error("missing permission_request");
  note("B2", `session events: ${[...types].slice(0, 12).join(", ")}`);

  const diagnostics = await getJson(`${base}/api/diagnostics`);
  note(
    "B4",
    `workflow=${JSON.stringify(diagnostics.workflow)} friction=${JSON.stringify(friction)}`,
  );
} finally {
  server.kill("SIGTERM");
  await sleep(500);
}

await runPython(["-m", "asteria_runtime", "accept", "--root", workspace]);
const status = JSON.parse(
  await runPythonCapture(["-m", "asteria_runtime", "status", "--root", workspace, "--json"]),
);
if (status.current_phase !== "ACCEPTED") throw new Error(`accept failed: ${status.current_phase}`);
note("C2", "accept ok");

await verifyTaskCompletion(taskId);

let warm = null;
if (process.env.B6_WARM_CONTINUATION === "1" && taskId === "small_code_change") {
  warm = await runWarmContinuationGoal();
}

const totalMin = Math.round((Date.now() - startedAt) / 60000);
console.log(
  JSON.stringify(
    { ok: true, task_id: taskId, workspace, total_min: totalMin, log, friction, warm },
    null,
    2,
  ),
);

async function runWarmContinuationGoal() {
  const warmGoal =
    process.env.B6_WARM_GOAL_TEXT ||
    "再给 greet_cli 增加 --uppercase 参数，输出时将名字转为大写，并补一个 pytest。";
  const warmPort = port + 1;
  const warmStarted = Date.now();
  const warmServer = spawn(
    process.execPath,
    [
      "server.mjs",
      "--workspace",
      workspace,
      "--runtime-root",
      repoRoot,
      "--port",
      String(warmPort),
      "--python",
      python,
    ],
    { cwd: studioDir, stdio: ["ignore", "pipe", "pipe"] },
  );
  let warmBoot = "";
  warmServer.stdout.on("data", (c) => {
    warmBoot += c;
  });
  warmServer.stderr.on("data", (c) => {
    warmBoot += c;
  });
  try {
    await waitFor(
      () => warmBoot.includes("Asteria Studio listening"),
      20000,
      "warm studio API failed",
    );
    const base = `http://127.0.0.1:${warmPort}`;
    const { session } = await postJson(`${base}/api/studio/sessions`, {});
    const submit = await postJson(`${base}/api/studio/sessions/${session.session_id}/messages`, {
      message: warmGoal,
      mode: "run",
      permission: "allow",
    });
    if (!submit.started) throw new Error("warm continuation should start immediately with allow");
    if (submit.execution_route !== "warm_session") {
      throw new Error(`expected warm_session route, got ${submit.execution_route || "none"}`);
    }
    note("W1", "warm continuation job started (--continue-session expected)");
    await waitForReadyOrAssist(base, session.session_id);
    const { events } = await getJson(`${base}/api/studio/sessions/${session.session_id}/events`);
    const toolStart = events.find(
      (event) => event.type === "tool_start" && Array.isArray(event.command),
    );
    const command = toolStart?.command || [];
    if (!command.includes("--continue-session")) {
      throw new Error(`warm route missing --continue-session: ${JSON.stringify(command)}`);
    }
    const elapsed_s = Math.round((Date.now() - warmStarted) / 1000);
    note("W2", `warm continuation finished in ~${elapsed_s}s`);
    return { ok: true, elapsed_s, route: submit.execution_route, goal: warmGoal };
  } finally {
    warmServer.kill("SIGTERM");
    await sleep(500);
  }
}

async function verifyTaskCompletion(activeTaskId) {
  if (activeTaskId === "static_landing_page") {
    const indexPath = path.join(workspace, "index.html");
    if (!existsSync(indexPath)) throw new Error("index.html not found");
    const html = readFileSync(indexPath, "utf8");
    if (!/<html/i.test(html) || html.trim().length < 80) {
      throw new Error(`index.html invalid (${html.trim().length} bytes)`);
    }
    note("C3", `index.html ok (${html.trim().length} bytes)`);
    return;
  }

  const versionOut = await runPythonCapture([path.join(workspace, "greet_cli.py"), "--version"]);
  const versionTrimmed = versionOut.trim();
  if (!versionTrimmed || !/(greet_cli|\d+\.\d+)/i.test(versionTrimmed)) {
    throw new Error(`--version failed: ${versionOut}`);
  }
  const testPath = resolveGreetTestPath(workspace);
  if (!testPath) throw new Error("greet_cli test file not found");
  const pytest = await runPythonCapture(["-m", "pytest", testPath, "-q"], workspace);
  if (!/passed/i.test(pytest)) throw new Error(`pytest: ${pytest}`);
  note("C3", pytest.trim());
}

function resolveGreetTestPath(root) {
  for (const rel of [
    "test_greet_cli.py",
    "tests/test_greet_cli.py",
    "greet_cli_test.py",
    "tests/greet_cli_test.py",
  ]) {
    const candidate = path.join(root, rel);
    if (existsSync(candidate)) return candidate;
  }
  return null;
}

function isReady(status) {
  return Boolean(
    status.can_accept ||
    status.workflow_state === "ready_for_accept" ||
    status.recommended_next_command === "accept" ||
    String(status.recommended_next_command || "").includes("accept"),
  );
}

async function waitForReadyOrAssist(base, sessionId) {
  let lastSig = "";
  let stagnant = 0;
  let actionCooldown = 0;
  let awaitJobs = false;
  let inProgressIdlePolls = 0;

  await waitFor(
    async () => {
      if (awaitJobs) {
        await waitForSessionJobsIdle(base, sessionId);
        awaitJobs = false;
      }

      if (actionCooldown > 0) {
        actionCooldown -= 1;
        return false;
      }

      const status = await getStatusJson();
      if (isReady(status)) return true;

      const rec = normalizeCommand(status.recommended_next_command);
      const sig = `${status.workflow_state}|${rec}|${status.pending_decision_count}|${status.can_accept}`;

      if (Number(status.pending_decision_count) > 0 || rec.startsWith("decide")) {
        const advanced = await resolvePendingDecisions(base, sessionId, status);
        if (advanced) {
          friction.decide += 1;
          actionCooldown = 12;
          awaitJobs = true;
          stagnant = 0;
          lastSig = "";
          inProgressIdlePolls = 0;
          return false;
        }
        if (
          Number(status.pending_decision_count) > 0 &&
          rec.startsWith("decide") &&
          stagnant >= 8
        ) {
          throw new Error(`pending decisions unresolved: ${sig}`);
        }
      }

      const action = resolveRuntimeAction(rec);
      if (action) {
        if (action === "model-check") {
          const tierMatch = rec.match(/--tier\s+(\w+)/i);
          const tier = tierMatch?.[1] || "medium";
          const check = JSON.parse(
            await runPythonCapture([
              "-m",
              "asteria_runtime",
              "model-check",
              "--root",
              workspace,
              "--tier",
              tier,
              "--json",
            ]),
          );
          if (!check.call_ok) throw new Error(`model-check ${tier} failed during assist loop`);
          note("B1m", `model-check ${tier} ok`);
          actionCooldown = 4;
          stagnant = 0;
          lastSig = "";
          inProgressIdlePolls = 0;
          return false;
        }
        if (action === "debug") {
          friction.debug += 1;
          if (friction.debug > 4) {
            throw new Error(`too many debug cycles (${friction.debug}) at ${sig}`);
          }
        }
        if (action === "resume") friction.resume += 1;
        await triggerRuntimeAction(base, sessionId, action);
        note("B1x", `Studio runtime action: ${action}`);
        actionCooldown = action === "debug" ? 8 : 6;
        awaitJobs = true;
        stagnant = 0;
        lastSig = "";
        inProgressIdlePolls = 0;
        return false;
      }

      const stillRunning = /in_progress|running|execute/i.test(
        `${status.workflow_state || ""} ${status.current_phase || ""}`,
      );
      if (!rec && stillRunning) {
        const runningJobs = await sessionJobsRunning(base, sessionId);
        if (!runningJobs) {
          inProgressIdlePolls += 1;
          if (inProgressIdlePolls >= 15) {
            friction.resume += 1;
            await triggerRuntimeAction(base, sessionId, "resume");
            note("B1x", "nudge resume (in_progress idle, no studio jobs)");
            actionCooldown = 6;
            awaitJobs = true;
            inProgressIdlePolls = 0;
          }
        } else {
          inProgressIdlePolls = 0;
        }
        stagnant = 0;
        lastSig = sig;
        return false;
      }

      inProgressIdlePolls = 0;
      if (sig === lastSig) stagnant += 1;
      else {
        stagnant = 0;
        lastSig = sig;
      }
      if (stagnant >= 25) {
        throw new Error(`stagnant workflow at ${sig}`);
      }
      return false;
    },
    900000,
    "Studio run did not reach ready_for_accept",
  );
}

async function waitForSessionJobsIdle(base, sessionId) {
  await waitFor(
    async () => {
      const status = await getStatusJson();
      if (isReady(status)) return true;
      const jobsRunning = await sessionJobsRunning(base, sessionId);
      if (!jobsRunning) return true;
      // Long goal runs legitimately keep a job "running" — don't block the assist loop forever.
      const stillActive = /in_progress|running|execute/i.test(
        `${status.workflow_state || ""} ${status.current_phase || ""}`,
      );
      if (stillActive) return false;
      return true;
    },
    540000,
    "Studio jobs did not finish",
  );
}

async function sessionJobsRunning(base, sessionId) {
  const payload = await getJson(`${base}/api/studio/sessions/${sessionId}/jobs`);
  return Number(payload.running || 0) > 0;
}

function normalizeCommand(raw) {
  return String(raw || "")
    .replace(/^asteria\s+/, "")
    .trim();
}

function resolveRuntimeAction(rec) {
  const normalized = normalizeCommand(rec).toLowerCase();
  if (!normalized || normalized.startsWith("accept")) return null;
  if (normalized.startsWith("decide")) return null;
  if (normalized.startsWith("model-check")) return "model-check";
  if (normalized.includes("debug")) return "debug";
  if (
    normalized.startsWith("resume") ||
    normalized.startsWith("continue") ||
    normalized.startsWith("run")
  )
    return "resume";
  if (normalized.startsWith("replan")) return "resume";
  if (normalized.startsWith("review")) return "review";
  return null;
}

async function resolvePendingDecisions(base, sessionId, status) {
  const runId = String(status.current_session_id || "").trim();
  if (!runId) return false;

  const pending = readPendingDecisions(runId);
  if (!pending.length) return false;

  for (const decision of pending) {
    const optionId = pickDecisionOption(decision);
    note("B1d", `resolve ${decision.decision_id} → ${optionId}`);
    const result = await postJson(`${base}/api/studio/sessions/${sessionId}/decisions/resolve`, {
      run_id: runId,
      decision_id: decision.decision_id,
      option_id: optionId,
    });
    if (!result.ok) throw new Error(`decision resolve failed: ${JSON.stringify(result)}`);
  }
  return true;
}

function readPendingDecisions(runId) {
  const file = path.join(workspace, ".asteria", "runs", runId, "decisions.jsonl");
  if (!existsSync(file)) return [];
  const byId = new Map();
  for (const line of readFileSync(file, "utf8").split(/\r?\n/)) {
    if (!line.trim()) continue;
    const item = JSON.parse(line);
    if (item?.decision_id) byId.set(item.decision_id, item);
  }
  return [...byId.values()].filter((item) => item.status === "pending");
}

function pickDecisionOption(decision) {
  const metadata = decision?.metadata || {};
  const requestTypes = metadata.request_types || [];
  const kind = String(metadata.kind || "");
  if (kind === "execution_policy_approval") {
    const options = Array.isArray(decision.options) ? decision.options : [];
    if (options.some((option) => option.option_id === "approve_once")) {
      return "approve_once";
    }
    if (options.some((option) => option.option_id === "approve_similar_for_session")) {
      return "approve_similar_for_session";
    }
  }
  if (kind === "runtime_request" || requestTypes.length > 0) {
    return "review_contract";
  }
  if (kind === "replan_decision" || metadata.reason === "repair_limit") {
    const options = Array.isArray(decision.options) ? decision.options : [];
    if (options.some((option) => option.option_id === "create_repair_task")) {
      return "create_repair_task";
    }
  }
  const options = Array.isArray(decision.options) ? decision.options : [];
  if (options.some((option) => option.option_id === "review_contract")) {
    return "review_contract";
  }
  return decision.recommended_option_id || decision.default_option_id || options[0]?.option_id;
}

async function triggerRuntimeAction(base, sessionId, action) {
  const body = { next_action: action, permission: "allow" };
  const result = await postJson(`${base}/api/studio/sessions/${sessionId}/runtime-actions`, body);
  if (result.needs_permission && result.job_id) {
    await patchJson(`${base}/api/studio/sessions/${sessionId}/jobs/${result.job_id}/permission`, {
      action: "allow",
    });
    return;
  }
  if (!result.ok && !result.started) {
    throw new Error(`runtime action ${action} failed: ${JSON.stringify(result)}`);
  }
}

async function getStatusJson() {
  return JSON.parse(
    await runPythonCapture(["-m", "asteria_runtime", "status", "--root", workspace, "--json"]),
  );
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

async function waitFor(predicate, timeoutMs, message) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    if (await predicate()) return;
    await sleep(3000);
  }
  throw new Error(message);
}

async function getJson(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`GET ${url} ${res.status}`);
  return res.json();
}

async function postJson(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`POST ${url} ${res.status}: ${await res.text()}`);
  return res.json();
}

async function patchJson(url, body) {
  const res = await fetch(url, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`PATCH ${url} ${res.status}: ${await res.text()}`);
  return res.json();
}

function runPython(args, cwd = repoRoot) {
  return new Promise((resolve, reject) => {
    const child = spawn(python, args, {
      cwd,
      stdio: "inherit",
      env: { ...process.env, PYTHONPATH: path.join(repoRoot, "src") },
    });
    child.on("error", reject);
    child.on("exit", (code) => (code === 0 ? resolve() : reject(new Error(`exit ${code}`))));
  });
}

function runPythonCapture(args, cwd = repoRoot) {
  return new Promise((resolve, reject) => {
    const child = spawn(python, args, {
      cwd,
      env: { ...process.env, PYTHONPATH: path.join(repoRoot, "src") },
    });
    let out = "";
    child.stdout?.on("data", (c) => {
      out += c;
    });
    child.stderr?.on("data", (c) => {
      out += c;
    });
    child.on("error", reject);
    child.on("exit", (code) =>
      code === 0 ? resolve(out) : reject(new Error(out || `exit ${code}`)),
    );
  });
}
