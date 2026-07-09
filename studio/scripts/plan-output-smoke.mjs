import { spawn } from "node:child_process";
import { promises as fs } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const studioDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const workspace = await fs.mkdtemp(path.join(os.tmpdir(), "asteria-studio-plan-output-"));
const port = Number(process.env.ASTERIA_STUDIO_PLAN_OUTPUT_PORT || 18794);

const server = spawn(
  process.execPath,
  ["server.mjs", "--workspace", workspace, "--port", String(port)],
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
  const session = await postJson("/api/studio/sessions", {});
  const sessionId = session.session.session_id;

  await postJson(`/api/studio/sessions/${encodeURIComponent(sessionId)}/messages`, {
    mode: "plan",
    permission: "ask",
    message: "Plan a 3-day Qingdao travel itinerary",
  });

  const { events } = await fetchEventsUntil(sessionId, (items) =>
    items.some((event) => event.type === "final_answer" && event.phase === "chat"),
  );
  const finalAnswer = events.find(
    (event) => event.type === "final_answer" && event.phase === "chat",
  );
  const answerText = String(finalAnswer?.content_delta || "");

  assert(
    /Goal understanding|Recommended plan|Suggested sequence|Next action/i.test(answerText),
    "plan-like chat answer should be a useful plan, not a fallback wrapper",
  );
  assert(
    /Qingdao|travel|itinerary/i.test(answerText),
    "plan should reflect the user's requested outcome",
  );
  assert(
    !/Temporary local fallback|Request type:|intent|route|model route|run was started|files were changed|permission_effect/i.test(
      answerText,
    ),
    "plan should not expose backend metadata",
  );
  assert(
    !/Context refs:|Current session:|Next actions:|Evidence Explorer|Inspector|run-[0-9]|stdout|stderr|\.asteria|command/i.test(
      answerText,
    ),
    "plan should not expose runtime context noise",
  );

  const entries = await fs.readdir(workspace, { withFileTypes: true });
  const businessEntries = entries
    .filter((entry) => !entry.name.startsWith("."))
    .map((entry) => entry.name);
  assert(
    businessEntries.length === 0,
    `content planning should not create business files, got ${businessEntries.join(", ")}`,
  );

  console.log("Studio plan output smoke passed");
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
    `Timed out waiting for plan answer. events=${(latest.events || []).length} stdout=${stdout} stderr=${stderr}`,
  );
}
