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
const pendingJobs = new Map(); // jobId -> { sessionId, mode, goal, command }
const sseClients = new Map(); // sessionId -> Set<response>

function notifySSE(sessionId, event) {
  const clients = sseClients.get(sessionId);
  if (!clients?.size) return;
  const payload = `data: ${JSON.stringify(event)}\n\n`;
  for (const res of [...clients]) {
    try { res.write(payload); } catch { clients.delete(res); }
  }
}

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
  if (request.method === "GET" && url.pathname.match(/^\/api\/studio\/sessions\/[^/]+\/events\/stream$/)) {
    const sessionId = decodeURIComponent(url.pathname.split("/").at(-3) || "");
    if (!isSafeId(sessionId)) { sendJson(response, 400, { ok: false, error: "invalid session id" }); return; }
    response.writeHead(200, {
      "Content-Type": "text/event-stream; charset=utf-8",
      "Cache-Control": "no-cache",
      "Connection": "keep-alive",
      "X-Accel-Buffering": "no"
    });
    response.write(": connected\n\n");
    const existingEvents = await readSessionEvents(sessionId);
    for (const event of existingEvents) {
      response.write(`data: ${JSON.stringify(event)}\n\n`);
    }
    if (!sseClients.has(sessionId)) sseClients.set(sessionId, new Set());
    sseClients.get(sessionId).add(response);
    const ping = setInterval(() => { try { response.write(": ping\n\n"); } catch {} }, 15000);
    request.on("close", () => {
      clearInterval(ping);
      sseClients.get(sessionId)?.delete(response);
    });
    return;
  }
  if (request.method === "POST" && url.pathname.match(/^\/api\/studio\/sessions\/[^/]+\/messages$/)) {
    const sessionId = decodeURIComponent(url.pathname.split("/").at(-2) || "");
    sendJson(response, 200, await submitUserGoal(sessionId, await readRequestJson(request)));
    return;
  }
  if (request.method === "PATCH" && url.pathname.match(/^\/api\/studio\/sessions\/[^/]+\/jobs\/[^/]+\/permission$/)) {
    const parts = url.pathname.split("/");
    // /api/studio/sessions/SESSION_ID/jobs/JOB_ID/permission
    const sessionId = decodeURIComponent(parts.at(-4) || "");
    const jobId = decodeURIComponent(parts.at(-2) || "");
    sendJson(response, 200, await handlePermission(sessionId, jobId, await readRequestJson(request)));
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
  if (request.method === "GET" && url.pathname.match(/^\/api\/runs\/[^/]+$/)) {
    const runId = decodeURIComponent(url.pathname.split("/").pop() || "");
    sendJson(response, 200, await readRunDetail(runId));
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

  // Chat mode: instant local response, no CLI spawn
  if (mode === "chat") {
    return handleChatMode(session.session_id, goal);
  }

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
    const pendingJobId = `pending-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`;
    pendingJobs.set(pendingJobId, { sessionId: session.session_id, mode, goal, command });
    await appendEvent(session.session_id, {
      type: "permission_request",
      status: "waiting_user",
      title: "需要权限确认",
      summary: "这个动作可能写文件或调用工具，请确认是否允许。",
      command,
      job_id: pendingJobId,
      content_delta: "允许后将立即启动，或取消后切回 plan 模式先查看计划。"
    });
    return { ok: true, session, started: false, needs_permission: true, job_id: pendingJobId };
  }

  startRuntimeJob(session.session_id, mode, goal);
  return { ok: true, session, started: true };
}

// ─── Chat mode: instant local answer, zero CLI overhead ─────────────────────

async function handleChatMode(sessionId, goal) {
  await appendEvent(sessionId, {
    type: "user_message",
    status: "completed",
    title: "User",
    summary: goal.slice(0, 80),
    content_delta: goal,
    phase: "understand",
    display_level: "main",
  });
  const content = await buildChatAnswer(goal, sessionId);
  await appendEvent(sessionId, {
    type: "final_answer",
    status: "completed",
    title: "Asteria",
    summary: "即时回复，未调用 CLI。",
    phase: "result",
    display_level: "main",
    content_delta: content,
  });
  return { ok: true, chat: true };
}

async function buildChatAnswer(message, sessionId) {
  const m = message.trim();
  const lower = m.toLowerCase();

  if (/你是谁|who are you|自我介绍|介绍.{0,4}自己|你叫什么/.test(lower)) return CHAT_INTRO;
  if (/帮助|help|怎么用|如何使用|使用说明|教程/.test(lower)) return CHAT_HELP;
  if (/状态|status|当前|现在怎样|运行情况/.test(lower)) return await chatStatusAnswer(sessionId);
  if (/你好|hello|hi\b|嗨|早|晚上好|下午好/.test(lower)) return CHAT_GREETING;
  if (/plan|run|review|resume|什么模式|模式区别|怎么选/.test(lower)) return CHAT_MODES;
  if (/chat|对话.*模式|聊天模式/.test(lower)) return CHAT_ABOUT_CHAT;
  if (/证据|evidence|inspector|产物|artifact/.test(lower)) return CHAT_EVIDENCE;

  // Looks like a task accidentally sent in chat mode → suggest switching
  const looksLikeTask = m.length > 15 && /[。！？，]|实现|修复|重构|添加|生成|补全|创建|更新|检查|分析/.test(m);
  if (looksLikeTask) return chatTaskSuggestion(m);

  return chatDefault(m);
}

async function chatStatusAnswer(sessionId) {
  try {
    const runsDir = path.join(workspace, ".asteria", "runs");
    let latestRunLine = "暂无运行记录。";
    if (existsSync(runsDir)) {
      const dirs = (await fs.readdir(runsDir)).filter((d) => /^run-\d{8}-\d{4}/.test(d)).sort().reverse();
      if (dirs.length) {
        const runJson = await readJson(path.join(runsDir, dirs[0], "run.json")).catch(() => ({}));
        const status = firstRuntimeText(runJson.status, "unknown");
        const goal = firstRuntimeText(runJson.goal, runJson.original_goal, "未记录目标");
        latestRunLine = `最近 run：**${dirs[0]}**（${status}）\n目标：${goal.slice(0, 100)}`;
      }
    }
    return `## 当前状态\n\n工作区：\`${workspace}\`\n\n${latestRunLine}\n\n使用 Inspector 右侧面板查看完整证据，或切换 **review** 模式出具质量评审。`;
  } catch {
    return `## 当前状态\n\n工作区：\`${workspace}\`\n\n无法读取运行记录，请刷新后重试。`;
  }
}

function chatTaskSuggestion(message) {
  return `## 看起来是一个任务

你的消息：**${message.slice(0, 80)}**

当前是 **chat** 模式（即时问答），不会调用 CLI。

如果你想执行这个任务：
- 切换到 **plan** → 先出执行计划
- 切换到 **run** → 直接执行（plan + execute + review）

切换方式：点击下方模式选择器，再重新发送。`;
}

function chatDefault(message) {
  return `## 收到

你问的是：**${message.slice(0, 100)}**

我暂时没有针对这个问题的内置回答。你可以：
- 切换 **plan** 或 **run** 模式，把它变成一个任务让我执行
- 换个关键词再问（支持：你是谁 / 怎么用 / 当前状态 / 模式区别 / 证据）`;
}

const CHAT_INTRO = `## 我是 Asteria

本地优先的多智能体自主开发运行时。

**核心定位**
把你的目标转化为可验证的工作产物——计划、代码补丁、测试、报告。每一步都有证据，失败时硬停，不盲目修复。

**四个工作模式**
| 模式 | 做什么 |
|------|--------|
| plan | 分析目标 → 拆解结构化任务计划（不执行）|
| run | 完整执行：plan + execute + debug + review |
| review | 对最近一次 run 出具独立质量评审 |
| resume | 恢复被中断的 run |

**当前模式 chat** 是即时问答，不调用 CLI，没有延迟。

想开始一个任务？切换到 **plan** 或 **run** 然后描述目标。`;

const CHAT_GREETING = `你好！我是 Asteria，本地多智能体开发运行时。

现在是 **chat** 模式——问我任何问题都会即时回答，没有等待。

想让我执行任务，切换到 **plan**（先看计划）或 **run**（直接执行）。`;

const CHAT_HELP = `## 使用指南

**模式选择**（下方选择器）
| 模式 | 适合场景 |
|------|---------|
| **chat** | 快速问答，了解 Asteria，查看状态 |
| **plan** | 先看任务拆解再决定是否执行 |
| **run** | 直接完整执行，包含 debug 和 review |
| **review** | 评审最近一次 run 的质量 |
| **resume** | 恢复因超预算/pending decision 中断的 run |

**权限控制**（plan/run/resume 模式下显示）
- 写入前询问 → 每次写文件前弹出确认卡片
- 直接允许 → 自动放行（适合信任的工作区）

**快捷键**：Ctrl+Enter 发送

**Inspector**（右侧面板）：查看原始事件、模型调用、证据文件和产物引用。`;

const CHAT_MODES = `## 模式说明

**chat** — 当前模式。即时本地回复，不调用 CLI，零等待。适合问答和了解状态。

**plan** — 只分析目标、生成任务计划，不执行任何代码。适合先看思路再决定。

**run** — 完整执行：制定计划 → 执行任务 → 调试失败 → 评审结果。一步到位。

**review** — 对最近一次 run 出具独立质量评审，判断是否达标、有无遗漏。

**resume** — 从上次中断处恢复。run 因超预算、待确认决策或权限等待暂停时使用。

---
**怎么选？**
- 第一次跑某个目标 → **plan** 先看拆解
- 目标清晰、工作区干净 → **run** 直接执行
- 上次没跑完 → **resume**
- 不确定质量 → **review**`;

const CHAT_ABOUT_CHAT = `## chat 模式

即时本地问答，不调用任何 CLI 命令，没有模型 API 调用，回复是瞬时的。

**支持的问题类型**
- 你是谁 / 自我介绍
- 怎么用 / 使用帮助
- 当前状态 / 最近运行
- 模式区别 / 怎么选
- 证据 / Inspector / 产物

**不支持的**：实际任务执行（请切换到 plan / run / review / resume）。`;

const CHAT_EVIDENCE = `## 证据与 Inspector

**Inspector（右侧面板）** 是 Asteria 的证据中心，包含：

- **Shell** — 原始命令输出（stdout/stderr）
- **Diff** — 文件变化对比
- **产物** — 生成的文件、报告引用
- **诊断** — 模型调用记录、worker 结果、验证结果、任务执行证据

**证据文件位置**（工作区 .asteria/runs/run-YYYYMMDD-XXXX/）
- \`goal_spec.json\` — 目标规格
- \`task_plan.json\` — 任务计划
- \`eval_report.json\` — 评审评分
- \`final_report.md\` — 完整运行报告
- \`worker_results.jsonl\` — 各 worker 执行结果
- \`model_calls.jsonl\` — 全部模型调用记录

点击 Thread 中的任意事件卡片，Inspector 会跳到对应细节。`;

// ─────────────────────────────────────────────────────────────────────────────

async function handlePermission(sessionId, jobId, body) {
  const action = String(body?.action || "");
  if (action === "allow") {
    const pending = pendingJobs.get(jobId);
    if (!pending || pending.sessionId !== sessionId) return { ok: false, error: "job not found or session mismatch" };
    pendingJobs.delete(jobId);
    await appendEvent(sessionId, {
      type: "assistant_delta",
      status: "completed",
      title: "已授权",
      summary: "权限已批准，正在启动 runtime...",
      phase: "execute",
      display_level: "main"
    });
    startRuntimeJob(sessionId, pending.mode, pending.goal);
    return { ok: true, started: true };
  }
  if (action === "deny") {
    pendingJobs.delete(jobId);
    await appendEvent(sessionId, {
      type: "assistant_delta",
      status: "completed",
      title: "已取消",
      summary: "操作已取消。如需继续，可以选择 plan 模式先查看计划，再决定是否执行。",
      phase: "next",
      display_level: "main"
    });
    return { ok: true, started: false };
  }
  return { ok: false, error: "invalid action, use allow or deny" };
}

/** Map user_progress channel → studio event type */
function channelToEventType(channel, eventType) {
  if (channel === "conclusion") return eventType === "message" ? "assistant_delta" : "reasoning_delta";
  if (channel === "model") return "reasoning_delta";
  if (channel === "tool") return "tool_start";
  if (channel === "file") return "tool_end";
  if (eventType === "heartbeat") return "tool_delta";
  return "reasoning_delta";
}

/**
 * While a subprocess is live, tail the current run's user_progress.jsonl every 1.2s
 * and emit new entries as SSE events.  Returns a stop function.
 */
function tailUserProgress(sessionId, jobId) {
  let stopped = false;
  let lastSeq = 0;
  let runDir = null;

  async function poll() {
    if (stopped) return;
    const job = liveJobs.get(jobId);
    if (!job) { stopped = true; return; }

    // Try to locate the run directory
    if (!runDir && job.run_id) {
      const candidate = path.join(workspace, ".asteria", "runs", job.run_id);
      if (existsSync(candidate)) runDir = candidate;
    }
    if (!runDir) {
      const runsDir = path.join(workspace, ".asteria", "runs");
      if (existsSync(runsDir)) {
        try {
          const dirs = (await fs.readdir(runsDir)).filter((d) => /^run-\d{8}-\d{4}/.test(d));
          const withStats = (
            await Promise.all(
              dirs.map(async (d) => {
                const p = path.join(runsDir, d);
                try { return { path: p, mtime: (await fs.stat(p)).mtimeMs }; } catch { return null; }
              })
            )
          ).filter(Boolean);
          const recent = withStats.filter((s) => s.mtime >= job.started_at_ms - 6000);
          if (recent.length) { recent.sort((a, b) => b.mtime - a.mtime); runDir = recent[0].path; }
        } catch {}
      }
    }

    if (runDir) {
      const progressPath = path.join(runDir, "user_progress.jsonl");
      if (existsSync(progressPath)) {
        try {
          const lines = (await fs.readFile(progressPath, "utf8")).split(/\r?\n/).filter(Boolean);
          for (const line of lines) {
            try {
              const evt = JSON.parse(line);
              const seq = Number(evt.sequence ?? 0);
              if (seq > lastSeq) {
                lastSeq = seq;
                // Emit via appendEvent so it persists in events.jsonl AND hits SSE
                void appendEvent(sessionId, {
                  event_id: evt.event_id,           // preserve original ID for client dedup
                  type: userProgressChannelToEventType(evt.channel, evt.event_type, evt.phase),
                  status: evt.status || "running",
                  title: evt.title || "",
                  summary: evt.summary || "",
                  phase: evt.phase || "",
                  content_delta: evt.content_delta || "",
                  display_level: evt.display_level || "main",
                  artifact_refs: evt.artifact_refs || [],
                  evidence_refs: evt.evidence_refs || [],
                });
              }
            } catch {}
          }
        } catch {}
      }
    }

    if (!stopped) setTimeout(poll, 1200);
  }

  // Brief delay so the subprocess has time to start writing
  setTimeout(poll, 1200);
  return () => { stopped = true; };
}

function startRuntimeJob(sessionId, mode, goal) {
  const command = runtimeCommand(mode, goal);
  const jobId = `job-${Date.now()}`;
  const job = {
    job_id: jobId,
    session_id: sessionId,
    status: "running",
    command,
    started_at_ms: Date.now(),
    run_id: null
  };
  liveJobs.set(jobId, job);

  void appendEvent(sessionId, {
    type: "tool_start",
    status: "running",
    title: "Runtime 已启动",
    summary: "正在运行命令。主线程会显示模型反馈，原始命令输出放在 Inspector。",
    display_level: "inspector",
    command
  });

  const stopTail = tailUserProgress(sessionId, jobId);

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
    rememberJobRunId(jobId, extractRunId(text) || extractRunId(stdout));
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
    rememberJobRunId(jobId, extractRunId(text) || extractRunId(stderr));
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
  child.on("close", async (code) => {
    stopTail();
    rememberJobRunId(jobId, extractRunId(stdout) || extractRunId(stderr));
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
      content_delta: await finalTextFor(mode, code, stdout, stderr),
      evidence_refs: [sessionPath(sessionId, "events.jsonl")],
      artifact_refs: runArtifactRefs(extractRunId(stdout))
    });
  });
  child.on("error", (error) => {
    stopTail();
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

async function finalTextFor(mode, code, stdout, stderr) {
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
  const runId = extractRunId(stdout) || extractRunId(stderr);
  if (mode === "plan" && runId) return withProcessDigest(runId, await planFinalTextForRun(runId, stdout));
  if ((mode === "run" || mode === "resume") && runId) return withProcessDigest(runId, await runFinalTextForRun(runId, stdout));
  if (mode === "review" && runId) return withProcessDigest(runId, await reviewFinalTextForRun(runId, stdout));
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

async function userProgressDigestLines(runId) {
  const runDir = path.join(workspace, ".asteria", "runs", runId);
  const events = await readJsonlTail(path.join(runDir, "user_progress.jsonl"), 1200);
  const counts = { model: 0, tool: 0, file: 0, evidence: 0 };
  const fileNames = [];
  for (const event of events) {
    const channel = String(event.channel || "");
    if (Object.hasOwn(counts, channel)) counts[channel] += 1;
    if (channel !== "file") continue;
    for (const change of event.file_changes || []) {
      const name = path.basename(String(change.path || ""));
      if (name && !fileNames.includes(name)) fileNames.push(name);
    }
  }
  const lines = [];
  if (counts.model) lines.push(`- 模型流式输出 ${counts.model} 段，用于理解目标、生成结构化计划或评审结论。`);
  if (counts.tool) lines.push(`- Runtime 记录 ${counts.tool} 个工具/内部执行事件，过程细节已收进 Inspector。`);
  if (counts.file) {
    const names = fileNames.slice(0, 4).join("、");
    lines.push(`- 写入或更新 ${counts.file} 个文件事件${names ? `：${names}` : ""}。`);
  }
  if (counts.evidence) lines.push(`- 沉淀 ${counts.evidence} 条证据引用，可回溯到 run 目录里的 JSON/Markdown 产物。`);
  return lines.length ? lines : ["- Runtime 已完成任务并保留原始事件；当前 run 暂无可折叠的用户进展摘要。"];
}

function userProgressChannelToEventType(channel, eventType, phase) {
  if (channel === "conclusion" && phase === "result") return "final_answer";
  return channelToEventType(channel, eventType);
}

async function withProcessDigest(runId, text) {
  const digest = await userProgressDigestLines(runId);
  const body = String(text || "").trim();
  return [
    body,
    "",
    "## 过程摘要",
    digest.join("\n"),
  ].filter(Boolean).join("\n");
}

async function planFinalTextForRun(runId, fallbackStdout) {
  const runDir = path.join(workspace, ".asteria", "runs", runId);
  const goalSpec = await readJson(path.join(runDir, "goal_spec.json"));
  const taskPlan = await readJson(path.join(runDir, "task_plan.json"));
  const taskEval = await readJson(path.join(runDir, "task_plan_eval.json"));
  const costReport = await readJson(path.join(runDir, "cost_report.json"));
  const tasks = Array.isArray(taskPlan.tasks) ? taskPlan.tasks : [];
  if (!Object.keys(goalSpec).length && !tasks.length) {
    return [
      "## 结果",
      "Runtime 已完成计划生成，但 Studio 暂时只能读取到产物收据，没能解析出计划内容。",
      "",
      "## 证据",
      trimForUser(fallbackStdout),
      "",
      "## 下一步",
      "请在 Inspector 或 Evidence Explorer 查看原始产物后重试。"
    ].join("\n");
  }
  const goal = firstRuntimeText(goalSpec.normalized_goal, goalSpec.original_goal, "已生成一份结构化计划。");
  const requirements = Array.isArray(goalSpec.expanded_requirements) ? goalSpec.expanded_requirements.length : 0;
  const warnings = Array.isArray(taskEval.issues) ? taskEval.issues.filter((issue) => issue.severity !== "error") : [];
  const recommendations = Array.isArray(taskEval.recommendations) ? taskEval.recommendations : [];
  const taskLines = tasks.slice(0, 5).map((task, index) => {
    const title = firstRuntimeText(task.title, task.task_id, `Task ${index + 1}`);
    const description = firstRuntimeText(task.description).replace(/\s+/g, " ");
    const acceptance = Array.isArray(task.acceptance) ? task.acceptance.slice(0, 3) : [];
    const artifacts = Array.isArray(task.expected_artifacts) ? task.expected_artifacts.slice(0, 3) : [];
    return [
      `- ${title}`,
      description ? `  目标：${description}` : "",
      acceptance.length ? `  验收：${acceptance.join("；")}` : "",
      artifacts.length ? `  产物：${artifacts.join("、")}` : "",
    ].filter(Boolean).join("\n");
  });
  const riskLines = [
    ...warnings.slice(0, 3).map((issue) => `- ${firstRuntimeText(issue.message, issue.code)}`),
    ...recommendations.slice(0, 3).map((item) => `- ${item}`)
  ];
  return [
    "## 答案",
    `我给你的规划结论是：围绕「${goal}」生成 ${tasks.length || 0} 个可执行任务，先按下面任务顺序推进。`,
    "",
    "## 任务计划",
    taskLines.length ? taskLines.join("\n") : "- 未生成可展示的任务条目。",
    "",
    "## 验收与风险",
    firstRuntimeText(taskEval.summary, `共 ${tasks.length} 个任务，${requirements} 条需求。`),
    riskLines.length ? [...new Set(riskLines)].join("\n") : "- 暂无明确阻断项；执行前仍应核对写入范围和验证命令。",
    "",
    "## 下一步",
    nextPlanAction(tasks, taskEval, costReport)
  ].join("\n");
}

function nextPlanAction(tasks, taskEval, costReport) {
  const status = String(taskEval.status || "").toLowerCase();
  const modelCalls = costReport.model_calls ?? costReport.total_model_calls;
  if (status === "warn") return "先把过大的任务拆成 3-5 个可独立验证的实现切片，再进入 run。模型调用和成本证据已记录在 Evidence Explorer。";
  if (tasks.length > 1) return `可以选择第一个切片进入 run，继续使用受控限制。${modelCalls != null ? `本次计划用了 ${modelCalls} 次模型调用。` : ""}`;
  return "可以直接要求执行该计划，或先调整范围、验收标准和风险边界。";
}

/** Build final text for run/resume modes — reads final_report.md and eval_report.json */
async function runFinalTextForRun(runId, fallbackStdout) {
  const runDir = path.join(workspace, ".asteria", "runs", runId);
  const goalSpec = await readJson(path.join(runDir, "goal_spec.json"));
  const taskPlan = await readJson(path.join(runDir, "task_plan.json"));
  const runJson = await readJson(path.join(runDir, "run.json"));
  const evalReport = await readJson(path.join(runDir, "eval_report.json"));
  const executionEvidence = await readJsonlTail(path.join(runDir, "task_execution_evidence.jsonl"), 30);
  const validationResults = await readJsonlTail(path.join(runDir, "validation_results.jsonl"), 30);
  const decisions = await readJsonlTail(path.join(runDir, "decisions.jsonl"), 20);
  const workerLines = await readWorkerSummaryLines(runDir);
  const taskRows = Array.isArray(taskPlan.tasks) ? taskPlan.tasks : [];
  const doneTasks = taskRows.filter((task) => task.status === "done");
  const blockedTasks = taskRows.filter((task) => task.status === "blocked");
  const pendingDecisions = decisions.filter((decision) => decision.status === "pending");
  const status = firstRuntimeText(runJson.status, evalReport?.overall?.status, "completed");
  const score = evalReport?.overall?.score != null ? `评分 ${Number(evalReport.overall.score).toFixed(2)}` : null;
  const reason = firstRuntimeText(evalReport?.overall?.reason);
  const costReport = await readJson(path.join(runDir, "cost_report.json"));
  const modelCalls = costReport.model_calls ?? costReport.total_model_calls;
  const artifacts = await runArtifactLines(runDir);
  const evidenceLines = executionEvidence.slice(-5).map((item) => {
    const taskId = firstRuntimeText(item.task_id, item.task?.task_id, "task");
    const itemStatus = firstRuntimeText(item.status, "unknown");
    const summary = firstRuntimeText(item.summary, item.failure_type, "").replace(/\s+/g, " ");
    return `- ${taskId}: ${itemStatus}${summary ? ` - ${summary}` : ""}`;
  });
  const validationLines = validationResults.slice(-5).map((item) => {
    const label = firstRuntimeText(item.name, item.command, item.validation_result_id, "validation");
    const itemStatus = firstRuntimeText(item.status, item.outcome, "unknown");
    const summary = firstRuntimeText(item.summary, item.error, "");
    return `- ${label}: ${itemStatus}${summary ? ` - ${summary}` : ""}`;
  });
  const answerLine = runAnswerLine({
    runId,
    goal: firstRuntimeText(goalSpec.normalized_goal, goalSpec.original_goal, runJson.goal, "本次目标"),
    status,
    done: doneTasks.length,
    total: taskRows.length,
    blocked: blockedTasks.length,
    decisions: pendingDecisions.length,
  });
  return [
    "## 答案",
    answerLine,
    "",
    "## 完成情况",
    `- 状态：${status}`,
    `- 任务：${doneTasks.length}/${taskRows.length} 完成，${blockedTasks.length} 个阻断`,
    pendingDecisions.length ? `- 待决策：${pendingDecisions.length} 个，需要你选择后继续` : "- 待决策：无",
    score || reason ? `- 评审：${[score, reason].filter(Boolean).join("；")}` : "",
    "",
    ...(artifacts.length ? ["## 产物", ...artifacts, ""] : []),
    ...(validationLines.length ? ["## 验证", ...validationLines, ""] : []),
    ...(evidenceLines.length ? ["## 执行证据", ...evidenceLines, ""] : []),
    ...(workerLines.length ? ["## Worker 摘要", ...workerLines, ""] : []),
    "## 证据入口",
    `已记录 ${modelCalls != null ? modelCalls + " 次模型调用" : "若干模型调用"}。完整证据在 Inspector → Evidence Explorer 查看。`,
    "",
    "## 下一步",
    nextRunAction({ status, blocked: blockedTasks.length, decisions: pendingDecisions.length })
  ].join("\n");
}

/** Build final text for review mode — reads review_report.md and eval_report.json */
async function reviewFinalTextForRun(runId, fallbackStdout) {
  const runDir = path.join(workspace, ".asteria", "runs", runId);
  const evalReport = await readJson(path.join(runDir, "eval_report.json"));
  const status = firstRuntimeText(evalReport?.overall?.status, "reviewed");
  const score = evalReport?.overall?.score != null ? Number(evalReport.overall.score).toFixed(2) : null;
  const reason = firstRuntimeText(evalReport?.overall?.reason);
  // Try review_report.md for body
  const reviewMdPath = path.join(runDir, "review_report.md");
  let reviewBody = "";
  if (existsSync(reviewMdPath)) {
    try { reviewBody = (await fs.readFile(reviewMdPath, "utf8")).trim(); } catch {}
  }
  if (reviewBody.length > 80) {
    return [
      `## 评审结果 — ${status}${score ? `（评分 ${score}）` : ""}`,
      reason ? reason : "",
      "",
      reviewBody,
      "",
      "## 下一步",
      nextStepForMode("review")
    ].filter((l, i, arr) => !(l === "" && arr[i - 1] === "")).join("\n");
  }
  return [
    "## 评审结果",
    `Run ${runId} 评审完成（${status}）。${score ? "评分 " + score + "。" : ""}${reason}`,
    "",
    "## 下一步",
    nextStepForMode("review")
  ].join("\n");
}

async function readWorkerSummaryLines(runDir) {
  const workersPath = path.join(runDir, "worker_results.jsonl");
  if (!existsSync(workersPath)) return [];
  try {
    const lines = (await fs.readFile(workersPath, "utf8")).split(/\r?\n/).filter(Boolean);
    return lines.slice(0, 5).map((line) => {
      try {
        const w = JSON.parse(line);
        const id = firstRuntimeText(w.task_id, w.worker_id, "task");
        const st = firstRuntimeText(w.status, "?");
        const note = firstRuntimeText(w.summary, w.result_summary, "");
        return `- ${id}: ${st}${note ? " — " + note.slice(0, 80) : ""}`;
      } catch { return null; }
    }).filter(Boolean);
  } catch { return []; }
}

async function runArtifactLines(runDir) {
  const artifacts = await readJsonlTail(path.join(runDir, "artifacts.jsonl"), 20);
  return artifacts.slice(-8).map((item) => {
    const artifactPath = firstRuntimeText(item.path, item.artifact_id, "artifact");
    const summary = firstRuntimeText(item.summary, item.type, "");
    return `- ${artifactPath}${summary ? `：${summary}` : ""}`;
  });
}

function runAnswerLine({ runId, goal, status, done, total, blocked, decisions }) {
  if (decisions > 0) {
    return `本次目标「${goal}」还没有最终完成。Run ${runId} 已推进到需要人工决策的位置：完成 ${done}/${total} 个任务，当前有 ${blocked} 个阻断和 ${decisions} 个待决策项。`;
  }
  if (blocked > 0 || /blocked|paused|failed/i.test(status)) {
    return `本次目标「${goal}」暂未完成。Run ${runId} 已产出执行证据，但仍有 ${blocked} 个阻断，需要先处理后才能给出完成结论。`;
  }
  return `本次目标「${goal}」已完成。Run ${runId} 完成 ${done}/${total} 个任务，并留下了产物、验证和执行证据。`;
}

function nextRunAction({ status, blocked, decisions }) {
  if (decisions > 0) return "先处理待决策项；通过后继续 resume，让 runtime 接着完成剩余任务。";
  if (blocked > 0 || /blocked|paused|failed/i.test(String(status))) {
    return "先运行 debug 或 replan 处理阻断，再继续 resume。";
  }
  return "可以进入 review 检查产物质量，或基于当前结果继续提出下一轮目标。";
}

function extractRunId(text) {
  return String(text || "").match(/\brun-\d{8}-\d{4}\b/)?.[0] || null;
}

function runArtifactRefs(runId) {
  if (!runId) return [];
  return [
    path.join(workspace, ".asteria", "runs", runId, "goal_spec.json"),
    path.join(workspace, ".asteria", "runs", runId, "task_plan.json"),
    path.join(workspace, ".asteria", "runs", runId, "task_plan_eval.json"),
    path.join(workspace, ".asteria", "runs", runId, "cost_report.json")
  ];
}

function firstRuntimeText(...items) {
  for (const item of items) {
    const text = String(item ?? "").trim();
    if (text) return text;
  }
  return "";
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
  notifySSE(sessionId, full);
  return full;
}

async function readSessionEvents(sessionId) {
  if (!isSafeId(sessionId)) return [];
  const file = sessionPath(sessionId, "events.jsonl");
  if (!existsSync(file)) return [];
  let events = (await fs.readFile(file, "utf8")).split(/\r?\n/).filter(Boolean).map((line) => {
    try {
      return redact(JSON.parse(line));
    } catch {
      return { type: "raw", content_delta: redactText(line) };
    }
  });
  const runIds = new Set();
  for (const event of events) {
    if (event.type !== "final_answer") continue;
    const runId = extractRunId(event.content_delta) || extractRunId((event.artifact_refs || []).join("\n"));
    if (!runId) continue;
    runIds.add(runId);
    const runDir = path.join(workspace, ".asteria", "runs", runId);
    const hasFinalReport = existsSync(path.join(runDir, "final_report.md"));
    const hasEvalReport = existsSync(path.join(runDir, "eval_report.json"));
    const hasGoalSpec = existsSync(path.join(runDir, "goal_spec.json"));
    if (hasFinalReport) {
      event.content_delta = await runFinalTextForRun(runId, event.content_delta);
    } else if (hasEvalReport && !hasGoalSpec) {
      event.content_delta = await reviewFinalTextForRun(runId, event.content_delta);
    } else {
      event.content_delta = await planFinalTextForRun(runId, event.content_delta);
    }
    event.summary = "已从 runtime 产物提炼为用户可读结论。";
    event.artifact_refs = [...(event.artifact_refs || []), ...runArtifactRefs(runId)];
  }
  for (const runId of await activeRuntimeRunIdsForSession(sessionId)) {
    runIds.add(runId);
  }
  if (runIds.size) {
    const runtimeEvents = [];
    for (const runId of runIds) {
      runtimeEvents.push(...(await readRuntimeUserProgressEvents(runId, sessionId)));
    }
    if (runtimeEvents.length) {
      events = mergeSessionAndRuntimeEvents(events, runtimeEvents);
    }
  }
  return events;
}

function rememberJobRunId(jobId, runId) {
  if (!runId) return;
  const job = liveJobs.get(jobId);
  if (!job || job.run_id) return;
  job.run_id = runId;
  liveJobs.set(jobId, job);
}

async function activeRuntimeRunIdsForSession(sessionId) {
  const jobs = [...liveJobs.values()].filter((job) => job.session_id === sessionId && job.status === "running");
  const runIds = [];
  for (const job of jobs) {
    const runId = job.run_id || (await discoverRuntimeRunIdForJob(job));
    if (!runId) continue;
    job.run_id = runId;
    liveJobs.set(job.job_id, job);
    runIds.push(runId);
  }
  return [...new Set(runIds)];
}

async function discoverRuntimeRunIdForJob(job) {
  const runsDir = path.join(workspace, ".asteria", "runs");
  if (!existsSync(runsDir)) return null;
  let entries = [];
  try {
    entries = await fs.readdir(runsDir, { withFileTypes: true });
  } catch {
    return null;
  }
  const candidates = [];
  for (const entry of entries) {
    if (!entry.isDirectory() || !/^run-\d{8}-\d{4}$/.test(entry.name)) continue;
    const runDir = path.join(runsDir, entry.name);
    const progressPath = path.join(runDir, "user_progress.jsonl");
    if (!existsSync(progressPath)) continue;
    let stat;
    try {
      stat = await fs.stat(runDir);
    } catch {
      continue;
    }
    if (stat.mtimeMs + 2500 < Number(job.started_at_ms || 0)) continue;
    candidates.push({ run_id: entry.name, modified_at: stat.mtimeMs });
  }
  candidates.sort((a, b) => b.modified_at - a.modified_at);
  return candidates[0]?.run_id || null;
}

async function readRuntimeUserProgressEvents(runId, sessionId) {
  const file = path.join(workspace, ".asteria", "runs", runId, "user_progress.jsonl");
  const rows = await readJsonlTail(file, 500);
  const events = rows.map((event) => userProgressToStudioEvent(event, sessionId, runId)).filter(Boolean);
  for (const event of events) {
    if (event.type !== "final_answer") continue;
    await enrichFinalAnswerEvent(event, runId);
  }
  return events;
}

async function enrichFinalAnswerEvent(event, runId) {
  const runDir = path.join(workspace, ".asteria", "runs", runId);
  const hasFinalReport = existsSync(path.join(runDir, "final_report.md"));
  const hasEvalReport = existsSync(path.join(runDir, "eval_report.json"));
  const hasGoalSpec = existsSync(path.join(runDir, "goal_spec.json"));
  if (hasFinalReport) {
    event.content_delta = await runFinalTextForRun(runId, event.content_delta);
  } else if (hasEvalReport && !hasGoalSpec) {
    event.content_delta = await reviewFinalTextForRun(runId, event.content_delta);
  } else {
    event.content_delta = await planFinalTextForRun(runId, event.content_delta);
  }
  event.summary = "已从 runtime 产物提炼为用户可读结论。";
  event.artifact_refs = [...(event.artifact_refs || []), ...runArtifactRefs(runId)];
}

function mergeSessionAndRuntimeEvents(sessionEvents, runtimeEvents) {
  const runtimeTypes = new Set(runtimeEvents.map((event) => event.type));
  const replaceable = new Set(["model_start", "model_delta", "model_end", "model_error", "file_changed"]);
  const filteredSessionEvents = sessionEvents.filter((event) => {
    if (!replaceable.has(event.type)) return true;
    return !runtimeTypes.has(event.type);
  });
  return [...filteredSessionEvents, ...runtimeEvents].sort((a, b) =>
    String(a.created_at || "").localeCompare(String(b.created_at || ""))
  );
}

function userProgressToStudioEvent(event, sessionId, runId) {
  const channel = String(event.channel || "");
  const eventType = String(event.event_type || "");
  let type = "reasoning_delta";
  if (channel === "model") {
    if (eventType === "start") type = "model_start";
    else if (eventType === "delta") type = "model_delta";
    else if (eventType === "end") type = "model_end";
    else if (eventType === "error") type = "model_error";
  } else if (channel === "tool") {
    if (eventType === "tool_call") type = "tool_start";
    else if (eventType === "tool_output") type = "tool_end";
    else if (eventType === "error") type = "error";
    else type = "tool_delta";
  } else if (channel === "file") {
    type = "file_changed";
  } else if (channel === "conclusion") {
    type = event.phase === "result" ? "final_answer" : "assistant_delta";
  } else if (channel === "diagnostic") {
    type = "tool_delta";
  }
  return redact({
    schema_version: "0.1.0",
    event_id: `runtime-${runId}-${event.event_id}`,
    session_id: sessionId,
    type,
    status: event.status,
    title: event.title,
    summary: event.summary,
    content_delta: event.content_delta || "",
    command: event.command || [],
    artifact_refs: event.artifact_refs || [],
    evidence_refs: [...(event.evidence_refs || []), `.asteria/runs/${runId}/user_progress.jsonl`],
    model_provider: event.model_provider,
    model_name: event.model_name,
    telemetry: event.telemetry || {},
    phase: event.phase,
    display_level: event.display_level,
    created_at: event.created_at,
    source: "runtime_user_progress",
    runtime_channel: channel,
    runtime_event_type: eventType,
    file_changes: event.file_changes || [],
    run_id: runId
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

async function readRunDetail(runId) {
  if (!isSafeId(runId)) return { ok: false, error: "invalid run id" };
  const runsDir = path.join(workspace, ".asteria", "runs");
  const runDir = path.resolve(runsDir, runId);
  if (!runDir.startsWith(runsDir) || !existsSync(runDir)) return { ok: false, error: "run not found" };
  const jsonFiles = {
    run: "run.json",
    cost_report: "cost_report.json",
    goal_spec: "goal_spec.json",
    task_plan: "task_plan.json",
    task_plan_eval: "task_plan_eval.json",
    agent_run_graph: "agent_run_graph.json"
  };
  const payload = { ok: true, run_id: runId };
  for (const [key, file] of Object.entries(jsonFiles)) {
    payload[key] = redact(await readJson(path.join(runDir, file)));
  }
  payload.model_calls = redact(await readJsonlTail(path.join(runDir, "model_calls.jsonl"), 120));
  payload.task_execution_evidence = redact(await readJsonlTail(path.join(runDir, "task_execution_evidence.jsonl"), 80));
  payload.worker_results = redact(await readJsonlTail(path.join(runDir, "worker_results.jsonl"), 80));
  payload.validation_results = redact(await readJsonlTail(path.join(runDir, "validation_results.jsonl"), 80));
  payload.events = redact(await readJsonlTail(path.join(runDir, "events.jsonl"), 120));
  payload.user_progress = redact(await readJsonlTail(path.join(runDir, "user_progress.jsonl"), 120));
  payload.files = await listRunEvidenceFiles(runDir, runId);
  return redact(payload);
}

async function listRunEvidenceFiles(runDir, runId) {
  let entries = [];
  try {
    entries = await fs.readdir(runDir, { withFileTypes: true });
  } catch {
    return [];
  }
  const files = [];
  for (const entry of entries) {
    if (!entry.isFile()) continue;
    const relative = `.asteria/runs/${runId}/${entry.name}`;
    if (!isSafeWorkspacePath(relative) || !isPreviewableFile(relative)) continue;
    const stat = await fs.stat(path.join(runDir, entry.name));
    files.push({ path: relative, size: stat.size, modified_at: stat.mtime.toISOString() });
  }
  return files.sort((a, b) => String(a.path).localeCompare(String(b.path)));
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
