/**
 * Smoke: runtime-actions must work when session.json lost session_id (regression S59).
 */
import { mkdtempSync, mkdirSync, writeFileSync } from "node:fs";
import { spawn } from "node:child_process";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const studioDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = path.resolve(studioDir, "..");
const workspace = mkdtempSync(path.join(os.tmpdir(), "asteria-session-id-smoke-"));
mkdirSync(path.join(workspace, ".asteria"), { recursive: true });
const port = 18900 + Math.floor(Math.random() * 200);
const sessionId = "session-smoke-regression";
const sessionDir = path.join(workspace, ".asteria", "studio", "sessions", sessionId);
mkdirSync(sessionDir, { recursive: true });
writeFileSync(
  path.join(sessionDir, "session.json"),
  JSON.stringify({ updated_at: new Date().toISOString() }, null, 2),
);

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
    "python",
  ],
  { cwd: studioDir, stdio: ["ignore", "pipe", "pipe"] },
);

try {
  await waitForListen(server, 15000);
  const base = `http://127.0.0.1:${port}`;
  const res = await fetch(`${base}/api/studio/sessions/${sessionId}/runtime-actions`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ next_action: "debug", permission: "allow" }),
  });
  const body = await res.json();
  if (res.status !== 200 || !body.ok || body.action !== "debug") {
    throw new Error(`runtime-actions failed: ${res.status} ${JSON.stringify(body)}`);
  }
  console.log(
    JSON.stringify({ ok: true, summary: "session-id smoke passed", sessionId, workspace }, null, 2),
  );
} finally {
  server.kill("SIGTERM");
}

function waitForListen(child, timeoutMs) {
  let boot = "";
  child.stdout.on("data", (chunk) => {
    boot += chunk;
  });
  child.stderr.on("data", (chunk) => {
    boot += chunk;
  });
  return new Promise((resolve, reject) => {
    const start = Date.now();
    const timer = setInterval(() => {
      if (boot.includes("Asteria Studio listening")) {
        clearInterval(timer);
        resolve();
      } else if (Date.now() - start > timeoutMs) {
        clearInterval(timer);
        reject(new Error(`studio failed to start: ${boot}`));
      }
    }, 200);
  });
}
