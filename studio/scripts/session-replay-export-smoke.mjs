/**
 * G15 会话回放导出 — the /export.html replay page must be:
 *   1. Self-contained: no external script/style/img references (a file forwarded on the intranet
 *      must render offline, and must not phone anywhere).
 *   2. Escaped: transcript content is DATA — a message containing `</script><script>` must not
 *      break out of the embedded JSON block or become live markup.
 *   3. Faithful: the user message and final answer are present; delta noise is not.
 */
import { spawn } from "node:child_process";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const studioDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = path.resolve(studioDir, "..");
const port = Number(process.env.ASTERIA_STUDIO_REPLAY_PORT || 18812);
const python = process.env.ASTERIA_PYTHON || "python";
const base = `http://127.0.0.1:${port}`;

const workspace = await fs.mkdtemp(path.join(os.tmpdir(), "asteria-replay-smoke-"));

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

function assert(cond, message) {
  if (!cond) throw new Error(message);
}

try {
  await waitForHealth();
  const created = await fetchJson(`${base}/api/studio/sessions`, "POST");
  const sid = created?.session?.session_id;
  assert(created.ok && sid, "session create failed");

  const eventsFile = path.join(workspace, ".asteria", "studio", "sessions", sid, "events.jsonl");
  const rows = [
    {
      event_id: "e1",
      session_id: sid,
      type: "user_message",
      status: "completed",
      title: "goal",
      summary: "写一个恶意消息测试",
      content_delta: '</script><script>alert("xss")</script> 把 a.py 改对',
      created_at: "2026-07-17T01:00:00Z",
    },
    {
      event_id: "e2",
      session_id: sid,
      type: "tool_start",
      status: "running",
      title: "写入 a.py",
      summary: "writing",
      command: ["python", "-m", "pytest"],
      created_at: "2026-07-17T01:00:05Z",
    },
    {
      event_id: "e3",
      session_id: sid,
      type: "model_delta",
      status: "running",
      title: "delta noise",
      summary: "",
      content_delta: "STREAM-DELTA-NOISE",
      created_at: "2026-07-17T01:00:06Z",
    },
    {
      event_id: "e4",
      session_id: sid,
      type: "final_answer",
      status: "completed",
      title: "done",
      summary: "",
      content_delta: "改完了，测试通过。",
      created_at: "2026-07-17T01:00:10Z",
    },
    {
      event_id: "e5",
      session_id: sid,
      type: "tool_end",
      status: "completed",
      title: "inspector only",
      summary: "hidden",
      display_level: "inspector",
      content_delta: "INSPECTOR-ONLY-LINE",
      created_at: "2026-07-17T01:00:11Z",
    },
  ];
  await fs.writeFile(eventsFile, rows.map((row) => JSON.stringify(row)).join("\n") + "\n", "utf8");

  const response = await fetch(`${base}/api/studio/sessions/${sid}/export.html`);
  assert(response.ok, `export.html returned ${response.status}`);
  assert(
    String(response.headers.get("content-type")).includes("text/html"),
    "must serve text/html",
  );
  const html = await response.text();

  // 1. Self-contained: no external references of any kind.
  assert(!/<script[^>]+src=/i.test(html), "replay page must not load external scripts");
  assert(!/<link[^>]+href=/i.test(html), "replay page must not load external styles");
  assert(!/<img|<iframe|@import|url\(/i.test(html), "replay page must not reference any asset");

  // 2. Escaping: the raw attack string must NOT appear; the JSON embed keeps it as <.
  assert(!html.includes('</script><script>alert("xss")</script>'), "transcript broke out of JSON");
  assert(html.includes("\\u003c/script"), "embedded JSON must escape < as \\u003c");

  // 3. Faithful main-thread replay: goal + final present, delta noise + inspector rows absent.
  assert(html.includes("把 a.py 改对"), "user message text missing");
  assert(html.includes("改完了，测试通过。"), "final answer text missing");
  assert(!html.includes("STREAM-DELTA-NOISE"), "stream deltas must not be embedded");
  assert(!html.includes("INSPECTOR-ONLY-LINE"), "inspector-level rows must not be embedded");
  assert(html.includes("完整原始证据在会话的 JSON 备份导出里"), "honest scope note missing");

  console.log("Studio session-replay export smoke passed (self-contained, escaped, faithful)");
} finally {
  server.kill("SIGTERM");
  await new Promise((resolve) => setTimeout(resolve, 200));
  await fs.rm(workspace, { recursive: true, force: true }).catch(() => {});
}

async function waitForHealth() {
  const deadline = Date.now() + 10_000;
  while (Date.now() < deadline) {
    try {
      const health = await (await fetch(`${base}/api/health`)).json();
      if (health.ok) return;
    } catch {
      // retry
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error("Studio server did not become healthy");
}

async function fetchJson(url, method = "GET", body) {
  const response = await fetch(url, {
    method,
    headers: body ? { "content-type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  return response.json();
}
