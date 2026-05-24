import { spawn } from "node:child_process";
import { promises as fs } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const studioDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const workspace = await fs.mkdtemp(path.join(os.tmpdir(), "asteria-studio-friendly-ssl-"));
const port = Number(process.env.ASTERIA_STUDIO_FRIENDLY_SSL_PORT || 18796);
const sslError = "<urlopen error _ssl.c:1015: The handshake operation timed out>";

const server = spawn(process.execPath, ["server.mjs", "--workspace", workspace, "--port", String(port)], {
  cwd: studioDir,
  stdio: ["ignore", "pipe", "pipe"],
  env: {
    ...process.env,
    ASTERIA_STUDIO_CHAT_BACKEND: "model",
    ASTERIA_STUDIO_FAKE_CHAT_ERROR: sslError,
  },
});

let stdout = "";
let stderr = "";
server.stdout.on("data", (chunk) => { stdout += String(chunk); });
server.stderr.on("data", (chunk) => { stderr += String(chunk); });

try {
  await waitForHealth();
  const session = await postJson("/api/studio/sessions", {});
  const sessionId = session.session.session_id;

  await postJson(`/api/studio/sessions/${encodeURIComponent(sessionId)}/messages`, {
    mode: "auto",
    permission: "ask",
    message: "??",
  });

  const { events } = await fetchEventsUntil(sessionId, (items) =>
    items.some((event) => event.type === "error" && event.phase === "chat")
  );
  const errorEvent = events.find((event) => event.type === "error" && event.phase === "chat");
  const text = String(errorEvent?.content_delta || "");
  assert(text.includes("Connection timed out"), "SSL handshake timeout should be translated into a friendly connection timeout message");
  assert(text.includes("HTTPS") && text.includes("Retry"), "friendly message should explain likely cause and next action");
  assert(!text.includes("_ssl.c:1015") && !text.includes("urlopen error"), "raw SSL implementation details should not be shown in the main user message");

  console.log("Studio friendly SSL error smoke passed");
} finally {
  server.kill("SIGTERM");
  await new Promise((resolve) => setTimeout(resolve, 200));
  await fs.rm(workspace, { recursive: true, force: true });
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
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
  throw new Error(`Studio server did not become healthy. stdout=${stdout} stderr=${stderr} last=${lastError}`);
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
  if (!response.ok) throw new Error(`${route} returned ${response.status}: ${await response.text()}`);
  return response.json();
}

async function fetchEventsUntil(sessionId, predicate) {
  const route = `/api/studio/sessions/${encodeURIComponent(sessionId)}/events`;
  const deadline = Date.now() + 10_000;
  let latest = { events: [] };
  while (Date.now() < deadline) {
    latest = await fetchJson(route);
    if (predicate(latest.events || [])) return latest;
    if (server.exitCode !== null) throw new Error(`Studio server exited early. stdout=${stdout} stderr=${stderr}`);
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(`Timed out waiting for friendly error. events=${(latest.events || []).length} stdout=${stdout} stderr=${stderr}`);
}
