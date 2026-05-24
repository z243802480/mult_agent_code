import { spawn } from "node:child_process";
import { promises as fs } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const studioDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const workspace = await fs.mkdtemp(path.join(os.tmpdir(), "asteria-studio-chat-fallback-"));
const port = Number(process.env.ASTERIA_STUDIO_CHAT_FALLBACK_PORT || 18790);

const server = spawn(process.execPath, ["server.mjs", "--workspace", workspace, "--port", String(port)], {
  cwd: studioDir,
  stdio: ["ignore", "pipe", "pipe"],
  env: { ...process.env, ASTERIA_STUDIO_CHAT_BACKEND: "local" },
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
    message: "Plan a 3-day Qingdao travel itinerary",
  });

  const { events } = await fetchEventsUntil(sessionId, (items) =>
    items.some((event) => event.type === "final_answer" && event.phase === "chat")
  );
  const finalAnswer = events.find((event) => event.type === "final_answer" && event.phase === "chat");
  const answerText = String(finalAnswer?.content_delta || "");

  assert(/Goal understanding|Recommended plan|Suggested sequence|Quick answer|I could not reach/i.test(answerText), "fallback should be user-facing, natural, and useful");
  assert(!/Temporary local fallback|Request type:|intent|route|model route|run was started|files were changed/i.test(answerText), "fallback should not expose backend metadata");
  assert(!/Zhanqiao|Laoshan|May Fourth|Beer Museum|shadowing/i.test(answerText), "fallback should not contain domain-specific template content");
  assert(!/Context refs:|Current session:|Next actions:|Evidence Explorer|Inspector|run-[0-9]/i.test(answerText), "fallback should not expose CLI/runtime context noise");

  console.log("Studio chat fallback smoke passed");
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
  throw new Error(`Timed out waiting for fallback answer. events=${(latest.events || []).length} stdout=${stdout} stderr=${stderr}`);
}
