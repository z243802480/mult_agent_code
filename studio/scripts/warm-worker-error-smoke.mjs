// A warm worker failure must reach the main thread and Inspector with its real reason.
import assert from "node:assert/strict";
import { spawn, spawnSync } from "node:child_process";
import { mkdtemp, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { friendlyErrorCategory, friendlyErrorText } from "../lib/friendly-error.mjs";

const missingFile = "FileNotFoundError: [Errno 2] No such file or directory: 'policies.json'";
assert.equal(friendlyErrorCategory(missingFile), "unknown");
assert.match(friendlyErrorText(missingFile), /FileNotFoundError/);
assert.equal(friendlyErrorCategory("getaddrinfo ENOTFOUND example.invalid"), "network");

const studioDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = path.resolve(studioDir, "..");
const workspace = await mkdtemp(path.join(os.tmpdir(), "asteria-warm-error-smoke-"));
const port = Number(process.env.ASTERIA_WARM_ERROR_SMOKE_PORT || 18923);
const python = process.env.ASTERIA_PYTHON || "python";
const env = {
  ...process.env,
  PYTHONPATH: [path.join(repoRoot, "src"), process.env.PYTHONPATH]
    .filter(Boolean)
    .join(path.delimiter),
  AGENT_MODEL_PROVIDER: "s93-invalid-provider",
  ASTERIA_STUDIO_WARM_WORKER: "1",
};
const initialized = spawnSync(python, ["-m", "asteria_runtime", "init", "--root", workspace], {
  cwd: repoRoot,
  env,
  encoding: "utf8",
  windowsHide: true,
});
assert.equal(initialized.status, 0, initialized.stderr || initialized.stdout);

const server = spawn(
  process.execPath,
  ["server.mjs", "--workspace", workspace, "--port", String(port)],
  {
    cwd: studioDir,
    env,
    stdio: ["ignore", "pipe", "pipe"],
    windowsHide: true,
  },
);
let output = "";
server.stdout.on("data", (chunk) => (output += String(chunk)));
server.stderr.on("data", (chunk) => (output += String(chunk)));

try {
  await until(async () => (await getJson("/api/health")).ok);
  // The worker's import graph must finish before submission; otherwise the cold fallback would
  // test a different error path. Its ready signal is private to the BFF, so allow prewarming here.
  await new Promise((resolve) => setTimeout(resolve, 3000));
  const sessionId = (await postJson("/api/studio/sessions", {})).session.session_id;
  await postJson(`/api/studio/sessions/${sessionId}/messages`, {
    mode: "run",
    permission: "allow",
    message: "Add --version to this small CLI.",
  });
  const events = await until(async () => {
    const payload = await getJson(`/api/studio/sessions/${sessionId}/events`);
    return payload.events.some((event) => event.type === "error") ? payload.events : null;
  });
  const error = events.find((event) => event.type === "error");
  const inspector = events.find((event) => event.type === "tool_end" && event.status === "failed");
  assert.match(String(error?.content_delta), /Unsupported model provider: s93-invalid-provider/);
  assert.match(
    String(inspector?.content_delta),
    /Unsupported model provider: s93-invalid-provider/,
  );
  console.log("Warm worker error smoke passed");
} finally {
  server.kill("SIGTERM");
  await new Promise((resolve) => setTimeout(resolve, 200));
  await rm(workspace, { recursive: true, force: true, maxRetries: 10, retryDelay: 250 });
}

async function getJson(route) {
  const response = await fetch(`http://127.0.0.1:${port}${route}`);
  if (!response.ok) throw new Error(`${route}: HTTP ${response.status}`);
  return response.json();
}

async function postJson(route, body) {
  const response = await fetch(`http://127.0.0.1:${port}${route}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error(`${route}: HTTP ${response.status}`);
  return response.json();
}

async function until(probe) {
  const deadline = Date.now() + 20_000;
  while (Date.now() < deadline) {
    try {
      const result = await probe();
      if (result) return result;
    } catch {
      // The server may not be listening yet.
    }
    if (server.exitCode !== null) throw new Error(`Studio exited early: ${output}`);
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(`Timed out waiting for Studio evidence: ${output}`);
}
