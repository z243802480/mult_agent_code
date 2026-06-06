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
const port = Number(process.env.B6_SIM_PORT || 8794);
const python = process.env.ASTERIA_PYTHON || "python";
const goalText = "给一个小 CLI 增加 --version 参数，并补一个测试。";
const startedAt = Date.now();
const log = [];

function note(step, detail) {
  const entry = { step, detail, elapsed_s: Math.round((Date.now() - startedAt) / 1000) };
  log.push(entry);
  console.log(`[${entry.elapsed_s}s] ${step}: ${detail}`);
}

if (existsSync(workspace)) {
  rmSync(workspace, { recursive: true, force: true });
}

await runPython(["-m", "asteria_runtime", "init", "--root", workspace, "--north-star-title", "Beta sim"]);
note("A4", "init fresh workspace");

copyFileSync(
  path.join(repoRoot, "benchmarks/fixtures/s13_clean_run/greet_cli.py"),
  path.join(workspace, "greet_cli.py"),
);
note("A4b", "starter greet_cli.py (maintainer-provided)");

for (const tier of ["strong", "medium"]) {
  const check = JSON.parse(await runPythonCapture(["-m", "asteria_runtime", "model-check", "--root", workspace, "--tier", tier, "--json"]));
  if (!check.call_ok) throw new Error(`model-check ${tier} failed`);
}
note("A3", "model routes ok");

const preview = JSON.parse(await runPythonCapture(["-m", "asteria_runtime", "studio", "--root", workspace, "--json"]));
if (!preview.studio_dir) throw new Error("studio preview failed");
note("A5", `studio preview ${preview.ui_url}`);

const server = spawn(process.execPath, [
  "server.mjs", "--workspace", workspace, "--runtime-root", repoRoot, "--port", String(port), "--python", python,
], { cwd: studioDir, stdio: ["ignore", "pipe", "pipe"] });
let boot = "";
server.stdout.on("data", (c) => { boot += c; });
server.stderr.on("data", (c) => { boot += c; });
await waitFor(() => boot.includes("Asteria Studio listening"), 20000, "studio API failed");

const base = `http://127.0.0.1:${port}`;
const { session } = await postJson(`${base}/api/studio/sessions`, {});
const submit = await postJson(`${base}/api/studio/sessions/${session.session_id}/messages`, {
  message: goalText, mode: "run", permission: "ask",
});
if (!submit.needs_permission) throw new Error("expected Studio permission card (B3)");
await patchJson(`${base}/api/studio/sessions/${session.session_id}/jobs/${submit.job_id}/permission`, { action: "allow" });
note("B3", "Studio permission_request → Allow");
note("B1", "Studio run job started (wait for ready_for_accept)");

await waitForReadyOrAssist(base, session.session_id);

const { events } = await getJson(`${base}/api/studio/sessions/${session.session_id}/events`);
const types = new Set(events.map((e) => e.type));
if (!types.has("permission_request")) throw new Error("missing permission_request");
note("B2", `session events: ${[...types].slice(0, 12).join(", ")}`);

const diagnostics = await getJson(`${base}/api/diagnostics`);
note("B4", `workflow=${JSON.stringify(diagnostics.workflow)}`);

server.kill("SIGTERM");
await sleep(500);

await runPython(["-m", "asteria_runtime", "accept", "--root", workspace]);
const status = JSON.parse(await runPythonCapture(["-m", "asteria_runtime", "status", "--root", workspace, "--json"]));
if (status.current_phase !== "ACCEPTED") throw new Error(`accept failed: ${status.current_phase}`);
note("C2", "accept ok");

const versionOut = await runPythonCapture([path.join(workspace, "greet_cli.py"), "--version"]);
if (!/greet_cli/i.test(versionOut)) throw new Error(`--version failed: ${versionOut}`);
const pytest = await runPythonCapture(["-m", "pytest", path.join(workspace, "test_greet_cli.py"), "-q"], workspace);
if (!/passed/i.test(pytest)) throw new Error(`pytest: ${pytest}`);
note("C3", pytest.trim());

const totalMin = Math.round((Date.now() - startedAt) / 60000);
console.log(JSON.stringify({ ok: true, workspace, total_min: totalMin, log }, null, 2));

function isReady(status) {
  return Boolean(
    status.can_accept
    || status.workflow_state === "ready_for_accept"
    || status.recommended_next_command === "accept"
    || String(status.recommended_next_command || "").includes("accept"),
  );
}

async function waitForReadyOrAssist(base, sessionId) {
  let lastSig = "";
  let stagnant = 0;
  let actionCooldown = 0;

  await waitFor(async () => {
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
        actionCooldown = 3;
        stagnant = 0;
        lastSig = "";
        return false;
      }
    }

    if (/^(resume|replan|debug|review)/.test(rec)) {
      const action = rec.split(/\s+/)[0];
      await triggerRuntimeAction(base, sessionId, action);
      note("B1x", `Studio runtime action: ${action}`);
      actionCooldown = 5;
      stagnant = 0;
      lastSig = "";
      return false;
    }

    if (sig === lastSig) stagnant += 1;
    else {
      stagnant = 0;
      lastSig = sig;
    }
    if (stagnant >= 25) {
      throw new Error(`stagnant workflow at ${sig}`);
    }
    return false;
  }, 600000, "Studio run did not reach ready_for_accept");
}

function normalizeCommand(raw) {
  return String(raw || "").replace(/^asteria\s+/, "").trim();
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
  if (metadata.kind === "runtime_request" || requestTypes.length > 0) {
    return "review_contract";
  }
  return decision.recommended_option_id || decision.default_option_id || decision.options?.[0]?.option_id;
}

async function triggerRuntimeAction(base, sessionId, action) {
  const body = { next_action: action, permission: "allow" };
  const result = await postJson(`${base}/api/studio/sessions/${sessionId}/runtime-actions`, body);
  if (result.needs_permission && result.job_id) {
    await patchJson(`${base}/api/studio/sessions/${sessionId}/jobs/${result.job_id}/permission`, { action: "allow" });
    return;
  }
  if (!result.ok && !result.started) {
    throw new Error(`runtime action ${action} failed: ${JSON.stringify(result)}`);
  }
}

async function getStatusJson() {
  return JSON.parse(await runPythonCapture(["-m", "asteria_runtime", "status", "--root", workspace, "--json"]));
}

function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }

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
  const res = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!res.ok) throw new Error(`POST ${url} ${res.status}: ${await res.text()}`);
  return res.json();
}

async function patchJson(url, body) {
  const res = await fetch(url, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!res.ok) throw new Error(`PATCH ${url} ${res.status}: ${await res.text()}`);
  return res.json();
}

function runPython(args, cwd = repoRoot) {
  return new Promise((resolve, reject) => {
    const child = spawn(python, args, { cwd, stdio: "inherit", env: { ...process.env, PYTHONPATH: path.join(repoRoot, "src") } });
    child.on("error", reject);
    child.on("exit", (code) => (code === 0 ? resolve() : reject(new Error(`exit ${code}`))));
  });
}

function runPythonCapture(args, cwd = repoRoot) {
  return new Promise((resolve, reject) => {
    const child = spawn(python, args, { cwd, env: { ...process.env, PYTHONPATH: path.join(repoRoot, "src") } });
    let out = "";
    child.stdout?.on("data", (c) => { out += c; });
    child.stderr?.on("data", (c) => { out += c; });
    child.on("error", reject);
    child.on("exit", (code) => (code === 0 ? resolve(out) : reject(new Error(out || `exit ${code}`))));
  });
}
