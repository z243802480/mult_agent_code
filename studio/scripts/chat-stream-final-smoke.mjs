import { spawn } from "node:child_process";
import { promises as fs } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const studioDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const workspace = await fs.mkdtemp(path.join(os.tmpdir(), "asteria-studio-chat-stream-final-"));
const port = Number(process.env.ASTERIA_STUDIO_CHAT_STREAM_FINAL_PORT || 18795);
const fakePackageDir = path.join(workspace, "asteria_runtime", "commands");
await fs.mkdir(fakePackageDir, { recursive: true });
await fs.writeFile(path.join(workspace, "asteria_runtime", "__init__.py"), "", "utf8");
await fs.writeFile(path.join(fakePackageDir, "__init__.py"), "", "utf8");
await fs.writeFile(
  path.join(fakePackageDir, "chat_command.py"),
  String.raw`
import json
import os
from pathlib import Path

class ChatResult:
    def to_dict(self):
        return {"schema_version":"0.1.0","answer":"## Wrong fallback\nThis non-stream answer must not replace streamed content."}

class ChatCommand:
    # Mirrors the real signature. The BFF passes every argument by keyword, so a double that omits
    # one raises TypeError, the process exits non-zero, and the answer silently falls back — which
    # is exactly how this smoke caught the attachments argument being added upstream.
    def __init__(self, root, question, history=None, attachments=None):
        self.root = root
        self.question = question
        self.history = history
        self.attachments = attachments

    def run(self):
        sink = os.environ.get("ASTERIA_STUDIO_EVENT_SINK")
        session = os.environ.get("ASTERIA_STUDIO_SESSION_ID", "session")
        if sink:
            path = Path(sink)
            path.parent.mkdir(parents=True, exist_ok=True)
            events = [
                {"event_id":"evt-model-test-start","session_id":session,"type":"model_start","status":"running","title":"Chat response started","summary":"fake","content_delta":"","phase":"chat","display_level":"main","model_provider":"fake","model_name":"stream"},
                {"event_id":"evt-model-test-delta-1","session_id":session,"type":"model_delta","status":"running","title":"Chat response update","summary":"fake","content_delta":"<think>internal reasoning should not appear</think>","phase":"chat","display_level":"main","parent_event_id":"evt-model-test-start","model_provider":"fake","model_name":"stream"},
                {"event_id":"evt-model-test-delta-2","session_id":session,"type":"model_delta","status":"running","title":"Chat response update","summary":"fake","content_delta":"\n\n# \u9752\u5c9b\u771f\u5b9e\u65b9\u6848\n\n\u8fd9\u662f\u6d41\u5f0f\u8fd4\u56de\u91cc\u7684\u4e2d\u6587\u771f\u5b9e\u7528\u6237\u7b54\u6848\uff0c\u5305\u542b\u6808\u6865\u3001\u516b\u5927\u5173\u548c\u5d02\u5c71\u3002","phase":"chat","display_level":"main","parent_event_id":"evt-model-test-start","model_provider":"fake","model_name":"stream"},
                {"event_id":"evt-model-test-end","session_id":session,"type":"model_end","status":"completed","title":"Chat response completed","summary":"fake","content_delta":"","phase":"chat","display_level":"main","parent_event_id":"evt-model-test-start","model_provider":"fake","model_name":"stream"},
            ]
            with path.open("a", encoding="utf-8") as f:
                for event in events:
                    f.write(json.dumps(event, ensure_ascii=False) + "\n")
        return ChatResult()
`,
  "utf8",
);

const server = spawn(
  process.execPath,
  ["server.mjs", "--workspace", workspace, "--port", String(port), "--python", "python"],
  {
    cwd: studioDir,
    stdio: ["ignore", "pipe", "pipe"],
    env: { ...process.env, ASTERIA_STUDIO_CHAT_BACKEND: "model", PYTHONPATH: workspace },
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
    mode: "auto",
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
    answerText.includes("\u9752\u5c9b\u771f\u5b9e\u65b9\u6848") &&
      answerText.includes("\u6808\u6865") &&
      answerText.includes("\u516b\u5927\u5173"),
    "final answer should reuse the visible streamed Chinese model answer without mojibake",
  );
  assert(
    !/Wrong fallback|non-stream answer|internal reasoning|<think>/i.test(answerText),
    "final answer should not replace stream with fallback or expose thinking tags",
  );

  console.log("Studio chat stream final smoke passed");
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
    `Timed out waiting for final answer. events=${(latest.events || []).length} stdout=${stdout} stderr=${stderr}`,
  );
}
