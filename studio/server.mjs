import { spawn } from "node:child_process";
import { createServer } from "node:http";
import { existsSync, promises as fs } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "..");
const args = parseArgs(process.argv.slice(2));
const workspace = path.resolve(args.workspace || repoRoot);
const runtimeRoot = path.resolve(args.runtimeRoot || repoRoot);
const port = Number(args.port || process.env.ASTERIA_STUDIO_PORT || 8787);
const python = args.python || process.env.ASTERIA_PYTHON || "python";
const moduleName = process.env.ASTERIA_MODULE || "asteria_runtime";
const distDir = path.join(__dirname, "dist");
const liveJobs = new Map();

createServer(async (request, response) => {
  try {
    const url = new URL(request.url || "/", `http://${request.headers.host || "localhost"}`);
    if (url.pathname.startsWith("/api/")) {
      await handleApi(request, response, url);
      return;
    }
    await serveStatic(response, url.pathname);
  } catch (error) {
    sendJson(response, 500, { ok: false, error: String(error?.message || error) });
  }
}).listen(port, "127.0.0.1", () => {
  console.log(`Asteria Studio listening on http://127.0.0.1:${port}`);
  console.log(`workspace=${workspace}`);
});

async function handleApi(request, response, url) {
  if (request.method === "GET" && url.pathname === "/api/health") {
    sendJson(response, 200, { ok: true, workspace, runtimeRoot, python, moduleName });
    return;
  }
  if (request.method === "GET" && url.pathname === "/api/studio/sessions") {
    sendJson(response, 200, { ok: true, sessions: await listSessions() });
    return;
  }
  if (request.method === "POST" && url.pathname === "/api/studio/sessions") {
    sendJson(response, 200, { ok: true, session: await createSession() });
    return;
  }
  if (request.method === "GET" && url.pathname.match(/^\/api\/studio\/sessions\/[^/]+$/)) {
    const sessionId = decodeURIComponent(url.pathname.split("/").pop() || "");
    sendJson(response, 200, await readSession(sessionId));
    return;
  }
  if (request.method === "GET" && url.pathname.match(/^\/api\/studio\/sessions\/[^/]+\/events$/)) {
    const sessionId = decodeURIComponent(url.pathname.split("/").at(-2) || "");
    sendJson(response, 200, { ok: true, events: await readSessionEvents(sessionId) });
    return;
  }
  if (request.method === "POST" && url.pathname.match(/^\/api\/studio\/sessions\/[^/]+\/messages$/)) {
    const sessionId = decodeURIComponent(url.pathname.split("/").at(-2) || "");
    sendJson(response, 200, await submitUserGoal(sessionId, await readRequestJson(request)));
    return;
  }
  if (request.method === "GET" && url.pathname === "/api/studio/files") {
    sendJson(response, 200, { ok: true, files: await listWorkspaceFiles() });
    return;
  }
  if (request.method === "POST" && url.pathname === "/api/studio/files/preview") {
    sendJson(response, 200, await previewWorkspaceFile(await readRequestJson(request)));
    return;
  }
  if (request.method === "GET" && url.pathname === "/api/studio/settings") {
    sendJson(response, 200, {
      ok: true,
      settings: {
        workMode: "engineering",
        permissionMode: "ask-for-write",
        shell: "PowerShell",
        streamMode: "runtime-model-events",
        workspace,
        runtimeRoot
      }
    });
    return;
  }
  if (request.method === "GET" && url.pathname === "/api/overview") {
    sendJson(response, 200, await overview());
    return;
  }
  sendJson(response, 404, { ok: false, error: "not found" });
}

async function submitUserGoal(sessionId, body) {
  const session = await ensureSession(sessionId);
  const goal = redactText(String(body?.message || "")).trim();
  const mode = String(body?.mode || "plan");
  const permission = String(body?.permission || "ask");
  if (!goal) return { ok: false, error: "message is required" };

  await appendEvent(session.session_id, {
    type: "user_message",
    status: "completed",
    title: "User",
    summary: goal,
    content_delta: goal
  });
  await appendEvent(session.session_id, {
    type: "assistant_delta",
    status: "completed",
    title: "理解目标",
    summary: "我已收到目标，会先核对意图和边界，再进入计划或执行。",
    content_delta: acknowledgementFor(mode, goal)
  });
  await appendEvent(session.session_id, progressEventForMode(mode, goal));

  if (mode !== "plan" && permission !== "allow") {
    const command = runtimeCommand(mode, goal);
    await appendEvent(session.session_id, {
      type: "permission_request",
      status: "waiting_user",
      title: "需要权限确认",
      summary: "这个动作可能写文件或调用工具。",
      command,
      content_delta: "允许本次执行，或切回 Plan 模式只生成计划。"
    });
    return { ok: true, session, started: false, needs_permission: true };
  }

  startRuntimeJob(session.session_id, mode, goal);
  return { ok: true, session, started: true };
}

function startRuntimeJob(sessionId, mode, goal) {
  const command = runtimeCommand(mode, goal);
  const jobId = `job-${Date.now()}`;
  const job = { job_id: jobId, session_id: sessionId, status: "running", command };
  liveJobs.set(jobId, job);

  void appendEvent(sessionId, {
    type: "tool_start",
    status: "running",
    title: "Runtime 已启动",
    summary: "正在运行命令。主线程会显示模型反馈，原始命令输出放在 Inspector。",
    display_level: "inspector",
    command
  });

  const child = spawn(command[0], command.slice(1), {
    cwd: runtimeRoot,
    env: {
      ...process.env,
      ASTERIA_STUDIO_EVENT_SINK: sessionPath(sessionId, "events.jsonl"),
      ASTERIA_STUDIO_SESSION_ID: sessionId,
      ASTERIA_STUDIO_PHASE: phaseForMode(mode),
      PYTHONIOENCODING: "utf-8"
    },
    windowsHide: true
  });

  let stdout = "";
  let stderr = "";
  child.stdout.on("data", (chunk) => {
    const text = redactText(chunk.toString());
    stdout = tailText(stdout + text, 24000);
    void appendEvent(sessionId, {
      type: "tool_delta",
      status: "running",
      title: "Runtime 输出",
      summary: summarizeRuntimeChunk(text),
      content_delta: text,
      display_level: "inspector",
      command
    });
  });
  child.stderr.on("data", (chunk) => {
    const text = redactText(chunk.toString());
    stderr = tailText(stderr + text, 16000);
    void appendEvent(sessionId, {
      type: "tool_delta",
      status: "running",
      title: "Runtime 诊断",
      summary: summarizeRuntimeChunk(text),
      content_delta: text,
      display_level: "inspector",
      command
    });
  });
  child.on("close", (code) => {
    job.status = code === 0 ? "completed" : "failed";
    liveJobs.set(jobId, job);
    void appendEvent(sessionId, {
      type: "tool_end",
      status: job.status,
      title: code === 0 ? "Runtime 完成" : "Runtime 失败",
      summary: code === 0 ? "执行完成，正在整理最终回复。" : "执行没有成功完成，需要查看失败原因。",
      command,
      display_level: "inspector",
      content_delta: stderr ? `stderr:\n${stderr}` : stdout.slice(-4000)
    });
    void appendEvent(sessionId, {
      type: code === 0 ? "final_answer" : "error",
      status: code === 0 ? "completed" : "failed",
      title: code === 0 ? "正式回复" : "需要处理的问题",
      summary: code === 0 ? "这是根据真实模型和 runtime 结果整理出的回复。" : "这次没有完成，我会给出失败原因和可选下一步。",
      phase: code === 0 ? "result" : "review",
      display_level: "main",
      content_delta: finalTextFor(mode, code, stdout, stderr),
      evidence_refs: [sessionPath(sessionId, "events.jsonl")]
    });
  });
  child.on("error", (error) => {
    job.status = "failed";
    liveJobs.set(jobId, job);
    void appendEvent(sessionId, {
      type: "error",
      status: "failed",
      title: "Runtime 启动失败",
      summary: String(error),
      content_delta: redactText(String(error)),
      command
    });
  });
}

function runtimeCommand(mode, goal) {
  if (mode === "run") {
    return [python, "-m", moduleName, "run", "--root", workspace, "--max-iterations", "2", "--max-tasks-per-iteration", "1", "--no-research", goal];
  }
  if (mode === "review") return [python, "-m", moduleName, "review", "--root", workspace];
  if (mode === "resume") return [python, "-m", moduleName, "resume", "--root", workspace, "--max-iterations", "2", "--max-tasks-per-iteration", "1"];
  return [python, "-m", moduleName, "plan", "--root", workspace, goal];
}

function acknowledgementFor(mode, goal) {
  if (mode === "plan") return `收到。我会先用真实模型为这个目标制定计划：${goal}`;
  if (mode === "run") return `收到。我会在受控范围内推进这个任务：${goal}`;
  if (mode === "review") return "收到。我会审查当前运行结果，并总结问题和下一步。";
  if (mode === "resume") return "收到。我会在受限条件下恢复当前任务。";
  return `收到。我会围绕这个目标推进：${goal}`;
}

function progressEventForMode(mode, goal) {
  if (mode === "run") {
    return {
      type: "reasoning_delta",
      status: "running",
      title: "执行",
      summary: "我会按受控范围推进任务，并把需要你确认的权限、文件变化和结果放回同一条任务线。",
      phase: "execute",
      display_level: "main",
      content_delta: `目标：${goal}\n当前阶段：准备执行。`
    };
  }
  if (mode === "review") {
    return {
      type: "reasoning_delta",
      status: "running",
      title: "核对",
      summary: "我会检查已有结果、失败证据和下一步风险。",
      phase: "review",
      display_level: "main",
      content_delta: "当前阶段：核对结果与证据。"
    };
  }
  if (mode === "resume") {
    return {
      type: "reasoning_delta",
      status: "running",
      title: "继续",
      summary: "我会接上已有上下文继续推进，并避免重复已经完成的步骤。",
      phase: "resume",
      display_level: "main",
      content_delta: "当前阶段：恢复任务上下文。"
    };
  }
  return {
    type: "reasoning_delta",
    status: "running",
    title: "制定计划",
    summary: "我会把目标拆成可执行步骤，并标出约束、风险和下一步。",
    phase: "plan",
    display_level: "main",
    content_delta: `目标：${goal}\n当前阶段：制定计划。`
  };
}

function phaseForMode(mode) {
  if (mode === "run") return "execute";
  if (mode === "review") return "review";
  if (mode === "resume") return "resume";
  return "plan";
}

function summarizeRuntimeChunk(text) {
  const clean = String(text || "").replace(/\s+/g, " ").trim();
  if (!clean) return "后台有新的运行输出。";
  if (/timeout|deadline|timed out/i.test(clean)) return "模型或运行步骤出现超时迹象。";
  if (/error|failed|traceback/i.test(clean)) return "运行过程中出现错误，需要核对。";
  if (/plan|goal|task/i.test(clean)) return "runtime 正在返回任务相关内容。";
  if (/created|written|file/i.test(clean)) return "运行过程产生了文件或产物更新。";
  return clean.slice(0, 120);
}

function finalTextFor(mode, code, stdout, stderr) {
  if (code !== 0) {
    return [
      "## 结果",
      "这次任务没有成功完成。",
      "",
      "## 需要处理",
      trimForUser(stderr || stdout || "没有捕获到输出。"),
      "",
      "## 下一步",
      "可以重试、切换模型/路由，或把失败证据导出后继续诊断。"
    ].join("\n");
  }
  const text = stdout.trim();
  const result = text ? trimForUser(text) : "Runtime 已完成，但没有返回文本输出。可以在 Inspector 查看证据和产物。";
  return [
    "## 结果",
    result,
    "",
    "## 下一步",
    nextStepForMode(mode)
  ].join("\n");
}

function nextStepForMode(mode) {
  if (mode === "plan") return "你可以直接要求执行计划，或指出要调整的范围、风格和约束。";
  if (mode === "run") return "你可以检查产物、继续迭代，或要求我进入 review。";
  if (mode === "review") return "你可以选择修复问题、继续执行，或导出证据。";
  if (mode === "resume") return "你可以继续推进当前任务，或要求我先总结当前状态。";
  return "你可以继续给出下一步要求。";
}

function trimForUser(text) {
  const clean = String(text || "").trim();
  if (!clean) return "";
  return clean.length > 8000 ? clean.slice(-8000) : clean;
}

async function overview() {
  const [gateStatus, doctor, packageCheck, runs, modelRoutes] = await Promise.all([
    commandJson(["gate-status", "--root", workspace, "--json"]),
    commandJson(["doctor", "--root", workspace, "--json"]),
    commandJson(["package-check", "--root", runtimeRoot, "--json"]),
    readRuns(),
    modelRouteSummary()
  ]);
  return {
    ok: true,
    workspace,
    runtimeRoot,
    gateStatus,
    doctor,
    packageCheck,
    runs: runs.slice(0, 10),
    modelRoutes
  };
}

async function createSession() {
  const sessionId = `session-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`;
  const now = new Date().toISOString();
  const session = {
    schema_version: "0.1.0",
    session_id: sessionId,
    title: "New task",
    workspace,
    created_at: now,
    updated_at: now
  };
  await fs.mkdir(sessionPath(sessionId), { recursive: true });
  await fs.writeFile(sessionPath(sessionId, "session.json"), JSON.stringify(session, null, 2), "utf8");
  await appendEvent(sessionId, {
    type: "assistant_delta",
    status: "completed",
    title: "Asteria Ready",
    summary: "告诉我你要完成什么任务。",
    content_delta: "我会在主线程展示模型反馈、计划、权限请求和最终结果；命令细节会放在 Inspector。"
  });
  return session;
}

async function ensureSession(sessionId) {
  if (!isSafeId(sessionId)) return createSession();
  const loaded = await readSession(sessionId);
  if (loaded.ok) return loaded.session;
  return createSession();
}

async function readSession(sessionId) {
  if (!isSafeId(sessionId)) return { ok: false, error: "invalid session id" };
  const file = sessionPath(sessionId, "session.json");
  if (!existsSync(file)) return { ok: false, error: "session not found" };
  return { ok: true, session: JSON.parse(await fs.readFile(file, "utf8")), events: await readSessionEvents(sessionId) };
}

async function listSessions() {
  const root = path.join(workspace, ".asteria", "studio", "sessions");
  if (!existsSync(root)) return [];
  const entries = await fs.readdir(root, { withFileTypes: true });
  const sessions = [];
  for (const entry of entries) {
    if (!entry.isDirectory()) continue;
    const loaded = await readSession(entry.name);
    if (loaded.ok) sessions.push(loaded.session);
  }
  return sessions.sort((a, b) => String(b.updated_at).localeCompare(String(a.updated_at)));
}

async function appendEvent(sessionId, event) {
  if (!isSafeId(sessionId)) return;
  const full = {
    schema_version: "0.1.0",
    event_id: `evt-${Date.now()}-${Math.random().toString(16).slice(2)}`,
    session_id: sessionId,
    created_at: new Date().toISOString(),
    artifact_refs: [],
    evidence_refs: [],
    ...redact(event)
  };
  await fs.mkdir(sessionPath(sessionId), { recursive: true });
  await fs.appendFile(sessionPath(sessionId, "events.jsonl"), `${JSON.stringify(full)}\n`, "utf8");
  const sessionFile = sessionPath(sessionId, "session.json");
  if (existsSync(sessionFile)) {
    const session = JSON.parse(await fs.readFile(sessionFile, "utf8"));
    session.updated_at = full.created_at;
    if (full.type === "user_message") session.title = String(full.summary || session.title).slice(0, 64);
    await fs.writeFile(sessionFile, JSON.stringify(session, null, 2), "utf8");
  }
}

async function readSessionEvents(sessionId) {
  if (!isSafeId(sessionId)) return [];
  const file = sessionPath(sessionId, "events.jsonl");
  if (!existsSync(file)) return [];
  return (await fs.readFile(file, "utf8")).split(/\r?\n/).filter(Boolean).map((line) => {
    try {
      return redact(JSON.parse(line));
    } catch {
      return { type: "raw", content_delta: redactText(line) };
    }
  });
}

function sessionPath(sessionId, file = "") {
  return path.join(workspace, ".asteria", "studio", "sessions", sessionId, file);
}

function isSafeId(value) {
  return /^[A-Za-z0-9_.-]+$/.test(String(value || ""));
}

async function commandJson(commandArgs) {
  const completed = await runCommand([python, "-m", moduleName, ...commandArgs], runtimeRoot);
  if (completed.code !== 0) return { ok: false, code: completed.code, stdout: redactText(completed.stdout), stderr: redactText(completed.stderr) };
  try {
    return redact(JSON.parse(completed.stdout));
  } catch {
    return { ok: false, status: "invalid_json", stdout: redactText(completed.stdout), stderr: redactText(completed.stderr) };
  }
}

function runCommand(command, cwd) {
  return new Promise((resolve) => {
    const child = spawn(command[0], command.slice(1), { cwd, env: process.env, windowsHide: true });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => {
      stdout += chunk.toString();
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk.toString();
    });
    child.on("close", (code) => resolve({ code, stdout, stderr }));
    child.on("error", (error) => resolve({ code: 1, stdout, stderr: String(error) }));
  });
}

async function readRuns() {
  const runsDir = path.join(workspace, ".asteria", "runs");
  if (!existsSync(runsDir)) return [];
  const entries = await fs.readdir(runsDir, { withFileTypes: true });
  const runs = [];
  for (const entry of entries) {
    if (!entry.isDirectory()) continue;
    const runDir = path.join(runsDir, entry.name);
    runs.push(redact({ run_id: entry.name, ...(await readJson(path.join(runDir, "run.json"))), cost_report: await readJson(path.join(runDir, "cost_report.json")) }));
  }
  return runs.sort((a, b) => String(b.run_id).localeCompare(String(a.run_id)));
}

async function modelRouteSummary() {
  const runs = await readRuns();
  const summary = new Map();
  for (const run of runs.slice(0, 20)) {
    const calls = await readJsonlTail(path.join(workspace, ".asteria", "runs", run.run_id, "model_calls.jsonl"), 500);
    for (const call of calls) {
      const key = [call.model_provider || "unknown", call.model_name || "unknown", call.purpose || "unknown", call.model_tier || "unknown"].join("/");
      const item = summary.get(key) || { key, provider: call.model_provider || "unknown", model: call.model_name || "unknown", purpose: call.purpose || "unknown", tier: call.model_tier || "unknown", total: 0, success: 0, failure: 0, streamingFailed: 0, durationMs: [] };
      item.total += 1;
      if (call.status === "success") item.success += 1;
      if (call.status === "failure") item.failure += 1;
      if (call.streaming?.mode === "streaming_failed") item.streamingFailed += 1;
      if (Number.isFinite(call.streaming?.duration_ms)) item.durationMs.push(call.streaming.duration_ms);
      else if (Number.isFinite(call.duration_ms)) item.durationMs.push(call.duration_ms);
      summary.set(key, item);
    }
  }
  return [...summary.values()].map((item) => ({
    ...item,
    successRate: item.total ? Number((item.success / item.total).toFixed(4)) : 0,
    durationP95: percentile(item.durationMs, 0.95)
  })).sort((a, b) => b.total - a.total);
}

async function listWorkspaceFiles() {
  const roots = [".asteria/studio/sessions", ".asteria/verification", "docs/zh", "studio/src"];
  const files = [];
  for (const relativeRoot of roots) {
    const absoluteRoot = path.join(workspace, relativeRoot);
    if (existsSync(absoluteRoot)) await collectFiles(absoluteRoot, files, 0);
  }
  return files.sort((a, b) => String(b.modified_at).localeCompare(String(a.modified_at))).slice(0, 80);
}

async function collectFiles(directory, files, depth) {
  if (depth > 4 || files.length > 200) return;
  let entries = [];
  try {
    entries = await fs.readdir(directory, { withFileTypes: true });
  } catch {
    return;
  }
  for (const entry of entries) {
    const absolute = path.join(directory, entry.name);
    const relative = path.relative(workspace, absolute).replace(/\\/g, "/");
    if (!isSafeWorkspacePath(relative)) continue;
    if (entry.isDirectory()) {
      await collectFiles(absolute, files, depth + 1);
      continue;
    }
    if (!isPreviewableFile(relative)) continue;
    const stat = await fs.stat(absolute);
    files.push({ path: relative, size: stat.size, modified_at: stat.mtime.toISOString() });
  }
}

async function previewWorkspaceFile(body) {
  const relative = String(body?.path || "").replace(/\\/g, "/");
  if (!isSafeWorkspacePath(relative) || !isPreviewableFile(relative)) return { ok: false, error: "file is not previewable" };
  const absolute = path.resolve(workspace, relative);
  if (!absolute.startsWith(workspace) || !existsSync(absolute)) return { ok: false, error: "file not found" };
  const stat = await fs.stat(absolute);
  if (stat.size > 120_000) return { ok: false, error: "file too large for preview" };
  return { ok: true, path: relative, size: stat.size, content: redactText(await fs.readFile(absolute, "utf8")) };
}

function isSafeWorkspacePath(relative) {
  const normalized = String(relative || "").replace(/\\/g, "/");
  if (!normalized || normalized.includes("..")) return false;
  if (/^\.git(\/|$)/i.test(normalized) || /^secrets(\/|$)/i.test(normalized)) return false;
  if (/\.env(\.|$)/i.test(path.basename(normalized))) return false;
  if (/\.(pem|key)$/i.test(normalized)) return false;
  if (/(^|\/)(id_rsa|id_ed25519|model\.routes\.local\.(ps1|json))$/i.test(normalized)) return false;
  if (/(node_modules|dist)(\/|$)/i.test(normalized)) return false;
  return true;
}

function isPreviewableFile(relative) {
  return /\.(md|txt|json|jsonl|py|ts|tsx|js|mjs|css|html|toml|yaml|yml)$/i.test(relative);
}

async function readJson(file) {
  try {
    return JSON.parse(await fs.readFile(file, "utf8"));
  } catch {
    return {};
  }
}

async function readJsonlTail(file, limit) {
  try {
    return (await fs.readFile(file, "utf8")).split(/\r?\n/).filter(Boolean).slice(-limit).map((line) => {
      try {
        return JSON.parse(line);
      } catch {
        return { raw: redactText(line) };
      }
    });
  } catch {
    return [];
  }
}

async function serveStatic(response, pathname) {
  if (!existsSync(distDir)) {
    response.writeHead(200, { "content-type": "text/plain; charset=utf-8" });
    response.end("Asteria Studio API is running. Start Vite with `npm run dev` for the UI.");
    return;
  }
  const relative = pathname === "/" ? "index.html" : pathname.replace(/^\/+/, "");
  const target = path.resolve(distDir, relative);
  if (!target.startsWith(distDir)) {
    sendJson(response, 403, { ok: false, error: "forbidden" });
    return;
  }
  const file = existsSync(target) ? target : path.join(distDir, "index.html");
  const type = { ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml" }[path.extname(file)] || "application/octet-stream";
  response.writeHead(200, { "content-type": type });
  response.end(await fs.readFile(file));
}

function readRequestJson(request) {
  return new Promise((resolve) => {
    let raw = "";
    request.on("data", (chunk) => {
      raw += chunk.toString();
      if (raw.length > 64_000) request.destroy();
    });
    request.on("end", () => {
      try {
        resolve(raw ? JSON.parse(raw) : {});
      } catch {
        resolve({});
      }
    });
    request.on("error", () => resolve({}));
  });
}

function sendJson(response, status, payload) {
  response.writeHead(status, { "content-type": "application/json; charset=utf-8" });
  response.end(JSON.stringify(payload, null, 2));
}

function parseArgs(items) {
  const parsed = {};
  for (let index = 0; index < items.length; index += 1) {
    const item = items[index];
    if (!item.startsWith("--")) continue;
    parsed[item.slice(2).replace(/-([a-z])/g, (_, char) => char.toUpperCase())] = items[index + 1];
    index += 1;
  }
  return parsed;
}

function redact(value) {
  if (Array.isArray(value)) return value.map(redact);
  if (!value || typeof value !== "object") return typeof value === "string" ? redactText(value) : value;
  const result = {};
  for (const [key, item] of Object.entries(value)) {
    result[key] = /api[_-]?key|authorization|token|secret|password|credential/i.test(key) ? "[REDACTED]" : redact(item);
  }
  return result;
}

function redactText(text) {
  return String(text)
    .replace(/(api[_-]?key|authorization|token|secret|password)\s*[:=]\s*['"]?[^'",}\s]+/gi, "$1=[REDACTED]")
    .replace(/(bearer\s+)[A-Za-z0-9._-]+/gi, "$1[REDACTED]");
}

function tailText(text, limit) {
  return text.length > limit ? text.slice(-limit) : text;
}

function percentile(values, q) {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.min(sorted.length - 1, Math.max(0, Math.round((sorted.length - 1) * q)))];
}
