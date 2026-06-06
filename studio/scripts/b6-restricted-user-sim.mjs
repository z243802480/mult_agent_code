/**
 * B6 restricted user simulation — fresh workspace, user-doc commands only.
 * Studio: A5 launch + B3 permission card. Goal/accept: CLI per Beta用户入门.
 */
import { spawn } from "node:child_process";
import { copyFileSync, existsSync, rmSync } from "node:fs";
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

server.kill("SIGTERM");
await sleep(1000);

note("B1", "CLI goal (user-doc path; Studio run capped at 2 iterations in server.mjs)");
await runPython([
  "-m", "asteria_runtime", "goal", goalText,
  "--root", workspace, "--permission-level", "balanced", "--no-research", "--max-iterations", "8",
]);

await waitFor(async () => {
  const status = JSON.parse(await runPythonCapture(["-m", "asteria_runtime", "status", "--root", workspace, "--json"]));
  return status.can_accept || status.workflow_state === "ready_for_accept" || status.recommended_next_command === "accept";
}, 600000, "goal did not reach ready_for_accept");

note("B4", "status ready_for_accept");

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

function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }

async function waitFor(predicate, timeoutMs, message) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    if (await predicate()) return;
    await sleep(3000);
  }
  throw new Error(message);
}

async function postJson(url, body) {
  const res = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!res.ok) throw new Error(`POST ${url} ${res.status}`);
  return res.json();
}

async function patchJson(url, body) {
  const res = await fetch(url, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!res.ok) throw new Error(`PATCH ${url} ${res.status}`);
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
