import { spawn } from "node:child_process";
import { createServer, request as httpRequest } from "node:http";
import { existsSync, statSync, readFileSync, watch as fsWatch, promises as fs } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { outcomeAnswerContract } from "./prompt-contract.mjs";
import {
  classifyChatRequest,
  hasAny,
  intentAuditFor,
  isRuntimeMetaQuestion,
  routeUserIntent,
} from "./intent-router.mjs";
import {
  buildRouteMessageWithChatContext,
  recentChatHistoryMessages,
} from "./lib/chat-route-context.mjs";
import { buildOrchestrationWorkflowMonitor } from "./lib/orchestration-workflow-monitor.mjs";
import { RuntimeRouteClient } from "./lib/runtime-route-client.mjs";
import { mapPermissionLevel, withPermissionLevel } from "./lib/permission-level.mjs";
import { redact, redactText, tailText, percentile } from "./lib/text-utils.mjs";
import { createGitHelpers } from "./lib/git.mjs";
import {
  friendlyErrorText,
  friendlyErrorCategory,
  friendlyErrorTitle,
  friendlyErrorSummary,
  summarizeRuntimeChunk,
} from "./lib/friendly-error.mjs";
import {
  isSafeId,
  isSafeWorkspacePath,
  isPreviewableFile,
  workspaceBasename,
  isAbsoluteWorkspacePath,
} from "./lib/workspace-paths.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "..");
const args = parseArgs(process.argv.slice(2));
let workspace = path.resolve(args.workspace || repoRoot);
let runtimeRoot = path.resolve(args.runtimeRoot || repoRoot);
const port = Number(args.port || process.env.ASTERIA_STUDIO_PORT || 8787);
const python = args.python || process.env.ASTERIA_PYTHON || "python";
const chatBackend = String(
  args.chatBackend || process.env.ASTERIA_STUDIO_CHAT_BACKEND || "model",
).toLowerCase();
const moduleName = process.env.ASTERIA_MODULE || "asteria_runtime";
const routeClient = new RuntimeRouteClient({ python, runtimeRoot, moduleName });
const distDir = path.join(__dirname, "dist");
const liveJobs = new Map();
// Git helpers live in ./lib/git.mjs; wire them with a live workspace getter (the active
// workspace is reassigned on switch) + the protected-path-aware safety guard.
const {
  readWorkspaceGitStatus,
  readWorkspaceGitDiff,
  stageWorkspaceGitFile,
  discardWorkspaceGitFile,
} = createGitHelpers({ getWorkspace: () => workspace, runCommand });
let previewPort = null; // PREVIEW-1: port of the dedicated static workspace server (null until bound)
const previewSseClients = new Set(); // PREVIEW-2: live-reload SSE connections from preview iframes
let previewReloadTimer = null;
// PREVIEW-3: opt-in reverse proxy to a running dev server (Vite/Next/CRA/etc.) so SPA/framework apps
// — which need a bundler, not static files — can be previewed. OPT-IN only (an explicit target),
// never an auto-probe of arbitrary localhost ports, which would risk proxying an unrelated app.
const previewProxyTarget = normalizeProxyTarget(
  args.previewProxy || process.env.ASTERIA_PREVIEW_PROXY,
);

// Accept a full URL ("http://127.0.0.1:5173"), host:port ("localhost:3000"), or a bare port ("5173",
// → 127.0.0.1:5173). Only http is proxied (local dev servers are http); returns null when unset/invalid.
function normalizeProxyTarget(value) {
  const raw = String(value || "").trim();
  if (!raw) return null;
  if (/^\d+$/.test(raw)) return normalizeProxyTarget(`http://127.0.0.1:${raw}`);
  try {
    const url = new URL(/^https?:\/\//i.test(raw) ? raw : `http://${raw}`);
    if (url.protocol !== "http:") return null;
    const targetPort = url.port || "80";
    return {
      hostname: url.hostname,
      port: targetPort,
      origin: `http://${url.hostname}:${targetPort}`,
    };
  } catch {
    return null;
  }
}

// Keep liveJobs bounded. Terminal (completed/failed/cancelled) jobs are retained briefly so the
// jobs/stop routes still reflect a just-finished run, then pruned after a grace window; a hard cap is
// a backstop. Running jobs are never pruned. Prevents a long-lived server from growing the map
// unbounded and keeps the workspace-switch guard (which scans liveJobs) honest.
function pruneLiveJobs(maxAgeMs = 10 * 60 * 1000, keepLatest = 50) {
  const now = Date.now();
  for (const [id, job] of liveJobs) {
    const terminal =
      job.status === "completed" || job.status === "failed" || job.status === "cancelled";
    if (terminal && now - (job.started_at_ms || 0) > maxAgeMs) liveJobs.delete(id);
  }
  if (liveJobs.size > keepLatest) {
    const terminalIds = [...liveJobs.entries()]
      .filter(([, job]) => job.status !== "running")
      .map(([id]) => id);
    for (const id of terminalIds.slice(0, liveJobs.size - keepLatest)) liveJobs.delete(id);
  }
}

const pendingJobs = new Map(); // jobId -> { sessionId, mode, goal, command }
const sseClients = new Map(); // sessionId -> Set<response>

function notifySSE(sessionId, event) {
  const clients = sseClients.get(sessionId);
  if (!clients?.size) return;
  const payload = `data: ${JSON.stringify(event)}\n\n`;
  for (const res of [...clients]) {
    try {
      res.write(payload);
    } catch {
      clients.delete(res);
    }
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
  startPreviewServer(port + 1);
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
  if (request.method === "POST" && url.pathname === "/api/studio/sessions/import") {
    const raw = await readRequestBodyRaw(request);
    if (raw === null) {
      sendJson(response, 413, { ok: false, error: "bundle too large" });
      return;
    }
    let body = null;
    try {
      body = raw ? JSON.parse(raw) : null;
    } catch {
      body = null;
    }
    if (!body) {
      sendJson(response, 400, { ok: false, error: "invalid bundle JSON" });
      return;
    }
    sendJson(response, 200, await importSessionBundle(body));
    return;
  }
  if (request.method === "GET" && url.pathname.match(/^\/api\/studio\/sessions\/[^/]+\/export$/)) {
    const sessionId = decodeURIComponent(url.pathname.split("/").at(-2) || "");
    const result = await exportSessionBundle(sessionId);
    if (!result.ok) {
      sendJson(response, 404, result);
      return;
    }
    const filename = `asteria-session-${result.session_id}.json`.replace(/[^a-zA-Z0-9._-]/g, "_");
    response.writeHead(200, {
      "content-type": "application/json; charset=utf-8",
      "content-disposition": `attachment; filename="${filename}"`,
    });
    response.end(JSON.stringify(result.bundle, null, 2));
    return;
  }
  if (request.method === "PATCH" && url.pathname.match(/^\/api\/studio\/sessions\/[^/]+$/)) {
    const sessionId = decodeURIComponent(url.pathname.split("/").pop() || "");
    sendJson(response, 200, await updateSession(sessionId, await readRequestJson(request)));
    return;
  }
  if (request.method === "DELETE" && url.pathname.match(/^\/api\/studio\/sessions\/[^/]+$/)) {
    const sessionId = decodeURIComponent(url.pathname.split("/").pop() || "");
    const purge = url.searchParams.get("purge") === "1";
    sendJson(response, 200, await deleteSession(sessionId, { purge }));
    return;
  }
  if (
    request.method === "POST" &&
    url.pathname.match(/^\/api\/studio\/sessions\/[^/]+\/restore$/)
  ) {
    const sessionId = decodeURIComponent(url.pathname.split("/").at(-2) || "");
    sendJson(response, 200, await restoreSession(sessionId));
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
  if (
    request.method === "GET" &&
    url.pathname.match(/^\/api\/studio\/sessions\/[^/]+\/events\/stream$/)
  ) {
    const sessionId = decodeURIComponent(url.pathname.split("/").at(-3) || "");
    if (!isSafeId(sessionId)) {
      sendJson(response, 400, { ok: false, error: "invalid session id" });
      return;
    }
    response.writeHead(200, {
      "Content-Type": "text/event-stream; charset=utf-8",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
      "X-Accel-Buffering": "no",
    });
    response.write(": connected\n\n");
    const existingEvents = await readSessionEvents(sessionId);
    for (const event of existingEvents) {
      response.write(`data: ${JSON.stringify(event)}\n\n`);
    }
    if (!sseClients.has(sessionId)) sseClients.set(sessionId, new Set());
    sseClients.get(sessionId).add(response);
    const ping = setInterval(() => {
      try {
        response.write(": ping\n\n");
      } catch {}
    }, 15000);
    request.on("close", () => {
      clearInterval(ping);
      sseClients.get(sessionId)?.delete(response);
    });
    return;
  }
  if (request.method === "GET" && url.pathname.match(/^\/api\/studio\/sessions\/[^/]+\/jobs$/)) {
    const sessionId = decodeURIComponent(url.pathname.split("/").at(-2) || "");
    sendJson(response, 200, sessionJobsPayload(sessionId));
    return;
  }
  if (request.method === "POST" && url.pathname.match(/^\/api\/studio\/sessions\/[^/]+\/stop$/)) {
    const sessionId = decodeURIComponent(url.pathname.split("/").at(-2) || "");
    sendJson(response, 200, stopSessionJobs(sessionId));
    return;
  }
  if (
    request.method === "POST" &&
    url.pathname.match(/^\/api\/studio\/sessions\/[^/]+\/messages$/)
  ) {
    const sessionId = decodeURIComponent(url.pathname.split("/").at(-2) || "");
    sendJson(response, 200, await submitUserGoal(sessionId, await readRequestJson(request)));
    return;
  }
  if (
    request.method === "POST" &&
    url.pathname.match(/^\/api\/studio\/sessions\/[^/]+\/runtime-actions$/)
  ) {
    const sessionId = decodeURIComponent(url.pathname.split("/").at(-2) || "");
    sendJson(response, 200, await handleRuntimeAction(sessionId, await readRequestJson(request)));
    return;
  }
  if (
    request.method === "POST" &&
    url.pathname.match(/^\/api\/studio\/sessions\/[^/]+\/decisions\/resolve$/)
  ) {
    const sessionId = decodeURIComponent(url.pathname.split("/").at(-3) || "");
    sendJson(response, 200, await handleDecisionResolve(sessionId, await readRequestJson(request)));
    return;
  }
  if (
    request.method === "POST" &&
    url.pathname.match(/^\/api\/studio\/sessions\/[^/]+\/decisions\/answer$/)
  ) {
    const sessionId = decodeURIComponent(url.pathname.split("/").at(-3) || "");
    sendJson(response, 200, await handleDecisionAnswer(sessionId, await readRequestJson(request)));
    return;
  }
  if (
    request.method === "PATCH" &&
    url.pathname.match(/^\/api\/studio\/sessions\/[^/]+\/jobs\/[^/]+\/permission$/)
  ) {
    const parts = url.pathname.split("/");
    // /api/studio/sessions/SESSION_ID/jobs/JOB_ID/permission
    const sessionId = decodeURIComponent(parts.at(-4) || "");
    const jobId = decodeURIComponent(parts.at(-2) || "");
    sendJson(
      response,
      200,
      await handlePermission(sessionId, jobId, await readRequestJson(request)),
    );
    return;
  }
  if (request.method === "GET" && url.pathname === "/api/studio/preview-info") {
    // PREVIEW-1: the dedicated static preview server's port, so the Preview tab can point its iframe
    // at http://<host>:<port>/<file> for real multi-file rendering. null if the server didn't bind.
    // PREVIEW-3: mode tells the Preview tab whether it is serving static workspace files or reverse-
    // proxying a running dev server (SPA/framework), plus the proxied origin for a status line.
    sendJson(response, 200, {
      ok: previewPort != null,
      port: previewPort,
      mode: previewProxyTarget ? "proxy" : "static",
      target: previewProxyTarget?.origin ?? null,
    });
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
  if (request.method === "GET" && url.pathname === "/api/studio/workspaces") {
    sendJson(response, 200, await listWorkspaceRegistry());
    return;
  }
  if (request.method === "POST" && url.pathname === "/api/studio/workspace/open") {
    sendJson(response, 200, await openWorkspace(await readRequestJson(request)));
    return;
  }
  if (request.method === "POST" && url.pathname === "/api/studio/workspace/browse") {
    sendJson(response, 200, await browseWorkspaceFolder());
    return;
  }
  if (request.method === "GET" && url.pathname === "/api/studio/workspace/profile") {
    sendJson(
      response,
      200,
      await describeWorkspaceProfile(url.searchParams.get("path") || workspace),
    );
    return;
  }
  if (request.method === "GET" && url.pathname === "/api/studio/git/status") {
    sendJson(response, 200, await readWorkspaceGitStatus());
    return;
  }
  if (request.method === "GET" && url.pathname === "/api/studio/git/diff") {
    sendJson(
      response,
      200,
      await readWorkspaceGitDiff(
        url.searchParams.get("path") || "",
        url.searchParams.get("stage") || "all",
      ),
    );
    return;
  }
  if (request.method === "POST" && url.pathname === "/api/studio/git/stage") {
    sendJson(response, 200, await stageWorkspaceGitFile(await readRequestJson(request)));
    return;
  }
  if (request.method === "POST" && url.pathname === "/api/studio/git/discard") {
    sendJson(response, 200, await discardWorkspaceGitFile(await readRequestJson(request)));
    return;
  }
  if (request.method === "GET" && url.pathname === "/api/studio/settings") {
    sendJson(response, 200, { ok: true, settings: await buildSettingsPayload() });
    return;
  }
  if (request.method === "POST" && url.pathname === "/api/studio/settings") {
    const body = await readRequestJson(request);
    const mode = String(body?.permissionMode || "");
    if (!PERMISSION_TIER_IDS.includes(mode)) {
      sendJson(response, 400, { ok: false, error: "invalid permissionMode" });
      return;
    }
    await saveStudioSettings({ permissionMode: mode });
    sendJson(response, 200, { ok: true, settings: await buildSettingsPayload() });
    return;
  }
  if (request.method === "GET" && url.pathname === "/api/overview") {
    sendJson(response, 200, await overview());
    return;
  }
  if (request.method === "GET" && url.pathname === "/api/diagnostics") {
    sendJson(response, 200, await diagnostics());
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
  const activeSessionId = resolvedSessionId(session, sessionId);
  const goal = redactText(String(body?.message || "")).trim();
  const channel = String(body?.channel || "").toLowerCase();
  const requestedMode = String(body?.mode || "auto");
  const permission = String(body?.permission || "ask");
  const permissionMode = String(body?.permissionMode || "reviewed_auto");
  if (!goal) return { ok: false, error: "message is required" };

  if (channel === "side") {
    const route = {
      mode: "chat",
      source: "side",
      permission: "read_only",
      confidence: "explicit",
      intent_kind: "side_ask",
      reason: "Side chat keeps questions off the main thread.",
    };
    return handleChatMode(activeSessionId, goal, route, null, "side");
  }

  const route = routeUserIntent(goal, requestedMode, permission);
  const audit = intentAuditFor(goal, requestedMode, permission, route);
  let mode = route.mode;
  let executionRoute = null;

  const sessionEvents = await readSessionEvents(activeSessionId);
  const routeMessage = buildRouteMessageWithChatContext(sessionEvents, goal);
  const chatHandoff = routeMessage !== goal;
  const orchestrated = await resolveStudioOrchestrationRoute(routeMessage, requestedMode);
  // Orchestration only refines execution routing (resume in-progress / continue a
  // warm session / a real runtime-router capability). Its cold "rules_fallback"
  // default carries no signal, so it must NOT override the base intent — otherwise
  // every conversational (chat) or plan-first message in a fresh workspace gets
  // clobbered into a runtime run. Honor orchestration only when it brings a signal.
  if (orchestrated && orchestrationHasRouteSignal(orchestrated)) {
    mode = orchestrated.mode;
    executionRoute = orchestrated;
    route.mode = mode;
    route.reason = orchestrated.reason || route.reason;
    route.source = orchestrated.source || route.source;
    route.capability_id = orchestrated.capability_id || null;
    if (chatHandoff) {
      route.chat_execute_handoff = true;
      route.reason = orchestrated.reason
        ? `${orchestrated.reason} (re-routed with recent chat context)`
        : "Strong route re-evaluated after recent chat context.";
    }
  }

  if (route.reason) {
    await appendEvent(activeSessionId, {
      type: "intent_route",
      status: "completed",
      title: "Intent routing",
      summary: route.reason,
      phase: "route",
      display_level: "inspector",
      content_delta: "",
      intent_route: route,
      intent_audit: audit,
    });
  }

  // Chat mode stays conversational by default, but auto-routing may hand off task-like input to plan/run.
  if (mode === "chat") {
    return handleChatMode(activeSessionId, goal, route, audit);
  }

  await appendEvent(activeSessionId, {
    type: "user_message",
    status: "completed",
    title: "User",
    summary: goal,
    content_delta: goal,
  });
  // A canned "I'll handle this: <goal>" acknowledgement is machinery, not the agent-loop's output —
  // it just repeats the user's goal back. Keep it for the Inspector, but the main thread shows only
  // the user's real input and the loop's real output (plan, steps, deliverable, recap).
  await appendEvent(activeSessionId, {
    type: "assistant_delta",
    status: "completed",
    title: "Understanding goal",
    summary: "Received the goal and selected the next controlled step.",
    content_delta: acknowledgementFor(mode, goal),
    phase: "understand",
    display_level: "inspector",
    intent_audit: audit,
  });
  await appendEvent(activeSessionId, progressEventForMode(mode, goal));

  // Best experience by default: the chosen tier decides how autonomous the loop is. Default tiers
  // self-heal (auto repair/replan); "Ask first" stays supervised. Applied to the workspace policy
  // the run is about to read (before the command is built), never the shared template.
  await applyAutonomyForTier(permissionMode);

  // Thread the user's chosen tier through to the runtime (it otherwise runs at the CLI default).
  // The same command is used for both the confirm-card (pending) and direct-start paths below.
  const command = withPermissionLevel(
    executionRoute?.command || runtimeCommand(mode, goal),
    mapPermissionLevel(permissionMode),
  );

  if (mode !== "plan" && permission !== "allow") {
    const permissionPreview = permissionPreviewForMode(mode);
    const pendingJobId = `pending-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`;
    pendingJobs.set(pendingJobId, { sessionId: activeSessionId, mode, goal, command });
    await appendEvent(activeSessionId, {
      type: "permission_request",
      status: "waiting_user",
      title: "Approval needed",
      summary:
        "This may modify files or run local operations. Confirm to continue; cancel makes no changes.",
      command,
      data: { permission_preview: permissionPreview },
      job_id: pendingJobId,
      content_delta: "Confirm to start. Cancel and nothing runs.",
    });
    return {
      ok: true,
      session: { ...session, session_id: activeSessionId },
      started: false,
      needs_permission: true,
      job_id: pendingJobId,
    };
  }

  startRuntimeJob(activeSessionId, mode, goal, command);
  return {
    ok: true,
    session: { ...session, session_id: activeSessionId },
    started: true,
    execution_route: executionRoute?.route || "direct",
  };
}

async function handleRuntimeAction(sessionId, body) {
  const session = await ensureSession(sessionId);
  const activeSessionId = resolvedSessionId(session, sessionId);
  const permission = String(body?.permission || "ask");
  const action = runtimeActionFor(body?.next_action ?? body?.next_command ?? body?.action);
  if (!action) return { ok: false, error: "unsupported runtime action" };

  await appendEvent(activeSessionId, {
    type: "assistant_delta",
    status: "completed",
    title: "Next step selected",
    summary: `${action.label} selected from current progress.`,
    phase: "next",
    display_level: "main",
    content_delta: action.summary,
  });
  await appendEvent(activeSessionId, progressEventForMode(action.mode, action.goal));

  if (action.requiresPermission && permission !== "allow") {
    const pendingJobId = `pending-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`;
    pendingJobs.set(pendingJobId, {
      sessionId: activeSessionId,
      mode: action.mode,
      goal: action.goal,
      command: action.command,
    });
    await appendEvent(activeSessionId, {
      type: "permission_request",
      status: "waiting_user",
      title: "Approval needed",
      summary: action.permissionSummary,
      command: action.command,
      data: { permission_preview: action.permissionPreview },
      job_id: pendingJobId,
      content_delta: "Confirm to start. Cancel and nothing runs.",
    });
    return {
      ok: true,
      session: { ...session, session_id: activeSessionId },
      started: false,
      needs_permission: true,
      job_id: pendingJobId,
      action: action.kind,
    };
  }

  startRuntimeJob(activeSessionId, action.mode, action.goal, action.command);
  return {
    ok: true,
    session: { ...session, session_id: activeSessionId },
    started: true,
    action: action.kind,
  };
}

async function handleDecisionResolve(sessionId, body) {
  const session = await ensureSession(sessionId);
  const activeSessionId = resolvedSessionId(session, sessionId);
  const runId = String(body?.run_id || "").trim();
  const decisionId = String(body?.decision_id || "").trim();
  const optionId = String(body?.option_id || "").trim();
  if (!isSafeId(runId) || !isSafeId(decisionId) || !isSafeDecisionOptionId(optionId)) {
    return { ok: false, error: "invalid decision selection" };
  }
  const runDir = path.join(workspace, ".asteria", "runs", runId);
  const decisions = latestDecisions(await readJsonlTail(path.join(runDir, "decisions.jsonl"), 200));
  const decision = decisions.find((item) => String(item.decision_id || "") === decisionId);
  if (!decision || decision.status !== "pending")
    return { ok: false, error: "decision is not pending" };
  const options = Array.isArray(decision.options) ? decision.options : [];
  if (!options.some((option) => String(option.option_id || "") === optionId)) {
    return { ok: false, error: "option not found" };
  }
  const option = options.find((item) => String(item.option_id || "") === optionId) || {};
  await appendEvent(activeSessionId, {
    type: "user_message",
    status: "completed",
    title: "Decision",
    summary: `${decisionId}: ${String(option.label || optionId)}`,
    content_delta: `Selected ${String(option.label || optionId)} for ${String(decision.question || decisionId)}.`,
    phase: "decision",
    display_level: "main",
  });
  await appendEvent(
    activeSessionId,
    progressEventForMode("decide", String(decision.question || decisionId)),
  );
  const command = [
    python,
    "-m",
    moduleName,
    "decide",
    "--root",
    workspace,
    "--session-id",
    runId,
    "--decision-id",
    decisionId,
    "--select-option-id",
    optionId,
  ];
  const metadata =
    decision.metadata && typeof decision.metadata === "object" ? decision.metadata : {};
  const followUpMode =
    (metadata.kind === "runtime_request" && optionId === "review_contract") ||
    (metadata.kind === "replan_decision" && optionId === "create_repair_task")
      ? "resume"
      : null;
  startRuntimeJob(activeSessionId, "decide", `Resolve ${decisionId}.`, command, { followUpMode });
  return {
    ok: true,
    session: { ...session, session_id: activeSessionId },
    started: true,
    decision_id: decisionId,
    option_id: optionId,
    follow_up_mode: followUpMode,
  };
}

// Open-ended ask: the model paused the loop with a free-text question (options empty,
// metadata.kind === "open_question"). The user answers in prose; we record the answer and
// resume the SAME loop so it continues with the answer folded in as guidance — Claude Code's
// "ask", not a review gate. The answer is genuine user-typed content, so it shows in the thread.
async function handleDecisionAnswer(sessionId, body) {
  const session = await ensureSession(sessionId);
  const activeSessionId = resolvedSessionId(session, sessionId);
  const runId = String(body?.run_id || "").trim();
  const decisionId = String(body?.decision_id || "").trim();
  const answer = redactText(String(body?.answer || "")).trim();
  if (!isSafeId(runId) || !isSafeId(decisionId)) {
    return { ok: false, error: "invalid decision reference" };
  }
  if (!answer) return { ok: false, error: "answer is required" };
  if (answer.length > 4000) return { ok: false, error: "answer is too long" };
  const runDir = path.join(workspace, ".asteria", "runs", runId);
  const decisions = latestDecisions(await readJsonlTail(path.join(runDir, "decisions.jsonl"), 200));
  const decision = decisions.find((item) => String(item.decision_id || "") === decisionId);
  if (!decision || decision.status !== "pending")
    return { ok: false, error: "decision is not pending" };
  const metadata =
    decision.metadata && typeof decision.metadata === "object" ? decision.metadata : {};
  if (metadata.kind !== "open_question")
    return { ok: false, error: "decision is not an open question" };
  await appendEvent(activeSessionId, {
    type: "user_message",
    status: "completed",
    title: "Answer",
    summary: answer,
    content_delta: answer,
    phase: "decision",
    display_level: "main",
  });
  await appendEvent(
    activeSessionId,
    progressEventForMode("decide", String(decision.question || decisionId)),
  );
  const command = [
    python,
    "-m",
    moduleName,
    "decide",
    "--root",
    workspace,
    "--session-id",
    runId,
    "--decision-id",
    decisionId,
    "--answer",
    answer,
  ];
  // Resume right after recording the answer so the loop continues with it as guidance.
  startRuntimeJob(activeSessionId, "decide", `Answer ${decisionId}.`, command, {
    followUpMode: "resume",
  });
  return {
    ok: true,
    session: { ...session, session_id: activeSessionId },
    started: true,
    decision_id: decisionId,
  };
}

function isSafeDecisionOptionId(value) {
  return /^[A-Za-z0-9_.:-]{1,120}$/.test(String(value || ""));
}

function latestDecisions(decisions) {
  const byId = new Map();
  const anonymous = [];
  for (const decision of decisions || []) {
    const decisionId = String(decision?.decision_id || "").trim();
    if (!decisionId) {
      anonymous.push(decision);
      continue;
    }
    byId.set(decisionId, decision);
  }
  return [...anonymous, ...byId.values()];
}

function runtimeActionFor(value) {
  const raw = String(value || "")
    .trim()
    .toLowerCase();
  if (!raw) return null;
  const normalized = raw
    .replace(/^asteria\s+/, "")
    .replace(/^python\s+-m\s+\S+\s+/, "")
    .replace(/\s+--latest\b/g, "")
    .trim();
  const first = normalized.split(/\s+/)[0];
  const kind = {
    review: "review",
    accept: "accept",
    resume: "continue",
    continue: "continue",
    run: "continue",
    replan: "continue",
    debug: "debug",
    repair: "debug",
    decide: "decide",
    compact: "compact",
  }[first];
  if (!kind) return null;
  return runtimeActionByKind(kind);
}

function runtimeActionByKind(kind) {
  const actions = {
    review: {
      kind: "review",
      label: "Review",
      mode: "review",
      goal: "Review the latest runtime result.",
      command: [python, "-m", moduleName, "review", "--root", workspace],
      requiresPermission: false,
      summary: "I will review the latest result and show the outcome.",
      permissionSummary: "",
    },
    accept: {
      kind: "accept",
      label: "Accept",
      mode: "accept",
      goal: "Accept the latest reviewed result.",
      command: [python, "-m", moduleName, "accept", "--root", workspace],
      requiresPermission: true,
      summary: "I will accept the verified result after confirmation.",
      permissionSummary:
        "\u63a5\u53d7\u7ed3\u679c\u4f1a\u66f4\u65b0\u5f53\u524d runtime \u72b6\u6001\u3002\u8bf7\u786e\u8ba4\u662f\u5426\u7ee7\u7eed\u3002",
      permissionPreview: permissionPreview({
        action: "Accept the reviewed result",
        impact: "Finalize the reviewed runtime result.",
        scope: "Current runtime state",
        network: "No network access requested.",
        risk: "low",
        reversible: "Review changes before continuing.",
      }),
    },
    continue: {
      kind: "continue",
      label: "Continue",
      mode: "resume",
      goal: "Continue the current runtime goal.",
      command: [
        python,
        "-m",
        moduleName,
        "resume",
        "--root",
        workspace,
        "--max-iterations",
        "8",
        "--max-tasks-per-iteration",
        "1",
      ],
      requiresPermission: true,
      summary: "I will continue the current goal after confirmation.",
      permissionSummary:
        "\u7ee7\u7eed\u63a8\u8fdb\u53ef\u80fd\u4f1a\u4fee\u6539\u6587\u4ef6\u6216\u8fd0\u884c\u672c\u5730\u64cd\u4f5c\u3002\u8bf7\u786e\u8ba4\u662f\u5426\u7ee7\u7eed\u3002",
      permissionPreview: permissionPreview({
        action: "Continue the current goal",
        impact: "May edit workspace files and run local verification.",
        scope: "Current workspace",
        network: "Model provider may be contacted; external tools still require separate approval.",
        risk: "medium",
        reversible: "Changes remain reviewable before acceptance.",
      }),
    },
    debug: {
      kind: "debug",
      label: "Debug",
      mode: "debug",
      goal: "Diagnose and repair the latest blocked runtime step.",
      command: [python, "-m", moduleName, "debug", "--root", workspace],
      requiresPermission: true,
      summary: "I will diagnose the blocked step and prepare a repair path after confirmation.",
      permissionSummary:
        "\u8c03\u8bd5\u4fee\u590d\u53ef\u80fd\u4f1a\u8bfb\u53d6\u8fd0\u884c\u8bc1\u636e\u5e76\u4fee\u6539\u6587\u4ef6\u3002\u8bf7\u786e\u8ba4\u662f\u5426\u7ee7\u7eed\u3002",
      permissionPreview: permissionPreview({
        action: "Diagnose and repair the blocked step",
        impact: "Read failure evidence and may edit workspace files.",
        scope: "Current workspace and run evidence",
        network: "Model provider may be contacted; external tools still require separate approval.",
        risk: "medium",
        reversible: "Repairs remain reviewable before acceptance.",
      }),
    },
    decide: {
      kind: "decide",
      label: "Decide",
      mode: "decide",
      goal: "List pending decisions for the current runtime goal.",
      command: [python, "-m", moduleName, "decide", "--root", workspace, "--list-pending"],
      requiresPermission: false,
      summary: "I will list the decisions that need your input.",
      permissionSummary: "",
    },
    compact: {
      kind: "compact",
      label: "Compact",
      mode: "compact",
      goal: "Compact session context to free space.",
      command: [python, "-m", moduleName, "compact", "--root", workspace],
      requiresPermission: true,
      summary: "I will compact the current session context after confirmation.",
      permissionSummary: "Compacting context may summarize older turns. Confirm to continue.",
      permissionPreview: permissionPreview({
        action: "Compact session context",
        impact: "Summarize older conversation turns to free context space.",
        scope: "Current session context",
        network: "No network access requested.",
        risk: "low",
        reversible: "Workspace files are not changed.",
      }),
    },
  };
  return actions[kind] ?? null;
}

function permissionPreviewForMode(mode) {
  const normalized = String(mode || "").toLowerCase();
  if (normalized === "review") {
    return permissionPreview({
      action: "Review the current result",
      impact: "Read project changes and verification evidence.",
      scope: "Current workspace, read-only",
      network: "No network access requested.",
      risk: "low",
      reversible: "No files will be changed.",
    });
  }
  return permissionPreview({
    action:
      normalized === "resume" || normalized === "continue"
        ? "Continue the current goal"
        : "Start working on this goal",
    impact: "May edit workspace files and run local verification.",
    scope: "Current workspace",
    network: "Model provider may be contacted; external tools still require separate approval.",
    risk: "medium",
    reversible: "Changes remain reviewable before acceptance.",
  });
}

function permissionPreview({ action, impact, scope, network, risk, reversible, scope_detail }) {
  return {
    action,
    impact,
    scope,
    network,
    risk,
    reversible,
    ...(scope_detail ? { scope_detail } : {}),
  };
}

// Chat mode: instant local answer, zero CLI overhead

function acknowledgementFor(mode, goal) {
  if (mode === "plan")
    return `\u6211\u4f1a\u5148\u7ed9\u4f60\u6574\u7406\u4e00\u4efd\u53ea\u8bfb\u8ba1\u5212\uff1a${goal}`;
  if (mode === "run")
    return `\u6211\u4f1a\u6309\u53d7\u63a7\u6d41\u7a0b\u5904\u7406\u8fd9\u4e2a\u76ee\u6807\uff1a${goal}`;
  if (mode === "continue")
    return `\u6211\u4f1a\u5728\u5f53\u524d session \u5185\u7ee7\u7eed\u63a8\u8fdb\uff08\u8df3\u8fc7\u91cd\u65b0 plan\uff09\uff1a${goal}`;
  if (mode === "orchestration")
    return `\u6211\u4f1a\u6309 L3 workflow manifest \u6267\u884c\u591a\u9636\u6bb5\u7f16\u6392\uff08\u72b6\u6001\u843d\u5728 runner JSONL\uff09\uff1a${goal}`;
  if (mode === "review")
    return `\u6211\u4f1a\u68c0\u67e5\u5f53\u524d\u7ed3\u679c\uff0c\u5e76\u7528\u4f60\u80fd\u76f4\u63a5\u5224\u65ad\u7684\u65b9\u5f0f\u603b\u7ed3\uff1a${goal}`;
  if (mode === "resume")
    return `\u6211\u4f1a\u7ee7\u7eed\u63a8\u8fdb\u5f53\u524d\u4efb\u52a1\uff1a${goal}`;
  return `\u6211\u5df2\u6536\u5230\u4f60\u7684\u8bf7\u6c42\uff1a${goal}`;
}

function progressEventForMode(mode, goal) {
  const labels = {
    plan: [
      "Planning",
      "\u6b63\u5728\u6574\u7406\u53ea\u8bfb\u8ba1\u5212\uff0c\u4e0d\u4f1a\u4fee\u6539\u4f60\u7684\u6587\u4ef6\u3002",
    ],
    run: ["Starting", "\u6b63\u5728\u5f00\u59cb\u53d7\u63a7\u5904\u7406\u3002"],
    continue: [
      "Continuing",
      "\u6b63\u5728\u5f53\u524d session \u5185\u7ee7\u7eed\u6267\u884c\u3002",
    ],
    orchestration: [
      "Orchestrating",
      "\u6b63\u5728\u6267\u884c L3 workflow manifest\uff08runner JSONL \u53ef\u89c2\u5bdf\uff09\u3002",
    ],
    review: [
      "Reviewing",
      "\u6b63\u5728\u68c0\u67e5\u7ed3\u679c\u5e76\u51c6\u5907\u603b\u7ed3\u3002",
    ],
    resume: ["Resuming", "\u6b63\u5728\u7ee7\u7eed\u63a8\u8fdb\u5f53\u524d\u4efb\u52a1\u3002"],
    accept: ["Accepting", "\u6b63\u5728\u63a5\u53d7\u5df2\u9a8c\u8bc1\u7684\u7ed3\u679c\u3002"],
    debug: [
      "Repairing",
      "\u6b63\u5728\u68c0\u67e5\u95ee\u9898\u5e76\u51c6\u5907\u4fee\u590d\u8def\u5f84\u3002",
    ],
    decide: [
      "Deciding",
      "\u6b63\u5728\u68c0\u67e5\u9700\u8981\u4f60\u5224\u65ad\u7684\u9009\u9879\u3002",
    ],
  };
  const [title, summary] = labels[mode] || ["Processing", "Working on the request."];
  return {
    type: "assistant_delta",
    status: "running",
    title,
    summary,
    phase: mode === "review" ? "review" : mode === "plan" ? "plan" : "execute",
    display_level: "main",
    content_delta: summary,
  };
}

function runtimeCommand(mode, goal, options = {}) {
  if (mode === "continue") {
    return runtimeContinuationCommand(goal);
  }
  if (mode === "orchestration") {
    const manifest = String(
      options.manifest || "benchmarks/orchestration_s72_ingress_manifest.json",
    );
    const liveFlag = options.live ? "--live" : "";
    return [
      python,
      "-m",
      moduleName,
      "orchestration",
      "run",
      "--root",
      workspace,
      "--manifest",
      manifest,
      ...(liveFlag ? [liveFlag] : []),
    ];
  }
  if (mode === "run") {
    return [
      python,
      "-m",
      moduleName,
      "run",
      "--root",
      workspace,
      "--max-iterations",
      "8",
      "--max-tasks-per-iteration",
      "1",
      "--no-research",
      goal,
    ];
  }
  if (mode === "review") return [python, "-m", moduleName, "review", "--root", workspace];
  if (mode === "resume")
    return [
      python,
      "-m",
      moduleName,
      "resume",
      "--root",
      workspace,
      "--max-iterations",
      "8",
      "--max-tasks-per-iteration",
      "1",
    ];
  if (mode === "accept") return [python, "-m", moduleName, "accept", "--root", workspace];
  if (mode === "debug") return [python, "-m", moduleName, "debug", "--root", workspace];
  if (mode === "decide")
    return [python, "-m", moduleName, "decide", "--root", workspace, "--list-pending"];
  return [python, "-m", moduleName, "plan", "--root", workspace, goal];
}

function runtimeContinuationCommand(goal) {
  return [
    python,
    "-m",
    moduleName,
    "run",
    "--continue-session",
    "--root",
    workspace,
    "--max-iterations",
    "8",
    "--max-tasks-per-iteration",
    "1",
    "--no-research",
    goal,
  ];
}

async function resolveStudioOrchestrationRoute(goal, requestedMode) {
  const explicitModes = new Set(["chat", "plan", "run", "review", "resume", "accept"]);
  const explicit = explicitModes.has(String(requestedMode || "").toLowerCase())
    ? String(requestedMode).toLowerCase()
    : null;
  // Honor an explicit user choice directly: if the user picked "run", RUN it — the model intent
  // router only decides in "auto". Letting the router reclassify an explicit execute request into a
  // read-only plan (or a continuation) is exactly the erratic behavior that made "开发一个计算器"
  // silently turn into a plan or a redo of the previous task.
  if (explicit && explicit !== "chat") {
    return {
      mode: explicit,
      studio_mode: explicit,
      route: "explicit",
      reason: "",
      source: "explicit_mode",
      command: orchestrationCommandFor(explicit, goal),
    };
  }
  const modeArg = explicit || "auto";
  const routed = await routeClient
    .route({
      root: workspace,
      message: String(goal || ""),
      requestedMode: modeArg,
    })
    .catch(() => null);
  if (!routed || routed.ok === false || !routed.studio_mode) {
    return resolveStudioExecutionRouteFallback(goal, requestedMode);
  }
  const studioMode = String(routed.studio_mode || "run");
  const command = orchestrationCommandFor(studioMode, goal, {
    manifest: routed.manifest_path || null,
    live: routed.live_execution === true,
  });
  return {
    mode: studioMode,
    studio_mode: studioMode,
    route: routed.route_kind || "orchestration",
    reason: routed.reason || "",
    source: routed.source || "orchestration",
    capability_id: routed.capability_id || null,
    route_transport: routed.transport || "worker",
    command,
  };
}

function orchestrationCommandFor(studioMode, goal, options = {}) {
  // A new user message is a new goal — plan it fresh over the current workspace, like Claude Code /
  // Cursor handle every turn. The old "continue-session" shortcut skipped GoalSpec/Plan and reused the
  // previous task's scope, so an unrelated new goal ("build a calculator") got misrouted into the last
  // task and thrashed/blocked. Route it as a normal cold run instead; the planner infers the right
  // scope and the existing files simply stay in the workspace. (Genuinely in-progress runs still
  // resume via the separate "resume" mode.)
  if (studioMode === "continue") return runtimeCommand("run", goal);
  if (studioMode === "orchestration") {
    return runtimeCommand("orchestration", goal, {
      manifest: options.manifest,
      live: options.live,
    });
  }
  if (studioMode === "chat") return null;
  return runtimeCommand(studioMode, goal);
}

function orchestrationHasRouteSignal(orchestrated) {
  // The no-signal cold fallback from resolveStudioExecutionRouteFallback
  // (source "rules_fallback" + route "cold") means "no in-progress/warm
  // continuation applies", so the base intent from routeUserIntent (chat /
  // plan / run) must stand unchanged. Every other orchestration result —
  // warm_session, resume_in_progress, or a real runtime-router decision —
  // carries a genuine signal and should be honored.
  if (!orchestrated || !orchestrated.mode) return false;
  return !(
    String(orchestrated.source) === "rules_fallback" && String(orchestrated.route) === "cold"
  );
}

async function resolveStudioExecutionRouteFallback(goal, requestedMode) {
  if (requestedMode === "plan") {
    return { mode: "run", route: "cold", reason: null, command: null, source: "rules_fallback" };
  }
  const status = await commandJson(["status", "--root", workspace, "--json"]).catch(() => ({}));
  const phase = String(status?.current_phase || "").toUpperCase();
  const runStatus = String(
    status?.current_context?.run_status?.status ||
      status?.run_status?.status ||
      status?.status ||
      "",
  ).toLowerCase();
  const currentRunId = String(status?.current_session_id || "").trim();
  if (!currentRunId) {
    return { mode: "run", route: "cold", reason: null, command: null, source: "rules_fallback" };
  }

  const inProgress =
    !CONTINUABLE_STUDIO_PHASES.has(phase) &&
    ["running", "blocked", "paused", "in_progress"].includes(runStatus);
  if (inProgress) {
    return {
      mode: "resume",
      route: "resume_in_progress",
      reason: "当前 session 仍在推进中，后续消息将直接 resume，跳过重新 plan。",
      command: null,
      source: "rules_fallback",
    };
  }

  // A completed/accepted run means the workspace is idle — a new message is a NEW goal, so plan it
  // fresh (cold) rather than reusing the previous task via the continue-session shortcut, which
  // misrouted unrelated goals into the last task. Only genuinely in-progress runs resume (above).
  return { mode: "run", route: "cold", reason: null, command: null, source: "rules_fallback" };
}

async function resolveStudioExecutionRoute(sessionId, goal, requestedMode) {
  return resolveStudioOrchestrationRoute(goal, requestedMode);
}

const CONTINUABLE_STUDIO_PHASES = new Set(["ACCEPTED", "DONE", "REVIEW"]);

function phaseForMode(mode) {
  if (mode === "run") return "execute";
  if (mode === "continue") return "execute";
  if (mode === "review") return "review";
  if (mode === "resume") return "resume";
  if (mode === "accept") return "result";
  if (mode === "debug") return "repair";
  if (mode === "decide") return "decision";
  return "plan";
}

async function handleChatMode(sessionId, goal, route = null, audit = null, displayLevel = "main") {
  await appendEvent(sessionId, {
    type: "user_message",
    status: "completed",
    title: "User",
    summary: goal.slice(0, 80),
    content_delta: goal,
    phase: displayLevel === "side" ? "chat" : "understand",
    display_level: displayLevel,
    ui_intent: displayLevel === "side" ? "side_chat" : undefined,
  });
  startChatJob(sessionId, goal, route, audit, displayLevel);
  return {
    ok: true,
    chat: true,
    started: true,
    channel: displayLevel === "side" ? "side" : "main",
  };
}

function startChatJob(sessionId, goal, route = null, audit = null, displayLevel = "main") {
  const jobId = `chat-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`;
  const job = {
    job_id: jobId,
    session_id: sessionId,
    status: "running",
    mode: "chat",
    goal,
    started_at_ms: Date.now(),
  };
  liveJobs.set(jobId, job);
  const stopTail = tailSessionEvents(sessionId, jobId);
  let lifecycleStarted = false;
  const markLifecycleStarted = () => {
    lifecycleStarted = true;
  };

  void (async () => {
    try {
      let answerInput = goal;
      if (displayLevel === "side") {
        const ctx = await readChatContext(sessionId).catch(() => ({}));
        answerInput = `${sideAskContextHint(ctx)}\n\nUser question:\n${goal}`;
      }
      const answer = await buildChatAnswer(answerInput, sessionId, route, markLifecycleStarted);
      if (answer.usedModel) await hideManualChatModelStart(sessionId);
      else if (!lifecycleStarted) await appendChatFallbackLifecycle(sessionId, answer);
      await appendEvent(sessionId, {
        type: "final_answer",
        status: "completed",
        title: "Asteria",
        summary: "Answer prepared.",
        phase: "chat",
        display_level: displayLevel,
        ui_intent: displayLevel === "side" ? "side_chat" : undefined,
        content_delta: answer.content,
        model_provider: answer.route?.provider,
        model_name: answer.route?.model,
        model_tier: answer.route?.tier,
        model_route: answer.route,
        intent_audit: audit,
      });
      job.status = "completed";
    } catch (error) {
      job.status = "failed";
      const rawError = String(error?.stack || error);
      const friendly = friendlyErrorText(rawError);
      await appendEvent(sessionId, {
        type: "error",
        status: "failed",
        title: friendlyErrorTitle(rawError) || "Chat failed",
        summary: friendlyErrorSummary(rawError) || String(error?.message || error),
        phase: "chat",
        display_level: displayLevel,
        ui_intent: displayLevel === "side" ? "side_chat" : undefined,
        content_delta: friendly || redactText(rawError),
      });
    } finally {
      stopTail();
      liveJobs.set(jobId, job);
    }
  })();
}

function tailSessionEvents(sessionId, jobId) {
  const file = sessionPath(sessionId, "events.jsonl");
  const seen = new Set();
  let stopped = false;
  let offset = 0;
  try {
    if (existsSync(file)) offset = statSync(file).size || 0;
  } catch {}
  const poll = async () => {
    if (stopped) return;
    try {
      if (existsSync(file)) {
        const stat = await fs.stat(file);
        if (stat.size < offset) offset = 0;
        if (stat.size > offset) {
          const handle = await fs.open(file, "r");
          try {
            const buffer = Buffer.alloc(stat.size - offset);
            await handle.read(buffer, 0, buffer.length, offset);
            offset = stat.size;
            for (const line of buffer.toString("utf8").split(/\r?\n/).filter(Boolean)) {
              try {
                const event = JSON.parse(line);
                if (!event.event_id || seen.has(event.event_id)) continue;
                seen.add(event.event_id);
                notifySSE(sessionId, redact(event));
              } catch {}
            }
          } finally {
            await handle.close();
          }
        }
      }
    } catch {}
    if (!stopped) setTimeout(poll, 180);
  };
  setTimeout(poll, 100);
  return () => {
    stopped = true;
  };
}

async function appendChatFallbackLifecycle(sessionId, answer) {
  const lifecycle = await appendChatModelStart(sessionId, answer.route, "local_fallback");
  await appendChatFallbackDelta(sessionId, lifecycle, answer.content, answer.route);
}

async function hideManualChatModelStart(sessionId) {
  if (!isSafeId(sessionId)) return;
  const file = sessionPath(sessionId, "events.jsonl");
  if (!existsSync(file)) return;
  let rows;
  try {
    rows = (await fs.readFile(file, "utf8"))
      .split(/\r?\n/)
      .filter(Boolean)
      .map((line) => JSON.parse(line));
  } catch {
    return;
  }
  const hasProviderStart = rows.some(
    (event) =>
      event.type === "model_start" &&
      event.phase === "chat" &&
      String(event.event_id || "").startsWith("evt-model-"),
  );
  if (!hasProviderStart) return;
  let changed = false;
  const nextRows = rows.map((event) => {
    if (
      event.type === "model_start" &&
      event.phase === "chat" &&
      !String(event.event_id || "").startsWith("evt-model-") &&
      event.status === "running"
    ) {
      changed = true;
      return {
        ...event,
        display_level: "hidden",
        status: "completed",
        summary: "Replaced by provider streaming lifecycle.",
      };
    }
    return event;
  });
  if (changed)
    await fs.writeFile(
      file,
      `${nextRows.map((event) => JSON.stringify(event)).join("\n")}\n`,
      "utf8",
    );
}

async function appendChatModelStart(sessionId, route, streamingMode = "streaming") {
  const start = await appendEvent(sessionId, {
    type: "model_start",
    status: "running",
    title: "Thinking",
    summary: "Asteria is preparing a chat answer.",
    phase: "chat",
    display_level: "main",
    content_delta: "",
    model_provider: route?.provider,
    model_name: route?.model,
    model_tier: route?.tier,
    model_route: route,
    streaming_mode: streamingMode,
  });
  return { start, startedAt: Date.now() };
}

async function appendChatFallbackDelta(sessionId, lifecycle, content, route) {
  const parentId = lifecycle?.start?.event_id;
  await appendEvent(sessionId, {
    type: "model_delta",
    status: "running",
    title: "Chat response update",
    summary: "Receiving chat response content.",
    phase: "chat",
    display_level: "main",
    content_delta: content,
    parent_event_id: parentId,
    model_provider: route?.provider,
    model_name: route?.model,
    model_tier: route?.tier,
    model_route: route,
  });
  await appendEvent(sessionId, {
    type: "model_end",
    status: "completed",
    title: "Chat response completed",
    summary: "Chat response completed.",
    phase: "chat",
    display_level: "main",
    content_delta: "",
    parent_event_id: parentId,
    model_provider: route?.provider,
    model_name: route?.model,
    model_tier: route?.tier,
    model_route: route,
    telemetry: { duration_ms: lifecycle?.startedAt ? Date.now() - lifecycle.startedAt : null },
  });
}

async function buildChatAnswer(message, sessionId, route = null, onLifecycleStart = null) {
  const m = message.trim();
  const lower = m.toLowerCase();

  if (isRuntimeMetaQuestion(lower)) return chatAnswer(await chatRuntimeAnswer(m, sessionId));
  if (hasAny(lower, ["who are you", "\u4f60\u662f\u8c01", "\u81ea\u6211\u4ecb\u7ecd"]))
    return await chatGeneralAnswer(m, sessionId, onLifecycleStart);
  if (isModeHelpQuestion(lower)) return chatAnswer(CHAT_MODES);

  // The backend intent router (routeUserIntent) already decided this message stays in chat rather
  // than becoming a run/plan, so buildChatAnswer must NOT re-guess "is this a task?" with a keyword
  // heuristic and short-circuit to a canned template. Answer conversationally via the model.
  return await chatGeneralAnswer(m, sessionId, onLifecycleStart);
}

function chatAnswer(content, route = null, usedModel = false) {
  return {
    content,
    usedModel,
    route,
    routeLabel: routeLabel(route),
  };
}

async function chatRuntimeAnswer(message, sessionId) {
  const lower = message.toLowerCase();
  if (
    hasAny(lower, [
      "model route",
      "route rationale",
      "cheap mode",
      "cost mode",
      "why this model",
      "\u4e3a\u4ec0\u4e48\u7528",
      "\u6a21\u578b\u8def\u7ebf",
      "\u7701\u94b1",
      "\u6210\u672c",
    ])
  ) {
    return await chatModelRouteAnswer(sessionId);
  }
  return await chatStatusAnswer(sessionId);
}

async function chatGeneralAnswer(message, sessionId, onLifecycleStart = null) {
  const context = await readChatContext(sessionId).catch(() => ({}));
  const kind = classifyChatRequest(message);
  const prompt = [
    ...outcomeAnswerContract(kind),
    `Internal intent hint: ${kind}. Use this only to choose answer shape; do not show the label.`,
    context.latestRunId
      ? `Background only if relevant: latest_run=${context.latestRunId}, state=${firstRuntimeText(context.run?.status, "unknown")}/${firstRuntimeText(context.run?.current_phase, "unknown")}.`
      : "No run context is needed unless asked.",
  ].join("\n");
  const route = await preferredChatRoute();
  if (chatBackend === "model") {
    const lifecycle = await appendChatModelStart(sessionId, route, "streaming");
    if (onLifecycleStart) onLifecycleStart();
    const answered = await chatModelAnswer(prompt, message, sessionId);
    const streamedAnswer = extractVisibleChatAnswerFromEvents(sessionId);
    const finalAnswer = streamedAnswer || answered;
    if (finalAnswer) return chatAnswer(appendModelNotice(finalAnswer, route, true), route, true);
    await appendChatFallbackDelta(
      sessionId,
      lifecycle,
      appendModelNotice(localGeneralAnswer(message), route, false),
      route,
    );
  }
  return chatAnswer(appendModelNotice(localGeneralAnswer(message), route, false), route, false);
}

// Honesty: the local*Answer templates are NOT model output. When no model was reached, disclose it
// so a canned answer is never presented as a generated one. Wording avoids the backend-metadata
// tokens the fallback smokes forbid (no "route"/"intent"/"Temporary local fallback").
function appendModelNotice(answer, route, usedModel) {
  void route;
  const text = String(answer || "").trim();
  if (usedModel) return text;
  const notice =
    "_Heads up: no model was reachable for this reply, so this is a built-in template answer, " +
    "not a generated one. Add your key details and resend for a real answer._";
  return text ? `${text}\n\n${notice}` : notice;
}

async function preferredChatRoute() {
  const routes = await modelRouteSummary().catch(() => []);
  const chatRoute =
    routes.find((item) => String(item.purpose || "").toLowerCase() === "chat") ||
    routes.find((item) => String(item.tier || "").toLowerCase() === "medium") ||
    routes[0] ||
    null;
  return chatRoute
    ? {
        provider: firstRuntimeText(chatRoute.provider, "unknown"),
        model: firstRuntimeText(chatRoute.model, "unknown"),
        tier: firstRuntimeText(chatRoute.tier, "unknown"),
        purpose: firstRuntimeText(chatRoute.purpose, "chat"),
      }
    : null;
}

function routeLabel(route) {
  if (!route) return "configured chat route";
  return `${firstRuntimeText(route.provider, "unknown")}/${firstRuntimeText(route.model, "unknown")} - ${firstRuntimeText(route.tier, "unknown")} - ${firstRuntimeText(route.purpose, "chat")}`;
}

function chatHistoryForSession(sessionId) {
  if (!isSafeId(sessionId)) return [];
  const file = sessionPath(sessionId, "events.jsonl");
  if (!existsSync(file)) return [];
  try {
    return recentChatHistoryMessages(fsSyncReadJsonl(file));
  } catch {
    return [];
  }
}

async function chatModelAnswer(systemPrompt, message, sessionId) {
  if (process.env.ASTERIA_STUDIO_FAKE_CHAT_ERROR) {
    throw new Error(process.env.ASTERIA_STUDIO_FAKE_CHAT_ERROR);
  }
  try {
    // Feed the recent completed chat turns (already persisted in this session's events.jsonl) into
    // ChatCommand so the reply is no longer single-turn amnesiac. ChatCommand bounds/clips further.
    const history = chatHistoryForSession(sessionId);
    const payload = Buffer.from(
      JSON.stringify({
        question: `System instruction:\n${systemPrompt}\n\nUser question:\n${message}`,
        history,
      }),
      "utf8",
    ).toString("base64");
    const script = [
      "import base64, json, os",
      "from pathlib import Path",
      "from asteria_runtime.commands.chat_command import ChatCommand",
      "data = json.loads(base64.b64decode(os.environ['ASTERIA_STUDIO_CHAT_PAYLOAD']).decode('utf-8'))",
      "result = ChatCommand(root=Path(os.environ['ASTERIA_STUDIO_ROOT']), question=data['question'], history=data.get('history')).run()",
      "print(json.dumps(result.to_dict(), ensure_ascii=False))",
    ].join("; ");
    const completed = await runCommand([python, "-c", script], runtimeRoot, {
      PYTHONIOENCODING: "utf-8",
      ASTERIA_STUDIO_CHAT_BACKEND: undefined,
      ASTERIA_STUDIO_CHAT_PAYLOAD: payload,
      ASTERIA_STUDIO_ROOT: workspace,
      ASTERIA_STUDIO_EVENT_SINK: sessionPath(sessionId, "events.jsonl"),
      ASTERIA_STUDIO_SESSION_ID: sessionId,
      ASTERIA_STUDIO_PHASE: "chat",
    });
    if (completed.code !== 0) return "";
    const raw = String(completed.stdout || "")
      .replace(/^\uFEFF/, "")
      .trim();
    try {
      const parsed = JSON.parse(raw);
      const answer = cleanAssistantText(stripCliContextNoise(parsed.answer || ""));
      return answer || localGeneralAnswer(message);
    } catch {
      return stripCliChatEnvelope(raw) || localGeneralAnswer(message);
    }
  } catch {
    return "";
  }
}

function stripCliChatEnvelope(stdout) {
  const lines = String(stdout || "").split(/\r?\n/);
  const useful = [];
  let skippingHeader = true;
  for (const line of lines) {
    if (
      skippingHeader &&
      (/^Chat\s*$/.test(line) || /^Permission level:/.test(line) || /^Model strategy:/.test(line))
    )
      continue;
    skippingHeader = false;
    useful.push(line);
  }
  return cleanAssistantText(stripCliContextNoise(useful.join("\n").trim()));
}

function stripCliContextNoise(text) {
  return String(text || "")
    .split(/\nContext refs:|\nCurrent session:|\nNext actions:/i)[0]
    .trim();
}

function stripThinkingBlocks(text) {
  return String(text || "")
    .replace(/<think>[\s\S]*?<\/think>/gi, "")
    .replace(/<think>[\s\S]*$/gi, "")
    .trim();
}

function extractVisibleChatAnswerFromEvents(sessionId) {
  if (!isSafeId(sessionId)) return "";
  const file = sessionPath(sessionId, "events.jsonl");
  if (!existsSync(file)) return "";
  let rows = [];
  try {
    rows = fsSyncReadJsonl(file);
  } catch {
    return "";
  }
  let latestStartIndex = -1;
  for (let i = rows.length - 1; i >= 0; i -= 1) {
    const event = rows[i];
    if (
      event.type === "model_start" &&
      event.phase === "chat" &&
      String(event.event_id || "").startsWith("evt-model-")
    ) {
      latestStartIndex = i;
      break;
    }
  }
  if (latestStartIndex < 0) return "";
  const start = rows[latestStartIndex];
  const parentId = start.event_id;
  const chunks = [];
  for (const event of rows.slice(latestStartIndex + 1)) {
    if (event.phase !== "chat") continue;
    if (event.type === "model_start" && event.event_id !== parentId) break;
    if (
      event.type === "model_delta" &&
      (!event.parent_event_id || event.parent_event_id === parentId)
    ) {
      chunks.push(String(event.content_delta || ""));
    }
    if (
      event.type === "model_end" &&
      (!event.parent_event_id || event.parent_event_id === parentId)
    )
      break;
  }
  return cleanAssistantText(stripCliContextNoise(stripThinkingBlocks(chunks.join(""))));
}

function fsSyncReadJsonl(file) {
  try {
    const raw = requireReadFileSync(file);
    return raw
      .split(/\r?\n/)
      .filter(Boolean)
      .map((line) => JSON.parse(line));
  } catch {
    return [];
  }
}

function requireReadFileSync(file) {
  return Buffer.from(readFileSync(file)).toString("utf8");
}

function cleanAssistantText(text) {
  const value = repairMojibake(String(text || ""))
    .replace(/\uFFFD/g, "-")
    .replace(/\s+-\s+/g, " - ")
    .trim();
  return isLikelyGarbledAnswer(value) ? "" : value;
}

function repairMojibake(text) {
  const value = String(text || "");
  const cjkCount = (value.match(/[㐀-鿿]/g) || []).length;
  const replacementCount = (value.match(/�/g) || []).length;
  const latin1ControlCount = (value.match(/[-ÿ]/g) || []).length;
  // Markdown tables and separators contain many dashes; that is not mojibake.
  // If the text already contains substantial CJK and no replacement/control bytes,
  // keep it exactly as streamed so Chinese answers are not stripped to ASCII.
  if (cjkCount >= 5 && replacementCount === 0 && latin1ControlCount === 0) return value;
  const suspicious = replacementCount + latin1ControlCount;
  if (suspicious < 3) return value;
  try {
    const bytes = Uint8Array.from([...value].map((ch) => ch.charCodeAt(0) & 0xff));
    const repaired = new TextDecoder("utf-8", { fatal: false }).decode(bytes).trim();
    return repaired.length >= Math.max(20, value.length * 0.35) ? repaired : value;
  } catch {
    return value;
  }
}

function isLikelyGarbledAnswer(text) {
  const value = String(text || "").trim();
  if (!value) return true;
  const controlChars = (value.match(/[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/g) || []).length;
  if (controlChars > 0) return true;
  const asciiLetters = (value.match(/[A-Za-z]/g) || []).length;
  const cjkLetters = (value.match(/[\u3400-\u9fff]/g) || []).length;
  const markdownNoise = (value.match(/[#*|_-]/g) || []).length;
  const visible = value.replace(/\s/g, "").length || 1;
  return asciiLetters + cjkLetters < 12 && markdownNoise / visible > 0.35;
}

function localGeneralAnswer(message) {
  const kind = classifyChatRequest(message);
  if (String(kind || "").endsWith("_plan")) return localOutcomePlanAnswer(message, kind);
  return [
    "## Quick answer",
    "",
    "I could not reach a configured model for this message, so here is a safe general way to move forward without inventing details.",
    "",
    "- Restate the exact result you want: explanation, checklist, comparison, draft, or step-by-step plan.",
    "- Add the important constraints: time, budget, audience, location, difficulty, format, or things to avoid.",
    "- If you want a concise answer, ask for a short version; if you want depth, ask for tradeoffs and examples.",
    "",
    "Next step: send the missing constraints and I can turn this into a more complete answer.",
  ].join("\n");
}

function localOutcomePlanAnswer(message, kind) {
  const goal = String(message || "").trim() || "your goal";
  const domainNote =
    kind === "travel_plan"
      ? "Assumption: you want a balanced itinerary with room for rest, local food, and one backup option per day."
      : kind === "learning_plan"
        ? "Assumption: you want steady progress with clear practice loops and checkpoints."
        : kind === "content_plan"
          ? "Assumption: you want a practical outline that can become a draft or production checklist."
          : "Assumption: you want a practical plan that can be adjusted after you add constraints.";
  const focus =
    kind === "travel_plan"
      ? [
          "Confirm dates, budget, travel companions, pace, and must-see constraints.",
          "Group activities by geography so each day has one primary area and one optional backup.",
          "Reserve high-demand transport, hotels, restaurants, or tickets first.",
        ]
      : kind === "learning_plan"
        ? [
            "Define the target level and one measurable outcome.",
            "Split the plan into input, deliberate practice, feedback, and review.",
            "Schedule small daily actions and a weekly checkpoint.",
          ]
        : kind === "content_plan"
          ? [
              "Clarify audience, promise, tone, and final format.",
              "Draft the core structure before polishing details.",
              "Review against usefulness, specificity, and clarity before publishing or sharing.",
            ]
          : [
              "Clarify the target result and constraints.",
              "Break the work into phases with a visible checkpoint after each phase.",
              "Decide what can be simplified if time, budget, or confidence drops.",
            ];
  return [
    "## Goal understanding",
    `You want a usable plan for: ${goal}`,
    "",
    "## Working assumptions",
    domainNote,
    "",
    "## Recommended plan",
    ...focus.map((item, index) => `${index + 1}. ${item}`),
    "",
    "## Suggested sequence",
    "1. Set the non-negotiables: deadline, budget, scope, audience, and success criteria.",
    "2. Build the first complete version with only the necessary details.",
    "3. Add alternatives for the riskiest parts instead of over-planning everything.",
    "4. Review the plan once from the user's point of view: what is unclear, unrealistic, or missing?",
    "5. Convert the plan into the next concrete action you can do today.",
    "",
    "## Risks and tradeoffs",
    "- Too many details too early can make the plan rigid.",
    "- Too few constraints can make the recommendation generic.",
    "- The best next version should add the few details that affect the decision most.",
    "",
    "## Next action",
    "Send the key constraints you already know, and I can turn this into a more specific final plan.",
  ].join("\n");
}

function isModeHelpQuestion(lower) {
  return hasAny(lower, [
    "which mode",
    "what mode",
    "choose mode",
    "how to choose mode",
    "plan/run",
    "chat/plan",
    "review mode",
    "resume mode",
    "\u6a21\u5f0f",
    "\u600e\u4e48\u9009\u6a21\u5f0f",
    "\u9009\u62e9\u54ea\u4e2a\u6a21\u5f0f",
    "plan \u6a21\u5f0f",
    "run \u6a21\u5f0f",
    "review \u6a21\u5f0f",
    "resume \u6a21\u5f0f",
  ]);
}

async function chatStatusAnswer(sessionId) {
  const context = await readChatContext(sessionId);
  if (!context.latestRunId) {
    return [
      "## \u5f53\u524d\u72b6\u6001",
      "",
      "\u73b0\u5728\u6ca1\u6709\u9700\u8981\u4f60\u5904\u7406\u7684\u8fdb\u884c\u4e2d\u4efb\u52a1\u3002",
      "",
      "## \u4f60\u53ef\u4ee5\u7ee7\u7eed\u505a\u4ec0\u4e48",
      "- \u76f4\u63a5\u95ee\u4e00\u4e2a\u95ee\u9898\uff0c\u6211\u4f1a\u81ea\u7136\u56de\u7b54\u3002",
      "- \u63cf\u8ff0\u4e00\u4e2a\u76ee\u6807\uff0c\u6211\u53ef\u4ee5\u5148\u5e2e\u4f60\u6574\u7406\u6210\u8ba1\u5212\u3002",
      "- \u5982\u679c\u9700\u8981\u771f\u6b63\u6267\u884c\uff0c\u6211\u4f1a\u5728\u654f\u611f\u52a8\u4f5c\u524d\u8bf7\u4f60\u786e\u8ba4\u3002",
    ].join("\n");
  }
  const status = context.status;
  const run = context.run;
  const summary = context.finalSummary;
  const loop = context.runLoopSummary;
  const progress = context.runtimeProgress || {};
  const progressTodo = progress.todo || {};
  const verification = progress.verification || {};
  const next = firstRuntimeText(
    progress.next_command,
    commandFromStatus(status, summary, loop),
    "",
  );
  const decisionId = context.latestDecision
    ? context.latestDecision.decision_id || context.latestDecision.id
    : "";
  const blocker = firstRuntimeText(
    summary.current_blocker,
    loop.current_blocker,
    status.current_blocker,
    decisionId
      ? "\u6709\u4e00\u4e2a\u9700\u8981\u4f60\u786e\u8ba4\u7684\u51b3\u7b56\u70b9\u3002"
      : "none",
  );
  const workflow = firstRuntimeText(
    progress.workflow_state,
    summary.workflow_state,
    loop.workflow_state,
    status.workflow_state,
    run.current_phase,
    "unknown",
  );
  const canReview = Boolean(status.can_review);
  const canAccept = Boolean(status.can_accept);
  const goal = firstRuntimeText(
    run.goal,
    run.original_goal,
    context.goalSpec.normalized_goal,
    context.goalSpec.original_goal,
    "\u672a\u8bb0\u5f55\u76ee\u6807",
  );
  const lines = [
    "## \u5f53\u524d\u72b6\u6001",
    "",
    `\u4efb\u52a1\u76ee\u6807\uff1a${goal}`,
    `\u8fdb\u5c55\uff1a${friendlyWorkflow(workflow)}`,
    `\u5f53\u524d\u6b65\u9aa4\uff1a${firstRuntimeText(progress.current_step, "\u8fd8\u6ca1\u6709\u8bb0\u5f55\u660e\u786e\u6b65\u9aa4")}`,
    `Todo\uff1a${firstRuntimeText(progressTodo.summary, "\u8fd8\u6ca1\u6709 Todo \u6458\u8981")}`,
    `\u9a8c\u8bc1\uff1a${firstRuntimeText(verification.summary, "\u8fd8\u6ca1\u6709\u9a8c\u8bc1\u7ed3\u679c")}`,
    "",
    "## \u662f\u5426\u6709\u963b\u585e",
    blocker && blocker !== "none"
      ? `- ${blocker}`
      : "- \u6682\u65f6\u6ca1\u6709\u770b\u5230\u9700\u8981\u4f60\u5904\u7406\u7684\u963b\u585e\u3002",
    "",
    "## \u5efa\u8bae\u4e0b\u4e00\u6b65",
  ];
  if (canAccept)
    lines.push(
      "- \u7ed3\u679c\u770b\u8d77\u6765\u5df2\u7ecf\u53ef\u4ee5\u63a5\u53d7\u3002\u5982\u679c\u4f60\u5bf9\u4ea7\u7269\u6ee1\u610f\uff0c\u53ef\u4ee5\u786e\u8ba4\u63a5\u53d7\u3002",
    );
  else if (canReview)
    lines.push(
      "- \u5efa\u8bae\u5148\u8fdb\u884c\u5ba1\u67e5\uff0c\u786e\u8ba4\u7ed3\u679c\u662f\u5426\u7b26\u5408\u76ee\u6807\u3002",
    );
  else if (decisionId)
    lines.push(
      "- \u9700\u8981\u4f60\u5148\u5904\u7406\u4e00\u4e2a\u51b3\u7b56\u70b9\uff0c\u518d\u7ee7\u7eed\u63a8\u8fdb\u3002",
    );
  else if (next)
    lines.push(
      "- \u53ef\u4ee5\u7ee7\u7eed\u63a8\u8fdb\u4e0b\u4e00\u6b65\u3002\u6211\u4f1a\u5728\u9700\u8981\u6267\u884c\u6216\u4fee\u6539\u524d\u8bf7\u4f60\u786e\u8ba4\u3002",
    );
  else
    lines.push(
      "- \u5efa\u8bae\u5148\u8ba9\u6211\u628a\u76ee\u6807\u518d\u6574\u7406\u6210\u4e00\u4e2a\u6e05\u6670\u8ba1\u5212\u3002",
    );
  return lines.join("\n");
}

function friendlyWorkflow(value) {
  const text = String(value || "").toLowerCase();
  if (/accept|accepted|done|completed|pass/.test(text))
    return "\u5df2\u5b8c\u6210\u6216\u7b49\u5f85\u6700\u7ec8\u786e\u8ba4";
  if (/review/.test(text)) return "\u7b49\u5f85\u5ba1\u67e5";
  if (/block|decision|pause|wait/.test(text))
    return "\u6682\u505c\uff0c\u7b49\u5f85\u786e\u8ba4\u6216\u5904\u7406\u963b\u585e";
  if (/run|exec|work|progress/.test(text)) return "\u6b63\u5728\u63a8\u8fdb";
  if (/plan/.test(text)) return "\u6b63\u5728\u6574\u7406\u8ba1\u5212";
  return "\u72b6\u6001\u4e0d\u660e\uff0c\u5efa\u8bae\u5148\u505a\u4e00\u6b21\u7b80\u77ed\u68c0\u67e5";
}

async function chatModelRouteAnswer(sessionId) {
  void sessionId;
  return [
    "## \u6a21\u578b\u4f7f\u7528\u539f\u5219",
    "",
    "\u666e\u901a\u7528\u6237\u4fa7\u4e0d\u5c55\u793a\u5177\u4f53\u540e\u53f0\u8def\u7531\u548c\u8bc1\u636e\u7ec6\u8282\u3002\u4f60\u53ea\u9700\u8981\u77e5\u9053\uff1a",
    "",
    "- \u7b80\u5355\u95ee\u7b54\u4f1a\u5c3d\u91cf\u7528\u4f4e\u6210\u672c\u8def\u5f84\u3002",
    "- \u9700\u8981\u63a8\u7406\u3001\u89c4\u5212\u6216\u68c0\u67e5\u65f6\uff0c\u4f1a\u4f7f\u7528\u66f4\u7a33\u7684\u80fd\u529b\u3002",
    "- \u9700\u8981\u4fee\u6539\u3001\u6267\u884c\u6216\u9ad8\u6210\u672c\u52a8\u4f5c\u65f6\uff0c\u6211\u4f1a\u5148\u8bf4\u660e\u5e76\u7b49\u5f85\u786e\u8ba4\u3002",
    "",
    "\u5982\u679c\u4f60\u60f3\u7701\u94b1\uff0c\u53ef\u4ee5\u76f4\u63a5\u8bf4\u201c\u7528\u7701\u94b1\u6a21\u5f0f\u201d\u6216\u201c\u5148\u7ed9\u7b80\u7248\u201d\u3002",
  ].join("\n");
}

function sideAskContextHint(context) {
  const goal = firstRuntimeText(context.goalSpec?.goal, context.run?.goal, "");
  const phase = firstRuntimeText(context.run?.current_phase, context.run?.status, "unknown");
  const ratio = context.runtimeProgress?.cost?.context_window_ratio;
  const lines = [
    "Side ask: answer briefly without starting a new runtime turn.",
    goal ? `Active goal: ${goal.slice(0, 240)}` : null,
    `Run phase: ${phase}`,
    ratio != null && Number.isFinite(Number(ratio))
      ? `Context pressure: ${Math.round(Number(ratio) * 100)}%`
      : null,
  ].filter(Boolean);
  return lines.join("\n");
}

async function readChatContext(sessionId) {
  const overviewData = await overview();
  const latestRunId = firstRuntimeText(overviewData.runs?.[0]?.run_id, "");
  const detail = latestRunId ? await readRunDetail(latestRunId) : {};
  const status = await commandJson(["status", "--root", workspace, "--json"]).catch(() => ({}));
  const runDir = latestRunId ? path.join(workspace, ".asteria", "runs", latestRunId) : null;
  const decisions = runDir
    ? latestDecisions(await readJsonlTail(path.join(runDir, "decisions.jsonl"), 20))
    : [];
  const pendingDecision =
    [...decisions]
      .reverse()
      .find((item) =>
        /pending|open|waiting/i.test(String(item.status ?? item.state ?? "pending")),
      ) || decisions.at(-1);
  return {
    sessionId,
    overview: overviewData,
    latestRunId,
    detail,
    status,
    run: detail.run || {},
    goalSpec: detail.goal_spec || {},
    finalSummary: detail.final_report_summary || {},
    runLoopSummary: detail.run_loop_summary || {},
    runtimeProgress:
      detail.runtime_progress ||
      (detail.final_report_summary || {}).runtime_progress ||
      (detail.run_loop_summary || {}).runtime_progress ||
      {},
    modelRouteTimeline: detail.model_route_timeline || {},
    latestDecision: pendingDecision || null,
  };
}

function commandFromStatus(status, summary, loop) {
  const raw = firstRuntimeText(
    summary.recommended_next_command,
    loop.recommended_next_command,
    status.recommended_next_command,
    "",
  );
  return raw.replace(/^asteria\s+/, "").trim();
}

function latestRouteDecision(context) {
  const artifact = context.modelRouteTimeline || {};
  const finalSummary = context.finalSummary || {};
  const timeline = Array.isArray(artifact.timeline)
    ? artifact.timeline
    : Array.isArray(artifact.route_timeline)
      ? artifact.route_timeline
      : Array.isArray(finalSummary.model_route_timeline)
        ? finalSummary.model_route_timeline
        : [];
  if (timeline.length) return timeline.at(-1);
  const modelSelection = finalSummary.model_selection || context.status?.model_selection;
  return modelSelection && Object.keys(modelSelection).length ? modelSelection : null;
}

function modelRouteSummaryLine(context) {
  const route = latestRouteDecision(context);
  if (!route) return "- No model route timeline is recorded for this run yet.";
  return `- ${firstRuntimeText(route.purpose, "unknown")} used ${firstRuntimeText(route.selected_tier, route.tier, "unknown")}: ${firstRuntimeText(route.reason, route.model_selection_reason, "No reason recorded.")}`;
}

const CHAT_INTRO = `\u4f60\u597d\uff0c\u6211\u662f Asteria\u3002\u4f60\u53ef\u4ee5\u76f4\u63a5\u95ee\u95ee\u9898\u3001\u8ba9\u6211\u8981\u70b9\u5206\u6790\u3001\u5199\u4e00\u4efd\u8ba1\u5212\uff0c\u6216\u63cf\u8ff0\u4e00\u4e2a\u4f60\u60f3\u5b8c\u6210\u7684\u76ee\u6807\u3002`;

const CHAT_GREETING = `\u4f60\u597d\u3002\u76f4\u63a5\u544a\u8bc9\u6211\u4f60\u60f3\u89e3\u51b3\u4ec0\u4e48\u95ee\u9898\uff0c\u6211\u4f1a\u5148\u7ed9\u51fa\u81ea\u7136\u56de\u7b54\uff1b\u5982\u679c\u9700\u8981\u6267\u884c\u6216\u4fee\u6539\u5185\u5bb9\uff0c\u6211\u4f1a\u5728\u884c\u52a8\u524d\u8bf4\u660e\u5e76\u7b49\u5f85\u786e\u8ba4\u3002`;

const CHAT_HELP = `## \u53ef\u4ee5\u8fd9\u6837\u95ee\u6211\n\n- \u5e2e\u6211\u89e3\u91ca\u4e00\u4e2a\u6982\u5ff5\u3002\n- \u5e2e\u6211\u5236\u5b9a\u4e00\u4e2a\u65c5\u884c\u3001\u5b66\u4e60\u6216\u5199\u4f5c\u8ba1\u5212\u3002\n- \u5e2e\u6211\u5206\u6790\u4e00\u6bb5\u9700\u6c42\uff0c\u6574\u7406\u6210\u65b9\u6848\u3002\n- \u5e2e\u6211\u5224\u65ad\u4e0b\u4e00\u6b65\u600e\u4e48\u505a\u3002\n\n\u5982\u679c\u4f60\u7684\u8bf7\u6c42\u9700\u8981\u4fee\u6539\u6587\u4ef6\u3001\u8fd0\u884c\u547d\u4ee4\u6216\u957f\u671f\u6267\u884c\uff0c\u6211\u4f1a\u5148\u8bf4\u660e\u5f71\u54cd\uff0c\u518d\u8bf7\u6c42\u786e\u8ba4\u3002`;

const CHAT_MODES = `## \u4f7f\u7528\u65b9\u5f0f\n\n\u4f60\u4e0d\u9700\u8981\u5148\u7406\u89e3\u6a21\u5f0f\u3002\u76f4\u63a5\u8f93\u5165\u76ee\u6807\u5373\u53ef\uff1a\n\n- \u666e\u901a\u95ee\u9898\uff1a\u6211\u4f1a\u76f4\u63a5\u56de\u7b54\u3002\n- \u9700\u8981\u65b9\u6848\uff1a\u6211\u4f1a\u5148\u7ed9\u51fa\u53ea\u8bfb\u8ba1\u5212\u3002\n- \u9700\u8981\u6267\u884c\uff1a\u6211\u4f1a\u8bf4\u660e\u5c06\u8981\u505a\u4ec0\u4e48\uff0c\u5e76\u5728\u654f\u611f\u52a8\u4f5c\u524d\u8bf7\u6c42\u786e\u8ba4\u3002`;

const CHAT_ABOUT_CHAT = `\u53ef\u4ee5\u628a\u8fd9\u91cc\u5f53\u6210\u666e\u901a AI \u52a9\u624b\u5165\u53e3\u3002\u4f60\u5148\u63cf\u8ff0\u95ee\u9898\uff0c\u6211\u4f1a\u6839\u636e\u610f\u56fe\u51b3\u5b9a\u662f\u76f4\u63a5\u56de\u7b54\u3001\u6574\u7406\u8ba1\u5212\uff0c\u8fd8\u662f\u5efa\u8bae\u8fdb\u5165\u53ef\u63a7\u6267\u884c\u3002`;

const CHAT_EVIDENCE = `\u666e\u901a\u4f7f\u7528\u65f6\u4e0d\u9700\u8981\u67e5\u770b\u540e\u53f0\u7ec6\u8282\u3002\u4f60\u53ea\u9700\u8981\u770b\u8fd9\u91cc\u7684\u56de\u7b54\u3001\u8ba1\u5212\u3001\u786e\u8ba4\u8bf7\u6c42\u548c\u6700\u7ec8\u7ed3\u679c\u3002`;

async function handlePermission(sessionId, jobId, body) {
  const action = String(body?.action || "");
  if (action === "allow") {
    const pending = pendingJobs.get(jobId);
    if (!pending || pending.sessionId !== sessionId)
      return { ok: false, error: "job not found or session mismatch" };
    pendingJobs.delete(jobId);
    // Durable resolution marker: the confirm card is a one-shot prompt. Once resolved, readSessionEvents
    // drops the original waiting_user permission_request from the thread feed by this job_id, so a page
    // reload no longer re-renders a live allow/deny card whose job is already gone (M4 dead button).
    await appendEvent(sessionId, {
      type: "assistant_delta",
      status: "completed",
      title: "Approved",
      summary: "Approved \u2014 starting the task\u2026",
      phase: "execute",
      display_level: "main",
      resolved_job_id: jobId,
    });
    startRuntimeJob(sessionId, pending.mode, pending.goal, pending.command);
    return { ok: true, started: true };
  }
  if (action === "deny") {
    pendingJobs.delete(jobId);
    await appendEvent(sessionId, {
      type: "assistant_delta",
      status: "completed",
      title: "Canceled",
      summary: "Canceled \u2014 nothing was run.",
      phase: "next",
      display_level: "main",
      resolved_job_id: jobId,
    });
    return { ok: true, started: false };
  }
  return { ok: false, error: "invalid action, use allow or deny" };
}

/** Map user_progress channel → studio event type */
function channelToEventType(channel, eventType) {
  if (channel === "conclusion")
    return eventType === "message" ? "assistant_delta" : "reasoning_delta";
  if (channel === "model") return "reasoning_delta";
  if (channel === "tool") return "tool_start";
  if (channel === "execution_chain" && (eventType === "turn_start" || eventType === "turn_end"))
    return "agent_turn";
  if (channel === "execution_chain" && eventType === "tool_observation") return "tool_observation";
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
    if (!job) {
      stopped = true;
      return;
    }

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
                try {
                  return { path: p, mtime: (await fs.stat(p)).mtimeMs };
                } catch {
                  return null;
                }
              }),
            )
          ).filter(Boolean);
          const recent = withStats.filter((s) => s.mtime >= job.started_at_ms - 6000);
          if (recent.length) {
            recent.sort((a, b) => b.mtime - a.mtime);
            runDir = recent[0].path;
          }
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
                const mapped = userProgressToStudioEvent(evt, sessionId, path.basename(runDir));
                // Keep the namespaced event_id from userProgressToStudioEvent (runtime-<runId>-<upe>).
                // Overriding it back to the bare per-run upe-NNNN caused cross-run id collisions (front-end
                // dedup dropped run B's early events) and left this live copy un-dedupable against the replay re-read.
                void appendEvent(sessionId, {
                  ...mapped,
                  job_id: jobId,
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
  return () => {
    stopped = true;
  };
}

function sessionJobsPayload(sessionId) {
  const jobs = [...liveJobs.values()]
    .filter((job) => job.session_id === sessionId)
    .map((job) => ({
      job_id: job.job_id,
      status: job.status,
      mode: job.mode || null,
      run_id: job.run_id || null,
    }));
  return {
    ok: true,
    running: jobs.filter((job) => job.status === "running").length,
    jobs,
  };
}

function stopSessionJobs(sessionId) {
  if (!isSafeId(sessionId)) return { ok: false, error: "invalid session id" };
  const running = [...liveJobs.values()].filter(
    (job) => job.session_id === sessionId && job.status === "running",
  );
  if (!running.length) return { ok: false, error: "no running job" };
  let stopped = 0;
  for (const job of running) {
    job.cancelled = true;
    job.follow_up_mode = null; // suppress the queued follow-up so a stop does not auto-restart
    liveJobs.set(job.job_id, job);
    try {
      const child = job.child;
      if (!child) continue;
      if (process.platform === "win32" && job.pid) {
        // child.kill() signals only the immediate process; the Python runtime spawns its own
        // subtree, so tree-kill (taskkill /T /F) is required to actually stop the work on Windows.
        spawn("taskkill", ["/pid", String(job.pid), "/T", "/F"], { windowsHide: true });
      } else {
        child.kill("SIGTERM");
      }
      stopped += 1;
    } catch {}
  }
  return { ok: true, stopped };
}

// Autonomy follows the chosen permission tier: default tiers self-heal (auto repair/replan for the
// best hands-off experience); "Ask first" (ask_everything) stays supervised and surfaces a decision
// instead of auto-fixing. We set the run-loop rings in the workspace's OWN .asteria/policies.json —
// never the shared repo template — so the CLI default and the test suite are untouched. Best-effort:
// a read/write failure never blocks the run (it just falls back to the workspace's current policy).
async function applyAutonomyForTier(permissionTier) {
  const autonomous = permissionTier !== "ask_everything";
  const policyPath = path.join(workspace, ".asteria", "policies.json");
  try {
    const policy = JSON.parse(await fs.readFile(policyPath, "utf8"));
    const loop =
      policy.agent_loop && typeof policy.agent_loop === "object" ? policy.agent_loop : {};
    if (
      loop.auto_repair === autonomous &&
      loop.auto_replan === autonomous &&
      loop.auto_replan_goal === autonomous
    ) {
      return autonomous; // already in the desired state — skip the rewrite
    }
    loop.auto_repair = autonomous;
    loop.auto_replan = autonomous;
    loop.auto_replan_goal = autonomous;
    policy.agent_loop = loop;
    await fs.writeFile(policyPath, `${JSON.stringify(policy, null, 2)}\n`, "utf8");
    return autonomous;
  } catch {
    return null; // never block a run on a policy patch
  }
}

function startRuntimeJob(sessionId, mode, goal, commandOverride = null, options = {}) {
  pruneLiveJobs();
  const command =
    Array.isArray(commandOverride) && commandOverride.length
      ? commandOverride
      : runtimeCommand(mode, goal);
  const jobId = `job-${Date.now()}`;
  const job = {
    job_id: jobId,
    session_id: sessionId,
    status: "running",
    mode,
    command,
    started_at_ms: Date.now(),
    run_id: null,
    follow_up_mode: options.followUpMode || null,
  };
  liveJobs.set(jobId, job);

  void appendEvent(sessionId, {
    type: "tool_start",
    status: "running",
    title: "Processing started",
    summary: "Processing started.",
    display_level: "inspector",
    command,
  });

  const stopTail = tailUserProgress(sessionId, jobId);

  const child = spawn(command[0], command.slice(1), {
    cwd: runtimeRoot,
    env: {
      ...process.env,
      ASTERIA_STUDIO_EVENT_SINK: sessionPath(sessionId, "events.jsonl"),
      ASTERIA_STUDIO_SESSION_ID: sessionId,
      ASTERIA_STUDIO_PHASE: phaseForMode(mode),
      PYTHONIOENCODING: "utf-8",
    },
    windowsHide: true,
  });
  // Keep the child handle + pid reachable by job so a stop route can terminate a running run.
  job.child = child;
  job.pid = child.pid;
  liveJobs.set(jobId, job);

  let stdout = "";
  let stderr = "";
  child.stdout.on("data", (chunk) => {
    const text = redactText(chunk.toString("utf8"));
    stdout = tailText(stdout + text, 24000);
    rememberJobRunId(jobId, extractRunId(text) || extractRunId(stdout));
    void appendEvent(sessionId, {
      type: "tool_delta",
      status: "running",
      title: "Runtime output",
      summary: summarizeRuntimeChunk(text),
      content_delta: text,
      display_level: "inspector",
      command,
    });
  });
  child.stderr.on("data", (chunk) => {
    const text = redactText(chunk.toString("utf8"));
    stderr = tailText(stderr + text, 16000);
    rememberJobRunId(jobId, extractRunId(text) || extractRunId(stderr));
    void appendEvent(sessionId, {
      type: "tool_delta",
      status: "running",
      title: "Runtime diagnostics",
      summary: summarizeRuntimeChunk(text),
      content_delta: text,
      display_level: "inspector",
      command,
    });
  });
  child.on("close", async (code) => {
    stopTail();
    job.child = null;
    // User stop: report an honest "stopped" outcome and suppress the "needs attention" final +
    // the queued follow-up (already cleared on stop). Do not dress a user cancel up as a failure.
    if (job.cancelled) {
      job.status = "cancelled";
      liveJobs.set(jobId, job);
      void appendEvent(sessionId, {
        type: "tool_end",
        status: "failed",
        title: "Stopped",
        summary: "Stopped by user.",
        command,
        display_level: "main",
        content_delta:
          "Stopped by user before completion. Open the Inspector to review any partial work.",
        job_id: jobId,
      });
      return;
    }
    rememberJobRunId(jobId, extractRunId(stdout) || extractRunId(stderr));
    job.status = code === 0 ? "completed" : "failed";
    liveJobs.set(jobId, job);
    const completedRunId = job.run_id || extractRunId(stdout) || extractRunId(stderr);
    void appendEvent(sessionId, {
      type: "tool_end",
      status: job.status,
      title: code === 0 ? "Processing completed" : "Processing needs attention",
      summary:
        code === 0
          ? "Processing completed; preparing the result."
          : "The task needs attention; preparing the reason and next step.",
      command,
      display_level: "inspector",
      run_id: completedRunId || undefined,
      content_delta: stderr
        ? `stderr:
${stderr}`
        : stdout.slice(-4000),
    });
    const userProgressRows = completedRunId ? await readRunUserProgress(completedRunId) : [];
    const mainFinal = latestMainFinalEvent(userProgressRows);
    if (mainFinal) {
      const mapped = userProgressToStudioEvent(mainFinal, sessionId, completedRunId || "");
      // Keep the namespaced event_id (see live-tail note above) so this persisted final dedups
      // cleanly against the runtime re-read instead of appearing twice.
      void appendEvent(sessionId, {
        ...mapped,
        job_id: jobId,
      });
    } else {
      // ADR-0012: when the runtime emitted no main-thread conversational final, do NOT synthesize the
      // diagnostic report as the reply. Show an honest short line and point to the Inspector for detail.
      const honest =
        code === 0
          ? "Finished. Open the Inspector to review what changed and the verification details."
          : friendlyErrorText(stderr || stdout) ||
            "The task needs attention — open the Inspector for the reason and next step.";
      void appendEvent(sessionId, {
        type: code === 0 ? "final_answer" : "error",
        status: code === 0 ? "completed" : "failed",
        title: code === 0 ? "Result" : "Needs attention",
        summary:
          code === 0
            ? "Result prepared."
            : "The task needs attention; here is the reason and suggestion.",
        phase: code === 0 ? "result" : "review",
        display_level: "main",
        content_delta: honest,
        evidence_refs: [sessionPath(sessionId, "events.jsonl")],
        artifact_refs: runArtifactRefs(completedRunId),
        run_id: completedRunId || undefined,
        job_id: jobId,
        data: code === 0 ? undefined : { error_category: friendlyErrorCategory(stderr || stdout) },
      });
    }
    const followUpMode = job.follow_up_mode;
    if (code === 0 && followUpMode) {
      const followUp = runtimeActionByKind(followUpMode);
      if (followUp) {
        startRuntimeJob(sessionId, followUp.mode, followUp.goal, followUp.command);
      }
    }
  });
  child.on("error", (error) => {
    stopTail();
    job.status = "failed";
    liveJobs.set(jobId, job);
    const rawError = String(error);
    const friendly = friendlyErrorText(rawError);
    void appendEvent(sessionId, {
      type: "error",
      status: "failed",
      title: friendlyErrorTitle(rawError) || "Task failed to start",
      summary: friendlyErrorSummary(rawError) || rawError,
      content_delta: friendly || redactText(rawError),
      command,
      run_id: job.run_id || undefined,
    });
  });
}

async function finalTextFor(mode, code, stdout, stderr) {
  if (code !== 0) {
    return [
      "## \u7ed3\u679c",
      "\u8fd9\u6b21\u4efb\u52a1\u6ca1\u6709\u987a\u5229\u5b8c\u6210\u3002",
      "",
      "## \u53ef\u80fd\u539f\u56e0",
      summarizeUserFacingFailure(stderr || stdout),
      "",
      "## \u4e0b\u4e00\u6b65",
      "\u4f60\u53ef\u4ee5\u8ba9\u6211\u91cd\u8bd5\u3001\u7f29\u5c0f\u8303\u56f4\uff0c\u6216\u5148\u91cd\u65b0\u5236\u5b9a\u8ba1\u5212\u3002",
    ].join("\n");
  }
  const runId = extractRunId(stdout) || extractRunId(stderr);
  if (mode === "plan" && runId) return await planFinalTextForRun(runId, stdout);
  if ((mode === "run" || mode === "continue" || mode === "resume") && runId)
    return withProcessDigest(runId, await runFinalTextForRun(runId, stdout));
  if (mode === "review" && runId)
    return withProcessDigest(runId, await reviewFinalTextForRun(runId, stdout));
  const text = cleanUserFacingRuntimeText(stdout);
  const result = text || "The task finished, but there was no clear user-facing result to show.";
  return ["## \u7ed3\u679c", result, "", "## \u4e0b\u4e00\u6b65", nextStepForMode(mode)].join("\n");
}

function summarizeUserFacingFailure(text) {
  const clean = cleanUserFacingRuntimeText(text);
  const friendly = friendlyErrorText(text) || friendlyErrorText(clean);
  if (friendly) return friendly;
  if (!clean) return "The task did not provide enough readable detail to explain the failure.";
  if (/timeout|deadline|timed out/i.test(clean))
    return "The task appears to have timed out before finishing.";
  if (/permission|denied|not allowed/i.test(clean))
    return "The task needs permission or policy approval before it can continue.";
  if (/traceback|exception|error|failed/i.test(clean))
    return "The task hit an execution error and needs a smaller retry or debugging step.";
  return clean.slice(0, 800);
}

function cleanUserFacingRuntimeText(text) {
  return String(text || "")
    .replace(/stderr:\s*/gi, "")
    .replace(/\b(run-\d{8}-\d{4})\b/g, "")
    .replace(
      /.*(?:Inspector|Evidence Explorer|status --json|stdout|stderr|traceback path|\.asteria).*/gi,
      "",
    )
    .trim();
}

function nextStepForMode(mode) {
  if (mode === "plan") return "Review the plan and tell me what to refine or execute next.";
  if (mode === "run") return "Review the result, then ask me to continue, revise, or summarize.";
  if (mode === "review") return "Use the review result to decide whether to accept or revise.";
  if (mode === "resume") return "Check the latest result and decide whether to continue.";
  if (mode === "accept")
    return "The reviewed result is accepted; continue with the next goal when ready.";
  if (mode === "debug") return "Use the repair result to continue, ask for help, or stop cleanly.";
  if (mode === "decide") return "Choose one pending decision, then continue the runtime goal.";
  return "Tell me what you want to do next.";
}

async function userProgressDigestLines(runId) {
  const runDir = path.join(workspace, ".asteria", "runs", runId);
  const events = await readJsonlTail(path.join(runDir, "user_progress.jsonl"), 1200);
  const counts = { model: 0, tool: 0, file: 0, evidence: 0, execution_chain: 0 };
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
  if (counts.model) lines.push("- I analyzed the request and prepared the response.");
  if (counts.tool || counts.execution_chain)
    lines.push("- I checked the relevant steps before producing the result.");
  if (counts.file) {
    const names = fileNames.slice(0, 4).join(", ");
    lines.push(`- I updated: ${names || "the requested files"}.`);
  }
  if (counts.evidence) lines.push("- I kept verification details available for debugging.");
  return lines.length ? [...new Set(lines)] : ["- I completed the requested step."];
}

function userProgressChannelToEventType(channel, eventType, phase) {
  if (channel === "conclusion" && phase === "result") return "final_answer";
  if (channel === "execution_chain" && (eventType === "turn_start" || eventType === "turn_end"))
    return "agent_turn";
  if (channel === "execution_chain" && eventType === "tool_observation") return "tool_observation";
  return channelToEventType(channel, eventType);
}

async function withProcessDigest(runId, text) {
  const digest = await userProgressDigestLines(runId);
  const body = String(text || "").trim();
  return [body, "", "## Process summary", digest.join("\n")].filter(Boolean).join("\n");
}

async function planFinalTextForRun(runId, fallbackStdout) {
  const runDir = path.join(workspace, ".asteria", "runs", runId);
  const goalSpec = await readJson(path.join(runDir, "goal_spec.json"));
  const taskPlan = await readJson(path.join(runDir, "task_plan.json"));
  const taskEval = await readJson(path.join(runDir, "task_plan_eval.json"));
  const tasks = Array.isArray(taskPlan.tasks) ? taskPlan.tasks : [];
  if (!Object.keys(goalSpec).length && !tasks.length) {
    return [
      "## Plan result",
      cleanUserFacingRuntimeText(fallbackStdout) ||
        "I could not produce a complete plan from the available information.",
      "",
      "## Next step",
      "Share the missing constraints or ask me to create a smaller first version.",
    ].join("\n");
  }
  const goal = firstRuntimeText(
    goalSpec.normalized_goal,
    goalSpec.original_goal,
    "the requested goal",
  );
  const warnings = Array.isArray(taskEval.issues)
    ? taskEval.issues.filter((issue) => issue.severity !== "error")
    : [];
  const recommendations = Array.isArray(taskEval.recommendations) ? taskEval.recommendations : [];
  const taskLines = tasks.slice(0, 6).map((task, index) => {
    const title = firstRuntimeText(task.title, task.task_id, `Step ${index + 1}`);
    const description = firstRuntimeText(task.description).replace(/\s+/g, " ");
    const acceptance = Array.isArray(task.acceptance) ? task.acceptance.slice(0, 2) : [];
    return [
      `- ${title}`,
      description ? `  Why: ${description}` : "",
      acceptance.length ? `  Done when: ${acceptance.join("; ")}` : "",
    ]
      .filter(Boolean)
      .join("\n");
  });
  const riskLines = [
    ...warnings.slice(0, 3).map((issue) => `- ${firstRuntimeText(issue.message, issue.code)}`),
    ...recommendations.slice(0, 3).map((item) => `- ${item}`),
  ];
  return [
    "## Plan result",
    `Goal: ${goal}`,
    "",
    "## Recommended work plan",
    taskLines.length
      ? taskLines.join("\n")
      : "- Start by clarifying the goal, constraints, and success criteria.",
    "",
    "## Notes and tradeoffs",
    riskLines.length
      ? [...new Set(riskLines)].join("\n")
      : "- Keep the first version small enough to review, then expand after feedback.",
    "",
    "## Next step",
    nextPlanAction(tasks, taskEval),
  ].join("\n");
}

function nextPlanAction(tasks, taskEval) {
  const status = String(taskEval.status || "").toLowerCase();
  if (status === "warn") return "Review the assumptions and adjust the plan before execution.";
  if (tasks.length > 1)
    return "Choose the first task you want to execute, or ask me to refine the plan.";
  return "Confirm this plan or ask for a narrower version before execution.";
}

/** Build final text for run/resume modes — reads final_report.md and eval_report.json */
async function runFinalTextForRun(runId, fallbackStdout) {
  const runDir = path.join(workspace, ".asteria", "runs", runId);
  const goalSpec = await readJson(path.join(runDir, "goal_spec.json"));
  const taskPlan = await readJson(path.join(runDir, "task_plan.json"));
  const runJson = await readJson(path.join(runDir, "run.json"));
  const evalReport = await readJson(path.join(runDir, "eval_report.json"));
  const validationResults = await readJsonlTail(path.join(runDir, "validation_results.jsonl"), 30);
  const decisions = await readJsonlTail(path.join(runDir, "decisions.jsonl"), 20);
  const taskRows = Array.isArray(taskPlan.tasks) ? taskPlan.tasks : [];
  const doneTasks = taskRows.filter((task) => task.status === "done");
  const blockedTasks = taskRows.filter((task) => task.status === "blocked");
  const pendingDecisions = decisions.filter((decision) => decision.status === "pending");
  const status = firstRuntimeText(runJson.status, evalReport?.overall?.status, "completed");
  const reason = firstRuntimeText(evalReport?.overall?.reason);
  const artifactLines = await runArtifactLines(runDir);
  const validationLines = validationResults.slice(-5).map((item) => {
    const label = firstRuntimeText(item.name, item.command, item.validation_result_id, "???");
    const itemStatus = firstRuntimeText(item.status, item.outcome, "unknown");
    const summary = firstRuntimeText(item.summary, item.error, "");
    return `- ${label}: ${friendlyCheckStatus(itemStatus)}${summary ? ` - ${summary}` : ""}`;
  });
  const answerLine = runAnswerLine({
    goal: firstRuntimeText(goalSpec.normalized_goal, goalSpec.original_goal, runJson.goal, "????"),
    status,
    done: doneTasks.length,
    total: taskRows.length,
    blocked: blockedTasks.length,
    decisions: pendingDecisions.length,
  });
  return [
    "## ??",
    answerLine,
    "",
    "## ????",
    `- ???${friendlyRunStatus(status)}`,
    `- ???${doneTasks.length}/${taskRows.length || doneTasks.length} ???${blockedTasks.length ? `?${blockedTasks.length} ?????` : ""}`,
    pendingDecisions.length ? `- ??????${pendingDecisions.length} ?` : "- ??????????",
    reason ? `- ???${reason}` : "",
    "",
    ...(artifactLines.length ? ["## ??", ...artifactLines, ""] : []),
    ...(validationLines.length ? ["## ????", ...validationLines, ""] : []),
    "## ???",
    nextRunAction({ status, blocked: blockedTasks.length, decisions: pendingDecisions.length }),
  ]
    .filter(Boolean)
    .join("\n");
}

function friendlyCheckStatus(status) {
  const text = String(status || "").toLowerCase();
  if (/pass|ok|success|completed/.test(text)) return "??";
  if (/fail|error|blocked/.test(text)) return "???";
  if (/skip/.test(text)) return "???";
  return status || "??";
}

function friendlyRunStatus(status) {
  const text = String(status || "").toLowerCase();
  if (/completed|success|accepted|pass/.test(text)) return "???";
  if (/blocked|paused|decision|waiting/.test(text)) return "????";
  if (/failed|error/.test(text)) return "???";
  if (/running|progress/.test(text)) return "???";
  return status || "??";
}

/** Build final text for review mode — reads review_report.md and eval_report.json */
async function reviewFinalTextForRun(runId, fallbackStdout) {
  const runDir = path.join(workspace, ".asteria", "runs", runId);
  const evalReport = await readJson(path.join(runDir, "eval_report.json"));
  const status = firstRuntimeText(evalReport?.overall?.status, "reviewed");
  const score =
    evalReport?.overall?.score != null ? Number(evalReport.overall.score).toFixed(2) : null;
  const reason = firstRuntimeText(evalReport?.overall?.reason);
  const reviewMdPath = path.join(runDir, "review_report.md");
  let reviewBody = "";
  if (existsSync(reviewMdPath)) {
    try {
      reviewBody = cleanUserFacingRuntimeText(await fs.readFile(reviewMdPath, "utf8"));
    } catch {}
  }
  const lines = [
    "## ????",
    `?????${friendlyRunStatus(status)}${score ? `??? ${score}?` : ""}`,
    reason ? `???${reason}` : "",
    "",
  ];
  if (reviewBody.length > 80) lines.push(reviewBody.slice(0, 3000), "");
  else lines.push(cleanUserFacingRuntimeText(fallbackStdout) || "??????????????????", "");
  lines.push("## ???", nextStepForMode("review"));
  return lines.filter(Boolean).join("\n");
}

async function readWorkerSummaryLines(runDir) {
  const workersPath = path.join(runDir, "worker_results.jsonl");
  if (!existsSync(workersPath)) return [];
  try {
    const lines = (await fs.readFile(workersPath, "utf8")).split(/\r?\n/).filter(Boolean);
    return lines
      .slice(0, 5)
      .map((line) => {
        try {
          const w = JSON.parse(line);
          const id = firstRuntimeText(w.task_id, w.worker_id, "task");
          const st = firstRuntimeText(w.status, "?");
          const note = firstRuntimeText(w.summary, w.result_summary, "");
          return `- ${id}: ${st}${note ? " — " + note.slice(0, 80) : ""}`;
        } catch {
          return null;
        }
      })
      .filter(Boolean);
  } catch {
    return [];
  }
}

async function runArtifactLines(runDir) {
  const artifacts = await readJsonlTail(path.join(runDir, "artifacts.jsonl"), 20);
  return artifacts.slice(-8).map((item) => {
    const artifactPath = firstRuntimeText(item.path, item.artifact_id, "??");
    const summary = firstRuntimeText(item.summary, item.type, "");
    const name = path.basename(String(artifactPath || "??"));
    return `- ${name}${summary ? `?${summary}` : ""}`;
  });
}

function runAnswerLine({ goal, status, done, total, blocked, decisions }) {
  if (decisions > 0) {
    return `?${goal}?????????????????? ${done}/${total || done} ???? ${decisions} ??????????????`;
  }
  if (blocked > 0 || /blocked|paused|failed/i.test(status)) {
    return `?${goal}????????????? ${done}/${total || done} ???? ${blocked} ?????????`;
  }
  return `?${goal}????????? ${done}/${total || done} ?????????`;
}

function nextRunAction({ status, blocked, decisions }) {
  if (decisions > 0) return "?????????????????????";
  if (blocked > 0 || /blocked|paused|failed/i.test(String(status))) {
    return "????????????????????????";
  }
  return "?????????????????????????????????????????";
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
    path.join(workspace, ".asteria", "runs", runId, "cost_report.json"),
  ];
}

function firstRuntimeText(...items) {
  for (const item of items) {
    const text = String(item ?? "").trim();
    if (text) return text;
  }
  return "";
}

function nonEmptyRecord(value) {
  return (
    value && typeof value === "object" && !Array.isArray(value) && Object.keys(value).length > 0
  );
}

function trimForUser(text) {
  const clean = String(text || "").trim();
  if (!clean) return "";
  return clean.length > 8000 ? clean.slice(-8000) : clean;
}

async function readBackgroundRuns() {
  const registryPath = path.join(workspace, ".asteria", "background_run_registry.json");
  const registry = await readJson(registryPath);
  const runs = Array.isArray(registry?.runs) ? registry.runs : [];
  const running = runs.filter((item) => item?.status === "starting" || item?.status === "running");
  const latest = runs.length ? runs[runs.length - 1] : null;
  return {
    enabled: true,
    local_subprocess: true,
    cloud_vm: false,
    running_count: running.length,
    total_count: runs.length,
    badge_status: running.length ? "running" : latest?.status || "idle",
    badge_summary: running.length
      ? `${running.length} local background run(s) active.`
      : "No local background runs active.",
    latest,
    running: running.slice(0, 5),
    registry_path: ".asteria/background_run_registry.json",
  };
}

async function overview() {
  const [runs, modelRoutes, v0_2_rolling_validation, background_runs, doctor] = await Promise.all([
    readRuns(),
    modelRouteSummary(),
    latestV02RollingValidation(),
    readBackgroundRuns(),
    // Provider readiness at first load (tier configured/missing env-vars/next actions) so the
    // Settings "Model & provider" panel is not a dead-end before any task has run. doctor is a
    // local env-var check (no network), and we tolerate failure rather than block the bootstrap.
    commandJson(["doctor", "--root", workspace, "--json"]).catch(() => ({})),
  ]);
  return {
    ok: true,
    workspace,
    runtimeRoot,
    diagnostics_loaded: false,
    gateStatus: {},
    v0_2_rolling_validation,
    doctor,
    packageCheck: {},
    runs: runs.slice(0, 10),
    modelRoutes,
    background_runs,
  };
}

async function diagnostics() {
  const [gateStatus, doctor, packageCheck, modelRoutes, statusPayload] = await Promise.all([
    commandJson(["gate-status", "--root", workspace, "--json"]),
    commandJson(["doctor", "--root", workspace, "--json"]),
    commandJson(["package-check", "--root", runtimeRoot, "--json"]),
    modelRouteSummary(),
    commandJson(["status", "--root", workspace, "--json"]).catch(() => ({})),
  ]);
  return {
    ok: true,
    workspace,
    runtimeRoot,
    diagnostics_loaded: true,
    gateStatus,
    v0_2_rolling_validation: nonEmptyRecord(gateStatus?.v0_2_rolling_validation)
      ? gateStatus.v0_2_rolling_validation
      : await latestV02RollingValidation(),
    doctor,
    packageCheck,
    modelRoutes,
    long_horizon: statusPayload?.long_horizon ?? {},
    background_runs: statusPayload?.background_runs ?? (await readBackgroundRuns()),
    workflow: {
      can_review: Boolean(statusPayload?.can_review),
      can_accept: Boolean(statusPayload?.can_accept),
      workflow_state: String(statusPayload?.workflow_state ?? ""),
      recommended_next_command: String(statusPayload?.recommended_next_command ?? ""),
      next_actions: Array.isArray(statusPayload?.next_actions) ? statusPayload.next_actions : [],
    },
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
    updated_at: now,
  };
  await fs.mkdir(sessionPath(sessionId), { recursive: true });
  await fs.writeFile(
    sessionPath(sessionId, "session.json"),
    JSON.stringify(session, null, 2),
    "utf8",
  );
  // No seed/welcome event: a brand-new session must stay empty so the thread renders the EmptyState
  // ("What would you like to do?" + example prompts). A main-level greeting event here made every new
  // conversation non-empty, which rendered a stray assistant turn AND dragged in the workspace-level
  // review/next-action bar \u2014 the confusing "review line at the top of a new chat".
  return session;
}

async function ensureSession(sessionId) {
  if (!isSafeId(sessionId)) return createSession();
  const loaded = await readSession(sessionId);
  if (loaded.ok) {
    const session = loaded.session;
    if (!session.session_id) session.session_id = sessionId;
    if (!session.workspace) session.workspace = workspace;
    return session;
  }
  return createSession();
}

function resolvedSessionId(session, sessionId) {
  return String(session?.session_id || sessionId || "").trim();
}

async function readSession(sessionId) {
  if (!isSafeId(sessionId)) return { ok: false, error: "invalid session id" };
  const file = sessionPath(sessionId, "session.json");
  if (!existsSync(file)) return { ok: false, error: "session not found" };
  try {
    const raw = await fs.readFile(file, "utf8");
    if (!raw.trim()) return { ok: false, error: "empty session" };
    return { ok: true, session: JSON.parse(raw), events: await readSessionEvents(sessionId) };
  } catch (error) {
    return { ok: false, error: String(error?.message || error) };
  }
}

async function deleteSession(sessionId, { purge = false } = {}) {
  if (!isSafeId(sessionId)) return { ok: false, error: "invalid session id" };
  const dir = sessionPath(sessionId);
  if (!existsSync(dir)) return { ok: false, error: "session not found" };
  if (purge) {
    // Permanent removal — only reached via explicit ?purge=1 (a future trash view), never the
    // default delete click. Honest destructive path kept available, but gated behind an opt-in flag.
    await fs.rm(dir, { recursive: true, force: true });
    return { ok: true, deleted: sessionId, purged: true };
  }
  // Soft delete (reversible): mark deleted_at so listSessions hides it, but keep session.json +
  // events.jsonl intact so an accidental delete of a long-task session can be undone. A long task
  // is expensive to lose; instant hard-delete on a stray click is the exact failure to prevent.
  const file = sessionPath(sessionId, "session.json");
  let session = { session_id: sessionId };
  try {
    const raw = await fs.readFile(file, "utf8");
    if (raw.trim()) session = JSON.parse(raw);
  } catch {
    session = { session_id: sessionId };
  }
  session.deleted_at = new Date().toISOString();
  await fs.writeFile(file, JSON.stringify(session, null, 2), "utf8");
  return { ok: true, deleted: sessionId, soft_deleted: true };
}

async function restoreSession(sessionId) {
  if (!isSafeId(sessionId)) return { ok: false, error: "invalid session id" };
  const file = sessionPath(sessionId, "session.json");
  if (!existsSync(file)) return { ok: false, error: "session not found" };
  let session = {};
  try {
    session = JSON.parse(await fs.readFile(file, "utf8"));
  } catch {
    return { ok: false, error: "session unreadable" };
  }
  // Clear the marker without touching updated_at, so the session slots back into its original
  // position in the list (undo = put it back exactly, not bump to the top).
  delete session.deleted_at;
  await fs.writeFile(file, JSON.stringify(session, null, 2), "utf8");
  return { ok: true, session, restored: sessionId };
}

// Backup (I10b): a session bundle is its session.json + the RAW events.jsonl lines (not the
// assembled/merged view) so a re-import reproduces exactly what was stored. Events are already
// redacted at write time, so the bundle carries no fresh secrets.
async function exportSessionBundle(sessionId) {
  const loaded = await readSession(sessionId);
  if (!loaded.ok) return { ok: false, error: loaded.error };
  const eventsFile = sessionPath(sessionId, "events.jsonl");
  let events = [];
  if (existsSync(eventsFile)) {
    events = (await fs.readFile(eventsFile, "utf8"))
      .split(/\r?\n/)
      .filter(Boolean)
      .map((line) => {
        try {
          return JSON.parse(line);
        } catch {
          return null;
        }
      })
      .filter(Boolean);
  }
  const bundle = {
    asteria_session_bundle: "0.1.0",
    exported_at: new Date().toISOString(),
    session: loaded.session,
    events,
  };
  return { ok: true, bundle, session_id: loaded.session.session_id || sessionId };
}

async function importSessionBundle(body) {
  const bundle = body?.bundle && typeof body.bundle === "object" ? body.bundle : body;
  if (!bundle || typeof bundle !== "object") return { ok: false, error: "invalid bundle" };
  const src = bundle.session && typeof bundle.session === "object" ? bundle.session : {};
  const events = Array.isArray(bundle.events) ? bundle.events : [];
  if (!src && !events.length) return { ok: false, error: "bundle has no session or events" };
  const sessionId = `session-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`;
  const now = new Date().toISOString();
  const session = {
    schema_version: "0.1.0",
    session_id: sessionId,
    title: String(src.title || "Imported session").slice(0, 120),
    workspace,
    created_at: now,
    updated_at: now,
    imported_from: src.session_id ? String(src.session_id) : null,
    imported_at: now,
  };
  if (src.goal_preview) session.goal_preview = String(src.goal_preview).slice(0, 160);
  await fs.mkdir(sessionPath(sessionId), { recursive: true });
  await fs.writeFile(
    sessionPath(sessionId, "session.json"),
    JSON.stringify(session, null, 2),
    "utf8",
  );
  if (events.length) {
    // Re-stamp session_id so the imported events belong to the new session; keep everything else
    // (event_id, timestamps, content) verbatim for a faithful restore.
    const lines = events
      .filter((ev) => ev && typeof ev === "object")
      .map((ev) => JSON.stringify({ ...ev, session_id: sessionId }))
      .join("\n");
    await fs.writeFile(sessionPath(sessionId, "events.jsonl"), lines ? `${lines}\n` : "", "utf8");
  }
  return { ok: true, session, imported: events.length };
}

async function updateSession(sessionId, body) {
  if (!isSafeId(sessionId)) return { ok: false, error: "invalid session id" };
  const file = sessionPath(sessionId, "session.json");
  if (!existsSync(file)) return { ok: false, error: "session not found" };
  let session = {};
  try {
    session = JSON.parse(await fs.readFile(file, "utf8"));
  } catch {
    return { ok: false, error: "session unreadable" };
  }
  if (body?.title) session.title = String(body.title).slice(0, 120);
  if (body?.goal_preview) session.goal_preview = String(body.goal_preview).slice(0, 160);
  if (body?.ui_state && typeof body.ui_state === "object") {
    session.ui_state = { ...(session.ui_state || {}), ...body.ui_state };
  }
  session.updated_at = new Date().toISOString();
  await fs.writeFile(file, JSON.stringify(session, null, 2), "utf8");
  return { ok: true, session };
}

async function listSessions() {
  const root = path.join(workspace, ".asteria", "studio", "sessions");
  if (!existsSync(root)) return [];
  const entries = await fs.readdir(root, { withFileTypes: true });
  const sessions = [];
  for (const entry of entries) {
    if (!entry.isDirectory()) continue;
    const loaded = await readSession(entry.name);
    // Soft-deleted sessions stay on disk (recoverable) but are hidden from the main list.
    if (loaded.ok && !loaded.session.deleted_at) sessions.push(loaded.session);
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
    ...redact(event),
  };
  await fs.mkdir(sessionPath(sessionId), { recursive: true });
  await fs.appendFile(sessionPath(sessionId, "events.jsonl"), `${JSON.stringify(full)}\n`, "utf8");
  const sessionFile = sessionPath(sessionId, "session.json");
  if (existsSync(sessionFile)) {
    let session = {};
    try {
      const rawSession = await fs.readFile(sessionFile, "utf8");
      session = rawSession.trim() ? JSON.parse(rawSession) : {};
    } catch {
      session = {};
    }
    session.session_id = sessionId;
    session.workspace = session.workspace || workspace;
    session.updated_at = full.created_at;
    if (full.type === "user_message") {
      session.title = String(full.summary || session.title || "New task").slice(0, 64);
      session.goal_preview = String(
        full.content_delta || full.summary || session.goal_preview || "",
      ).slice(0, 160);
    }
    await fs.writeFile(sessionFile, JSON.stringify(session, null, 2), "utf8");
  }
  notifySSE(sessionId, full);
  return full;
}

async function readSessionEvents(sessionId) {
  if (!isSafeId(sessionId)) return [];
  const file = sessionPath(sessionId, "events.jsonl");
  if (!existsSync(file)) return [];
  let events = (await fs.readFile(file, "utf8"))
    .split(/\r?\n/)
    .filter(Boolean)
    .map((line) => {
      try {
        return redact(JSON.parse(line));
      } catch {
        return { type: "raw", content_delta: redactText(line) };
      }
    });
  // M4: a job-based permission confirm card is a one-shot prompt. Once its job resolved (allow/deny
  // recorded a resolved_job_id marker), drop the original waiting_user permission_request from the
  // thread feed — the "Approved/Canceled" delta already narrates the outcome, and leaving the raw
  // request in place made a reload re-render a live allow/deny card whose job was already gone (a dead
  // button that reported nothing when clicked). The raw event stays in events.jsonl for audit.
  const resolvedJobIds = new Set(
    events.map((event) => event && event.resolved_job_id).filter(Boolean),
  );
  if (resolvedJobIds.size) {
    events = events.filter(
      (event) =>
        !(event.type === "permission_request" && event.job_id && resolvedJobIds.has(event.job_id)),
    );
  }
  const runIds = new Set();
  for (const event of events) {
    if (event.type !== "final_answer" || event.phase === "chat") continue;
    const runId =
      extractRunId(event.content_delta) || extractRunId((event.artifact_refs || []).join("\n"));
    if (!runId) continue;
    runIds.add(runId);
    // ADR-0012: the main-thread final is the runtime's own conversational transcript text. Do NOT
    // overwrite it with the synthesized diagnostic report (final_report.md / eval_report.json) — that
    // content is diagnostics and belongs in the Inspector. Only attach artifact_refs so the Inspector
    // can resolve the run's evidence.
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
  const jobs = [...liveJobs.values()].filter(
    (job) => job.session_id === sessionId && job.status === "running",
  );
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
  const events = rows
    .map((event) => userProgressToStudioEvent(event, sessionId, runId))
    .filter(Boolean);
  for (const event of events) {
    if (event.type !== "final_answer" || event.phase === "chat") continue;
    await enrichFinalAnswerEvent(event, runId);
  }
  return events;
}

async function enrichFinalAnswerEvent(event, runId) {
  // ADR-0012: keep the runtime's conversational final text verbatim; only attach artifact_refs so the
  // Inspector can resolve the run's diagnostics. Never rewrite the main-thread answer into the report.
  event.artifact_refs = [...(event.artifact_refs || []), ...runArtifactRefs(runId)];
}

function mergeSessionAndRuntimeEvents(sessionEvents, runtimeEvents) {
  const runtimeTypes = new Set(runtimeEvents.map((event) => event.type));
  const runtimeIds = new Set(runtimeEvents.map((event) => event.event_id).filter(Boolean));
  const replaceable = new Set([
    "model_start",
    "model_delta",
    "model_end",
    "model_error",
    "file_changed",
  ]);
  // Dedup the authoritative runtime re-read against the session-persisted live-tail copy by id.
  // Live-tail copies now share the runtime-<runId>-<upe> namespace, so this removes the duplicate
  // tool_start / final_answer / tool_observation rows that the id-less type filter left behind.
  const isRuntimeDuplicate = (id) => {
    if (!id) return false;
    if (runtimeIds.has(id)) return true;
    // Legacy sessions persisted bare upe-NNNN before namespacing; treat a bare id as a duplicate of
    // any namespaced runtime id that ends with it so replaying old sessions does not double up.
    if (/^upe-\d+$/.test(id)) {
      for (const rid of runtimeIds) {
        if (rid.endsWith(`-${id}`)) return true;
      }
    }
    return false;
  };
  const filteredSessionEvents = sessionEvents.filter((event) => {
    if (isRuntimeDuplicate(event.event_id)) return false;
    if (!replaceable.has(event.type)) return true;
    return !runtimeTypes.has(event.type);
  });
  return [...filteredSessionEvents, ...runtimeEvents].sort((a, b) =>
    String(a.created_at || "").localeCompare(String(b.created_at || "")),
  );
}

function userProgressToStudioEvent(event, sessionId, runId) {
  const channel = String(event.channel || "");
  const eventType = String(event.event_type || "");
  const transcriptKind = String(event.transcript_kind || "");
  let type = "reasoning_delta";
  if (transcriptKind === "final" || transcriptKind === "stop") {
    type = "final_answer";
  } else if (transcriptKind === "tool_use") {
    type = "tool_start";
  } else if (transcriptKind === "tool_result") {
    type = "tool_end";
  } else if (transcriptKind === "file_change") {
    type = "file_changed";
  } else if (transcriptKind === "verification") {
    type = "tool_observation";
  } else if (transcriptKind === "permission_request") {
    type = "permission_request";
  } else if (channel === "model") {
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
  } else if (channel === "execution_chain") {
    if (eventType === "turn_start" || eventType === "turn_end") type = "agent_turn";
    else type = eventType === "tool_observation" ? "tool_observation" : "reasoning_delta";
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
    data: event.data || {},
    tool_call_id: event.tool_call_id,
    parent_event_id: event.parent_event_id,
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
    transcript_kind: transcriptKind,
    ui_intent: event.ui_intent,
    actions: event.actions || [],
    file_changes: event.file_changes || [],
    run_id: runId,
  });
}

function sessionPath(sessionId, file = "") {
  return path.join(workspace, ".asteria", "studio", "sessions", sessionId, file);
}

// Single canonical permission tier vocabulary (mirrors studio/src/permissionTiers.ts and the
// runtime --permission-level contract via lib/permission-level.mjs). The persisted default seeds
// the Composer; the dead legacy display string "ask-for-write" has been removed.
const PERMISSION_TIER_IDS = ["ask_everything", "reviewed_auto", "auto"];

function studioSettingsPath() {
  return path.join(workspace, ".asteria", "studio", "settings.json");
}

async function loadStudioSettings() {
  try {
    const parsed = JSON.parse(await fs.readFile(studioSettingsPath(), "utf8"));
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

async function saveStudioSettings(patch) {
  const next = { ...(await loadStudioSettings()), ...patch };
  await fs.mkdir(path.dirname(studioSettingsPath()), { recursive: true });
  await fs.writeFile(studioSettingsPath(), JSON.stringify(next, null, 2), "utf8");
  return next;
}

// One source of truth for the settings payload — GET and POST both return this so the displayed
// value is always the one actually in effect. permissionMode is the only persisted/writable field
// in this slice; everything else stays server-derived.
async function buildSettingsPayload() {
  const persisted = await loadStudioSettings();
  const permissionMode = PERMISSION_TIER_IDS.includes(persisted.permissionMode)
    ? persisted.permissionMode
    : "reviewed_auto";
  return {
    workMode: "engineering",
    permissionMode,
    shell: "PowerShell",
    streamMode: "runtime-model-events",
    workspace,
    workspaceName: workspaceBasename(workspace),
    runtimeRoot,
    workspaceProfile: await describeWorkspaceProfile(workspace),
  };
}

async function commandJson(commandArgs) {
  const completed = await runCommand([python, "-m", moduleName, ...commandArgs], runtimeRoot);
  if (completed.code !== 0)
    return {
      ok: false,
      code: completed.code,
      stdout: redactText(completed.stdout),
      stderr: redactText(completed.stderr),
    };
  try {
    return redact(JSON.parse(completed.stdout));
  } catch {
    return {
      ok: false,
      status: "invalid_json",
      stdout: redactText(completed.stdout),
      stderr: redactText(completed.stderr),
    };
  }
}

function runCommand(command, cwd, envOverrides = {}) {
  return new Promise((resolve) => {
    const child = spawn(command[0], command.slice(1), {
      cwd,
      env: { ...process.env, ...envOverrides },
      windowsHide: true,
    });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => {
      stdout += chunk.toString("utf8");
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk.toString("utf8");
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
    let stat = null;
    try {
      stat = await fs.stat(runDir);
    } catch {}
    runs.push(
      redact({
        run_id: entry.name,
        is_runtime_run: /^run-\d{8}-\d{4}$/.test(entry.name),
        modified_at_ms: stat?.mtimeMs ?? 0,
        ...(await readJson(path.join(runDir, "run.json"))),
        cost_report: await readJson(path.join(runDir, "cost_report.json")),
      }),
    );
  }
  return runs.sort((a, b) => {
    if (a.is_runtime_run !== b.is_runtime_run) return a.is_runtime_run ? -1 : 1;
    const byTime = Number(b.modified_at_ms || 0) - Number(a.modified_at_ms || 0);
    if (byTime) return byTime;
    return String(b.run_id).localeCompare(String(a.run_id));
  });
}

async function readRunDetail(runId) {
  if (!isSafeId(runId)) return { ok: false, error: "invalid run id" };
  const runsDir = path.join(workspace, ".asteria", "runs");
  const runDir = path.resolve(runsDir, runId);
  if (!runDir.startsWith(runsDir) || !existsSync(runDir))
    return { ok: false, error: "run not found" };
  const jsonFiles = {
    run: "run.json",
    cost_report: "cost_report.json",
    goal_spec: "goal_spec.json",
    task_plan: "task_plan.json",
    task_plan_eval: "task_plan_eval.json",
    agent_run_graph: "agent_run_graph.json",
    agent_loop_run_summary: "agent_loop_run_summary.json",
    run_loop_summary: "run_loop_summary.json",
    final_report_summary: "final_report_summary.json",
    model_route_timeline: "model_route_timeline.json",
  };
  const payload = { ok: true, run_id: runId };
  for (const [key, file] of Object.entries(jsonFiles)) {
    payload[key] = redact(await readJson(path.join(runDir, file)));
  }
  payload.runtime_progress = redact(
    payload.final_report_summary?.runtime_progress ||
      payload.run_loop_summary?.runtime_progress ||
      {},
  );
  payload.model_calls = redact(await readJsonlTail(path.join(runDir, "model_calls.jsonl"), 120));
  payload.task_execution_evidence = redact(
    await readJsonlTail(path.join(runDir, "task_execution_evidence.jsonl"), 80),
  );
  payload.worker_results = redact(
    await readJsonlTail(path.join(runDir, "worker_results.jsonl"), 80),
  );
  payload.validation_results = redact(
    await readJsonlTail(path.join(runDir, "validation_results.jsonl"), 80),
  );
  payload.mcp_invocations = redact(
    await readJsonlTail(path.join(runDir, "mcp_invocations.jsonl"), 80),
  );
  payload.skill_invocations = redact(
    await readJsonlTail(path.join(runDir, "skill_invocations.jsonl"), 80),
  );
  // capability_decisions.jsonl was written by the runtime but never read here (have-write-no-read);
  // surface it so the Inspector can show why each tool/MCP/skill capability was allowed or denied.
  payload.capability_decisions = redact(
    await readJsonlTail(path.join(runDir, "capability_decisions.jsonl"), 80),
  );
  const runtimeRequests = await readJsonlTail(path.join(runDir, "runtime_requests.jsonl"), 120);
  const decisions = await readJsonlTail(path.join(runDir, "decisions.jsonl"), 120);
  const currentDecisions = latestDecisions(decisions).map((decision) =>
    enrichRuntimeRequestDecision(decision, runtimeRequests),
  );
  payload.runtime_requests = redact(runtimeRequests);
  payload.decision_requests = redact(
    currentDecisions.filter((decision) => decision?.status === "pending"),
  );
  payload.decisions = redact(currentDecisions);
  payload.decision_history = redact(decisions);
  payload.main_action = redact(mainActionForRun(payload, currentDecisions));
  payload.candidate_exports = redact(
    await readJsonlTail(path.join(runDir, "candidate_exports.jsonl"), 80),
  );
  payload.merge_gate_dry_runs = redact(
    await readJsonlTail(path.join(runDir, "merge_gate_dry_runs.jsonl"), 40),
  );
  payload.candidate_promotions = redact(
    await readJsonlTail(path.join(runDir, "candidate_promotions.jsonl"), 80),
  );
  payload.promotion_preview = redact(buildPromotionPreview(payload));
  payload.worker_tree = redact(await buildWorkerTree(runDir, payload.agent_run_graph || {}));
  const workflowStateRows = await readJsonlTail(
    path.join(runDir, "orchestration_runner_state.jsonl"),
    120,
  );
  payload.orchestration_workflow = redact(buildOrchestrationWorkflowMonitor(workflowStateRows));
  payload.runtime_progress = redact(enrichRuntimeProgress(payload.runtime_progress || {}, payload));
  // 500 (not 120) to match the thread's own event read (readRuntimeUserProgressEvents). user_progress
  // is ~85% inspector rows, so a 120-physical-line tail kept only ~18 user-facing events and dropped a
  // run's whole opening (goal → plan → first steps) — the "process" the user wants to see. 500 keeps a
  // typical run's full arc while staying bounded for very long runs.
  const userProgress = await readJsonlTail(path.join(runDir, "user_progress.jsonl"), 500);
  const legacyEvents = await readJsonlTail(path.join(runDir, "events.jsonl"), 120);
  payload.user_progress = redact(userProgress);
  payload.raw_evidence = redact({
    legacy_events: legacyEvents,
    model_calls: payload.model_calls,
    task_execution_evidence: payload.task_execution_evidence,
    worker_results: payload.worker_results,
    validation_results: payload.validation_results,
    mcp_invocations: payload.mcp_invocations,
    skill_invocations: payload.skill_invocations,
    runtime_requests: payload.runtime_requests,
  });
  payload.legacy_events = redact(legacyEvents);
  payload.timeline_events_source = userProgress.length ? "user_progress" : "events";
  payload.timeline_default = userProgress.length ? "user_progress" : "legacy_events_fallback";
  payload.inspector_raw_evidence_source = "raw_evidence";
  payload.events = redact(
    userProgress.length
      ? userProgress.map((event) => userProgressToRunDetailEvent(event, runId)).filter(Boolean)
      : legacyEvents,
  );
  payload.files = await listRunEvidenceFiles(runDir, runId);
  return redact(payload);
}

function enrichRuntimeRequestDecision(decision, runtimeRequests) {
  const metadata =
    decision?.metadata && typeof decision.metadata === "object" ? decision.metadata : {};
  if (metadata.kind !== "runtime_request" || metadata.permission_preview) return decision;
  const requestIds = new Set(
    Array.isArray(metadata.runtime_request_ids) ? metadata.runtime_request_ids.map(String) : [],
  );
  const matched = (runtimeRequests || []).filter((request) =>
    requestIds.has(String(request.runtime_request_id || "")),
  );
  if (!matched.length) return decision;
  return {
    ...decision,
    metadata: {
      ...metadata,
      permission_preview: permissionPreviewForRuntimeRequests(matched),
    },
  };
}

function permissionPreviewForRuntimeRequests(requests) {
  const readScope = runtimeRequestDetailValues(requests, [
    "read_scope",
    "requested_read_scope",
    "paths",
  ]);
  const writeScope = runtimeRequestDetailValues(requests, ["write_scope", "requested_write_scope"]);
  const tools = runtimeRequestDetailValues(requests, [
    "allowed_tools",
    "tools",
    "tool",
    "tool_name",
  ]);
  const requestTypes = [
    ...new Set(requests.map((request) => String(request.request_type || "")).filter(Boolean)),
  ].sort();
  const riskRank = { low: 0, medium: 1, high: 2 };
  const risk =
    requests
      .map((request) => String(request.risk || "medium").toLowerCase())
      .sort((left, right) => (riskRank[right] ?? 1) - (riskRank[left] ?? 1))[0] || "medium";
  let action = "Review a task boundary change";
  let impact = "Review the requested task contract change before work continues.";
  let reversible = "Rejecting keeps the current task boundary unchanged.";
  if (writeScope.length) {
    action = "Allow additional workspace changes";
    impact = `Allow writing ${scopeValueSummary(writeScope)}.`;
    reversible = "Changes remain reviewable before acceptance.";
  } else if (readScope.length) {
    action = "Allow additional project context";
    impact = `Allow reading ${scopeValueSummary(readScope)}.`;
    reversible = "Workspace files will not be changed by this approval.";
  } else if (tools.length) {
    action = "Allow an additional tool";
    impact = `Allow use of ${scopeValueSummary(tools)}.`;
    reversible = "The tool remains bounded by the current task contract.";
  }
  const scopeParts = [];
  if (readScope.length) scopeParts.push(`Read: ${scopeValueSummary(readScope)}`);
  if (writeScope.length) scopeParts.push(`Write: ${scopeValueSummary(writeScope)}`);
  if (tools.length) scopeParts.push(`Tools: ${scopeValueSummary(tools)}`);
  const externalTool = tools.some((tool) => /network|web|http|mcp/i.test(tool));
  return permissionPreview({
    action,
    impact,
    scope: scopeParts.join("; ") || "Current task contract",
    network: externalTool
      ? "The requested tool may access an external service."
      : requestTypes.includes("model_upgrade_request")
        ? "The model provider will be contacted for the requested route."
        : "No additional network access requested.",
    risk,
    reversible,
    scope_detail: {
      read_scope: readScope,
      write_scope: writeScope,
      tools,
      request_types: requestTypes,
    },
  });
}

function runtimeRequestDetailValues(requests, keys) {
  const values = [];
  for (const request of requests || []) {
    const details = request?.details && typeof request.details === "object" ? request.details : {};
    for (const key of keys) {
      const raw = details[key];
      const candidates = Array.isArray(raw) ? raw : raw ? [raw] : [];
      for (const candidate of candidates) {
        const value = String(candidate).trim();
        if (value && !values.includes(value)) values.push(value);
      }
    }
  }
  return values;
}

function scopeValueSummary(values) {
  const visible = values.slice(0, 3);
  return `${visible.join(", ")}${values.length > visible.length ? `, and ${values.length - visible.length} more` : ""}`;
}

function latestMainTranscriptEvent(events, transcriptKind) {
  if (!Array.isArray(events)) return null;
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const event = events[index];
    if (event.display_level === "inspector") continue;
    if (event.transcript_kind === transcriptKind) return event;
  }
  return null;
}

function latestMainToolEvent(events) {
  return (
    latestMainTranscriptEvent(events, "tool_use") ||
    latestMainTranscriptEvent(events, "tool_result")
  );
}

function latestMainFinalEvent(events) {
  return latestMainTranscriptEvent(events, "final") || latestMainTranscriptEvent(events, "stop");
}

function buildTranscriptRuntimeProgress(event, transcriptKind, taskSummary = null) {
  if (!event) return null;
  const data = event.data && typeof event.data === "object" ? event.data : {};
  const taskCount = Number(taskSummary?.total || 0) || Number(data.task_count || 0);
  const projection = {
    transcript_kind: transcriptKind,
    ui_intent: event.ui_intent || "work_progress",
    phase: event.phase,
    status: event.status,
    title: event.title,
    summary: event.summary,
    content_delta: event.content_delta || "",
    event_id: event.event_id,
    created_at: event.created_at,
  };
  if (taskCount) projection.task_count = taskCount;
  if (event.tool_call_id) projection.tool_call_id = event.tool_call_id;
  return projection;
}

async function readRunUserProgress(runId) {
  if (!runId) return [];
  const progressPath = path.join(workspace, ".asteria", "runs", runId, "user_progress.jsonl");
  return readJsonlTail(progressPath, 500);
}

function enrichRuntimeProgress(progress, payload) {
  const agentLoop = payload.agent_loop_run_summary || {};
  const runLoop = payload.run_loop_summary || {};
  const workerSummary = workerSummaryForProgress(
    payload.worker_tree || {},
    payload.worker_results || [],
    payload.promotion_preview || {},
  );
  const userProgress = payload.user_progress || [];
  const taskPlan = payload.task_plan || {};
  const taskSummary =
    Array.isArray(taskPlan.tasks) && taskPlan.tasks.length
      ? { total: taskPlan.tasks.length }
      : progress.todo?.counts || null;
  const toolEvent = latestMainToolEvent(userProgress);
  const toolKind = toolEvent?.transcript_kind || "tool_use";
  const finalEvent = latestMainFinalEvent(userProgress);
  const finalKind = finalEvent?.transcript_kind || "final";
  const planProjection = buildTranscriptRuntimeProgress(
    latestMainTranscriptEvent(userProgress, "plan"),
    "plan",
    taskSummary,
  );
  const toolProjection = buildTranscriptRuntimeProgress(toolEvent, toolKind);
  const verifyProjection = buildTranscriptRuntimeProgress(
    latestMainTranscriptEvent(userProgress, "verification"),
    "verification",
  );
  const finalProjection = buildTranscriptRuntimeProgress(finalEvent, finalKind);
  return {
    ...progress,
    ...(planProjection ? { plan: planProjection } : {}),
    ...(toolProjection ? { tool: toolProjection } : {}),
    ...(verifyProjection ? { verify: verifyProjection } : {}),
    ...(finalProjection ? { final: finalProjection } : {}),
    loop: {
      ...(progress.loop || {}),
      exit_reason: firstRuntimeText(
        progress.loop?.exit_reason,
        agentLoop.exit_reason,
        runLoop.stop_reason,
        "",
      ),
      rounds:
        progress.loop?.rounds ??
        agentLoop.rounds ??
        agentLoop.iteration_count ??
        runLoop.iteration_count,
    },
    worker_summary: workerSummary,
  };
}

function workerSummaryForProgress(workerTree, workerResults, promotionPreview = {}) {
  const total =
    Number(workerTree.total_workers ?? 0) ||
    (Array.isArray(workerResults) ? workerResults.length : 0);
  if (!total) return {};
  const failed = Array.isArray(workerResults)
    ? workerResults.filter((item) =>
        /fail|error|block|denied|timeout/i.test(String(item.status ?? item.outcome ?? "")),
      ).length
    : Number(workerTree.failed_workers ?? 0);
  const successful = Array.isArray(workerResults)
    ? workerResults.filter((item) =>
        /success|complete|pass|succeed/i.test(String(item.status ?? item.outcome ?? "")),
      ).length
    : Number(workerTree.successful_workers ?? 0);
  const parallel = Number(workerTree.parallel_batches ?? 0);
  const status = failed ? "failed" : successful >= total ? "completed" : "running";
  const profile = firstRuntimeText(
    Array.isArray(workerResults)
      ? workerResults
          .map((item) => item.worker_kind || item.agent_id)
          .filter(Boolean)
          .join(", ")
      : "",
    "worker",
  );
  const workers = flattenWorkerNodes(workerTree);
  const promotionHint = promotionPreviewHint(promotionPreview);
  const latestSwarm =
    workerTree.latest_swarm_plan && typeof workerTree.latest_swarm_plan === "object"
      ? workerTree.latest_swarm_plan
      : null;
  const schedulingMode = String(latestSwarm?.scheduling_mode || "").trim();
  const fakePath = latestSwarm?.fake_path;
  return {
    status,
    total,
    successful,
    failed,
    parallel_batches: parallel,
    progress_percent: total ? Math.round((successful / total) * 100) : 0,
    summary: failed
      ? `${failed} background task${failed === 1 ? "" : "s"} need attention.`
      : `${successful}/${total} background task${total === 1 ? "" : "s"} completed.`,
    worker_profile: profile,
    promotion_hint: promotionHint,
    scheduling_mode: schedulingMode || null,
    fake_path: typeof fakePath === "boolean" ? fakePath : null,
    parallel_writes: latestSwarm?.parallel_writes ?? null,
    spawn_kind: latestSwarm?.spawn_kind || null,
    workers,
    evidence_refs: [
      "workers.jsonl",
      "worker_results.jsonl",
      "swarm_execution_plans.jsonl",
      "agent_run_graph.json",
    ],
  };
}

function flattenWorkerNodes(workerTree) {
  const result = [];
  const visit = (node, depth = 0) => {
    if (!node || typeof node !== "object") return;
    result.push({
      worker_invocation_id: node.worker_invocation_id,
      task_id: node.task_id,
      status: node.status,
      result_status: node.result_status,
      execution_profile_id: node.execution_profile_id,
      spawn_kind: node.spawn_kind,
      fake_path: node.fake_path ?? null,
      scheduling_mode: node.scheduling_mode || null,
      depth,
    });
    for (const child of Array.isArray(node.children) ? node.children : []) visit(child, depth + 1);
  };
  for (const root of Array.isArray(workerTree.roots) ? workerTree.roots : []) visit(root, 0);
  return result;
}

function promotionPreviewHint(promotionPreview) {
  if (!promotionPreview || typeof promotionPreview !== "object") return "";
  const pending = Number(promotionPreview.pending_promotions ?? 0);
  const exportCount = Number(promotionPreview.export_count ?? 0);
  const mergeStatus = String(promotionPreview.merge_preview_status ?? "");
  if (pending > 0) {
    return `${pending} candidate change${pending === 1 ? "" : "s"} waiting for your review in Inspector.`;
  }
  if (mergeStatus === "needs_review") {
    return String(
      promotionPreview.merge_preview_summary || "Some candidate changes need review before merge.",
    );
  }
  if (exportCount > 0 && mergeStatus === "ready") {
    return `${exportCount} candidate export${exportCount === 1 ? "" : "s"} passed merge preview.`;
  }
  return "";
}

function buildPromotionPreview(payload) {
  const exports = Array.isArray(payload.candidate_exports) ? payload.candidate_exports : [];
  const dryRuns = Array.isArray(payload.merge_gate_dry_runs) ? payload.merge_gate_dry_runs : [];
  const promotions = Array.isArray(payload.candidate_promotions)
    ? payload.candidate_promotions
    : [];
  const latestDryRun = dryRuns.length ? dryRuns[dryRuns.length - 1] : null;
  const pendingStatuses = new Set([
    "queued",
    "pending_manual_approval",
    "auto_approved",
    "blocked",
  ]);
  const pending = promotions.filter((item) => pendingStatuses.has(String(item.status || "")));
  const promoted = promotions.filter((item) => String(item.status || "") === "promoted");
  const latestExport = exports.length ? exports[exports.length - 1] : null;
  const mergePreviewStatus = latestDryRun
    ? latestDryRun.ok
      ? "ready"
      : "needs_review"
    : exports.length
      ? "pending"
      : "none";
  const rawSummary = String(latestDryRun?.summary || "");
  const mergePreviewSummary = rawSummary
    .replace(/Merge gate/gi, "Merge preview")
    .replace(/merge gate/gi, "merge preview");
  // isolate→verify→merge lineage, grouped by task_id (candidate_export + candidate_promotion both
  // carry task_id; the dry-run is batch-level, so "verified" is a batch signal, not per-task — the
  // UI labels it as such). Tasks without a task_id are skipped; the flat items[] stays as fallback.
  const byTask = new Map();
  for (const ex of exports) {
    const taskId = String(ex.task_id || "");
    if (!taskId) continue;
    const entry = byTask.get(taskId) || { task_id: taskId };
    entry.candidate_id = entry.candidate_id || ex.candidate_id;
    entry.isolated = {
      status: ex.export_status,
      files: Array.isArray(ex.changed_files) ? ex.changed_files.length : 0,
    };
    byTask.set(taskId, entry);
  }
  for (const pr of promotions) {
    const taskId = String(pr.task_id || "");
    if (!taskId) continue;
    const entry = byTask.get(taskId) || { task_id: taskId };
    entry.candidate_id = entry.candidate_id || pr.candidate_id;
    entry.merged = {
      status: pr.status,
      files:
        Array.isArray(pr.promoted_files) && pr.promoted_files.length
          ? pr.promoted_files.length
          : Array.isArray(pr.promotable_files)
            ? pr.promotable_files.length
            : 0,
      risky_files: Array.isArray(pr.merge_gate?.risky_files) ? pr.merge_gate.risky_files : [],
    };
    byTask.set(taskId, entry);
  }
  const batchVerified = latestDryRun ? { ok: Boolean(latestDryRun.ok), batch: true } : null;
  const lineages = [...byTask.values()]
    .slice(-8)
    .map((entry) => ({ ...entry, verified: batchVerified }));
  return {
    export_count: exports.length,
    dry_run_count: dryRuns.length,
    pending_promotions: pending.length,
    promoted_count: promoted.length,
    merge_preview_status: mergePreviewStatus,
    merge_preview_summary:
      mergePreviewSummary ||
      (exports.length ? "Candidate exports recorded; open Inspector for details." : ""),
    latest_export: latestExport,
    latest_dry_run: latestDryRun,
    lineages,
    items: [
      ...exports.slice(-6).map((item) => ({
        kind: "candidate_export",
        id: item.candidate_export_id,
        task_id: item.task_id,
        status: item.export_status,
        files: item.changed_files,
        execution_profile_id: item.execution_profile_id,
      })),
      ...dryRuns.slice(-3).map((item) => ({
        kind: "merge_preview",
        id: item.merge_gate_dry_run_id,
        ok: item.ok,
        summary: String(item.summary || "").replace(/Merge gate/gi, "Merge preview"),
        batch_violations: item.batch_violations,
      })),
      ...pending.slice(-6).map((item) => ({
        kind: "promotion_pending",
        id: item.promotion_id,
        task_id: item.task_id,
        status: item.status,
        files: item.promotable_files,
        // Risk is read ONLY from this same promotion record's own merge_gate (1:1, no cross-record
        // join). risk_level annotates; it never blocks. Empty risky_files => render no risk claim
        // (a hold can also be deletion-driven, a cause not recorded here).
        risky_files: Array.isArray(item.merge_gate?.risky_files) ? item.merge_gate.risky_files : [],
        risk_level: String(item.merge_gate?.risk_level || "low"),
      })),
    ],
    evidence_refs: [
      ...(exports.length ? ["candidate_exports.jsonl"] : []),
      ...(dryRuns.length ? ["merge_gate_dry_runs.jsonl"] : []),
      ...(promotions.length ? ["candidate_promotions.jsonl"] : []),
    ],
  };
}

async function latestV02RollingValidation() {
  const bundleDir = path.join(workspace, ".asteria", "evidence_bundles");
  if (!existsSync(bundleDir)) return {};
  let entries = [];
  try {
    entries = await fs.readdir(bundleDir, { withFileTypes: true });
  } catch {
    return {};
  }
  const manifests = [];
  for (const entry of entries) {
    if (!entry.isFile() || !entry.name.endsWith(".manifest.json")) continue;
    const manifestPath = path.join(bundleDir, entry.name);
    let stat;
    try {
      stat = await fs.stat(manifestPath);
    } catch {
      continue;
    }
    manifests.push({ path: manifestPath, modified_at: stat.mtimeMs });
  }
  manifests.sort((a, b) => b.modified_at - a.modified_at);
  for (const manifest of manifests) {
    const raw = await readJson(manifest.path);
    const summary = raw?.v0_2_rolling_validation;
    if (summary && typeof summary === "object" && !Array.isArray(summary)) return summary;
  }
  return {};
}

async function buildWorkerTree(runDir, agentRunGraph = {}) {
  const workers = await readJsonlTail(path.join(runDir, "workers.jsonl"), 500);
  const results = await readJsonlTail(path.join(runDir, "worker_results.jsonl"), 500);
  const events = await readJsonlTail(path.join(runDir, "events.jsonl"), 500);
  const swarmPlans = await readJsonlTail(path.join(runDir, "swarm_execution_plans.jsonl"), 20);
  const resultByWorker = new Map(
    results.map((item) => [String(item.worker_invocation_id || ""), item]),
  );
  const nodes = new Map();
  for (const worker of workers) {
    const id = String(worker.worker_invocation_id || "");
    if (!id) continue;
    const result = resultByWorker.get(id) || {};
    nodes.set(id, {
      worker_invocation_id: id,
      worker_result_id: result.worker_result_id || null,
      parent_worker_invocation_id:
        worker.parent_worker_invocation_id || result.parent_worker_invocation_id || null,
      parent_task_id: worker.parent_task_id || null,
      worker_kind: worker.worker_kind || result.worker_kind || null,
      parallel_safety: worker.parallel_safety || null,
      child_plan_refs: Array.isArray(worker.child_plan_refs)
        ? worker.child_plan_refs
        : Array.isArray(result.child_plan_refs)
          ? result.child_plan_refs
          : [],
      task_id: worker.task_id || result.task_id || "task",
      agent_id: worker.agent_id || "agent",
      runtime_profile_id: worker.runtime_profile_id || "unknown",
      execution_profile_id: worker.execution_profile_id || null,
      spawn_kind: worker.spawn_kind || null,
      fake_path: worker.fake_path ?? null,
      scheduling_mode: worker.scheduling_mode || null,
      status: worker.status || "unknown",
      result_status: result.status || null,
      artifact_refs: Array.isArray(result.artifact_refs) ? result.artifact_refs : [],
      validation_refs: Array.isArray(result.validation_refs) ? result.validation_refs : [],
      failure_evidence_refs: Array.isArray(result.failure_evidence_refs)
        ? result.failure_evidence_refs
        : [],
      cost: result.cost || { model_calls: 0, tool_calls: 0 },
      summary: result.summary || worker.summary || "",
      children: [],
    });
  }
  const roots = [];
  const orphanWorkers = [];
  for (const node of nodes.values()) {
    const parentId = String(node.parent_worker_invocation_id || "");
    if (!parentId) {
      roots.push(node);
      continue;
    }
    const parent = nodes.get(parentId);
    if (!parent) {
      roots.push(node);
      orphanWorkers.push(node.worker_invocation_id);
      continue;
    }
    parent.children.push(node);
  }
  const statusCounts = {};
  for (const node of nodes.values()) {
    const status = String(node.result_status || node.status || "unknown");
    statusCounts[status] = (statusCounts[status] || 0) + 1;
  }
  return {
    total_workers: nodes.size,
    status_counts: statusCounts,
    successful_workers: statusCounts.succeeded || 0,
    failed_workers:
      (statusCounts.failed || 0) + (statusCounts.denied || 0) + (statusCounts.timeout || 0),
    parallel_batches: events.filter(
      (event) =>
        event.type === "task_graph_selection" &&
        ["readonly_batch_selection", "parallel_safe_batch_selection"].includes(
          String(event.data?.reason || ""),
        ),
    ).length,
    coordination_modes: [
      ...new Set(
        events
          .filter((event) => event.type === "task_graph_selection" && event.data?.reason)
          .map((event) => String(event.data.reason)),
      ),
    ],
    total_model_calls: [...nodes.values()].reduce(
      (total, node) => total + Number(node.cost?.model_calls || 0),
      0,
    ),
    total_tool_calls: [...nodes.values()].reduce(
      (total, node) => total + Number(node.cost?.tool_calls || 0),
      0,
    ),
    agent_run_graph: agentRunGraph || {},
    collaboration_summary: agentRunGraph?.collaboration_summary || {},
    swarm_execution_plans: swarmPlans,
    latest_swarm_plan: swarmPlans.length ? swarmPlans[swarmPlans.length - 1] : null,
    orphan_workers: orphanWorkers,
    roots,
  };
}

function mainActionForRun(payload, currentDecisions) {
  const pending = (currentDecisions || []).filter((decision) => decision?.status === "pending");
  if (pending.length) {
    return {
      kind: "decide",
      label: "Decide",
      next_command: "asteria decide --list-pending",
      requires_permission: false,
      status: "waiting_decision",
      decision_count: pending.length,
      source: "decisions.jsonl",
      evidence_refs: ["decisions.jsonl"],
    };
  }
  const finalSummary = payload.final_report_summary || {};
  const loopSummary = payload.run_loop_summary || {};
  const progress = payload.runtime_progress || {};
  // agent_loop_run_summary.recommended_command was an FSM projection RA7b deleted (never written
  // now); the spine's next-command chip resolves from runtime_progress / final_report_summary.
  const nextCommand = firstRuntimeText(
    progress.next_command,
    finalSummary.recommended_next_command,
    loopSummary.recommended_next_command,
    "",
  );
  if (!nextCommand) {
    return {
      kind: "done",
      label: "Done",
      next_command: "",
      requires_permission: false,
      status: "idle",
      decision_count: 0,
      source: "runtime_progress",
      evidence_refs: ["final_report_summary.json", "run_loop_summary.json"],
    };
  }
  const action = runtimeActionFor(nextCommand);
  return {
    kind: action?.kind || "continue",
    label: action?.label || "Continue",
    next_command: nextCommand,
    requires_permission: Boolean(action?.requiresPermission),
    status: action?.requiresPermission ? "needs_permission" : "ready",
    decision_count: 0,
    source: progress.next_command
      ? "runtime_progress.next_command"
      : "runtime_summary.recommended_next_command",
    evidence_refs: ["final_report_summary.json", "run_loop_summary.json"],
  };
}

function userProgressToRunDetailEvent(event, runId) {
  const mapped = userProgressToStudioEvent(event, "", runId);
  mapped.session_id = "";
  mapped.event_id = `run-detail-${runId}-${event.event_id || event.sequence || Date.now()}`;
  return mapped;
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
    const calls = await readJsonlTail(
      path.join(workspace, ".asteria", "runs", run.run_id, "model_calls.jsonl"),
      500,
    );
    for (const call of calls) {
      const key = [
        call.model_provider || "unknown",
        call.model_name || "unknown",
        call.purpose || "unknown",
        call.model_tier || "unknown",
      ].join("/");
      const item = summary.get(key) || {
        key,
        provider: call.model_provider || "unknown",
        model: call.model_name || "unknown",
        purpose: call.purpose || "unknown",
        tier: call.model_tier || "unknown",
        total: 0,
        success: 0,
        failure: 0,
        streamingFailed: 0,
        durationMs: [],
      };
      item.total += 1;
      if (call.status === "success") item.success += 1;
      if (call.status === "failure") item.failure += 1;
      if (call.streaming?.mode === "streaming_failed") item.streamingFailed += 1;
      if (Number.isFinite(call.streaming?.duration_ms))
        item.durationMs.push(call.streaming.duration_ms);
      else if (Number.isFinite(call.duration_ms)) item.durationMs.push(call.duration_ms);
      summary.set(key, item);
    }
  }
  return [...summary.values()]
    .map((item) => ({
      ...item,
      successRate: item.total ? Number((item.success / item.total).toFixed(4)) : 0,
      durationP95: percentile(item.durationMs, 0.95),
    }))
    .sort((a, b) => b.total - a.total);
}

// Heavy / generated / noise directories skipped when walking a general workspace, so the file list
// (Inspector browser + composer @-mentions) reflects the user's real source, not build output or
// runtime bookkeeping. Dot-directories (.git/.venv/.asteria/.vscode…) are skipped separately.
const IGNORED_WORKSPACE_DIRS = new Set([
  "node_modules",
  "dist",
  "build",
  "out",
  "target",
  "vendor",
  "bin",
  "obj",
  "__pycache__",
  "venv",
  "env",
  "coverage",
  ".gradle",
]);

async function listWorkspaceFiles() {
  // General workspace walk from the root (was hardcoded to Asteria's own repo roots, which surfaced
  // nothing for an arbitrary project). Bounded by depth/scan cap; returns the 200 most recent files.
  const files = [];
  await collectFiles(workspace, files, 0);
  return files
    .sort((a, b) => String(b.modified_at).localeCompare(String(a.modified_at)))
    .slice(0, 200);
}

async function collectFiles(directory, files, depth) {
  if (depth > 6 || files.length > 800) return;
  let entries = [];
  try {
    entries = await fs.readdir(directory, { withFileTypes: true });
  } catch {
    return;
  }
  for (const entry of entries) {
    if (entry.isDirectory()) {
      // Skip dot-dirs (.git/.venv/.asteria/.next/.vscode…) and known heavy/generated dirs.
      if (entry.name.startsWith(".") || IGNORED_WORKSPACE_DIRS.has(entry.name)) continue;
      await collectFiles(path.join(directory, entry.name), files, depth + 1);
      continue;
    }
    const absolute = path.join(directory, entry.name);
    const relative = path.relative(workspace, absolute).replace(/\\/g, "/");
    if (!isSafeWorkspacePath(relative)) continue;
    if (!isPreviewableFile(relative)) continue;
    const stat = await fs.stat(absolute);
    files.push({ path: relative, size: stat.size, modified_at: stat.mtime.toISOString() });
  }
}

async function previewWorkspaceFile(body) {
  const relative = String(body?.path || "").replace(/\\/g, "/");
  if (!isSafeWorkspacePath(relative) || !isPreviewableFile(relative))
    return { ok: false, error: "file is not previewable" };
  const absolute = path.resolve(workspace, relative);
  if (!absolute.startsWith(workspace) || !existsSync(absolute))
    return { ok: false, error: "file not found" };
  const stat = await fs.stat(absolute);
  if (stat.size > 120_000) return { ok: false, error: "file too large for preview" };
  return {
    ok: true,
    path: relative,
    size: stat.size,
    content: redactText(await fs.readFile(absolute, "utf8")),
  };
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
    return (await fs.readFile(file, "utf8"))
      .split(/\r?\n/)
      .filter(Boolean)
      .slice(-limit)
      .map((line) => {
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

const PREVIEW_MIME = {
  ".html": "text/html; charset=utf-8",
  ".htm": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".gif": "image/gif",
  ".webp": "image/webp",
  ".avif": "image/avif",
  ".ico": "image/x-icon",
  ".bmp": "image/bmp",
  ".woff": "font/woff",
  ".woff2": "font/woff2",
  ".ttf": "font/ttf",
  ".otf": "font/otf",
  ".txt": "text/plain; charset=utf-8",
  ".map": "application/json; charset=utf-8",
  ".wasm": "application/wasm",
  ".mp3": "audio/mpeg",
  ".wav": "audio/wav",
  ".webmanifest": "application/manifest+json",
};

function previewContentType(filePath) {
  return PREVIEW_MIME[path.extname(filePath).toLowerCase()] || "application/octet-stream";
}

// PREVIEW-1: a dedicated static server (own port, localhost-only) that serves the workspace so the
// Preview tab's iframe can load MULTI-FILE sites with real relative/absolute asset resolution — the
// live-server / VS Code Live Preview model, not the srcDoc self-contained-only hack. Path-safe:
// reuses isSafeWorkspacePath (no traversal; .env/secrets/.git/keys/node_modules/dist refused);
// serves files only, no directory listing; a trailing slash defaults to index.html.
function startPreviewServer(startPort) {
  const workspaceRoot = path.resolve(workspace);
  let attempt = 0;
  const server = createServer(async (req, res) => {
    try {
      // PREVIEW-3: in proxy mode every request is reverse-proxied to the dev server, which owns
      // routing, bundling and its own HMR — we do not serve static files or inject a reload client.
      if (previewProxyTarget) {
        proxyToDevServer(req, res, previewProxyTarget);
        return;
      }
      if (req.method !== "GET" && req.method !== "HEAD") {
        res.writeHead(405);
        res.end("method not allowed");
        return;
      }
      let pathname = decodeURIComponent((req.url || "/").split("?")[0].split("#")[0]);
      // PREVIEW-2: live-reload SSE channel — the injected script (below) connects here; the workspace
      // watcher broadcasts "reload" so the preview refreshes when the agent edits files.
      if (pathname === "/__livereload") {
        res.writeHead(200, {
          "content-type": "text/event-stream; charset=utf-8",
          "cache-control": "no-cache",
          connection: "keep-alive",
        });
        res.write(": connected\n\n");
        previewSseClients.add(res);
        const ping = setInterval(() => {
          try {
            res.write(": ping\n\n");
          } catch {}
        }, 20000);
        req.on("close", () => {
          clearInterval(ping);
          previewSseClients.delete(res);
        });
        return;
      }
      if (pathname.endsWith("/")) pathname += "index.html";
      const rel = pathname.replace(/^\/+/, "") || "index.html";
      if (!isSafeWorkspacePath(rel)) {
        res.writeHead(403, { "content-type": "text/plain; charset=utf-8" });
        res.end("Forbidden");
        return;
      }
      const abs = path.resolve(workspaceRoot, rel);
      if (abs !== workspaceRoot && !abs.startsWith(workspaceRoot + path.sep)) {
        res.writeHead(403);
        res.end("Forbidden");
        return;
      }
      if (!existsSync(abs) || !statSync(abs).isFile()) {
        res.writeHead(404, { "content-type": "text/plain; charset=utf-8" });
        res.end("Not found");
        return;
      }
      const contentType = previewContentType(abs);
      const body = await fs.readFile(abs);
      // PREVIEW-2: inject the live-reload client into served HTML so edits auto-refresh the preview.
      if (contentType.startsWith("text/html") && req.method !== "HEAD") {
        let html = body.toString("utf8");
        const snippet =
          '\n<script>(function(){try{var s=new EventSource("/__livereload");s.onmessage=function(e){if(e.data==="reload")location.reload();};}catch(_){}})();</script>\n';
        html = html.includes("</body>")
          ? html.replace("</body>", `${snippet}</body>`)
          : html + snippet;
        res.writeHead(200, {
          "content-type": contentType,
          "cache-control": "no-store",
          "x-content-type-options": "nosniff",
        });
        res.end(html);
        return;
      }
      res.writeHead(200, {
        "content-type": contentType,
        "cache-control": "no-store",
        "x-content-type-options": "nosniff",
      });
      res.end(req.method === "HEAD" ? undefined : body);
    } catch {
      res.writeHead(500, { "content-type": "text/plain; charset=utf-8" });
      res.end("Preview error");
    }
  });
  // PREVIEW-3: proxy the websocket upgrade too, so the dev server's HMR socket keeps working through
  // the preview iframe (Vite/Next live-update the app without a full reload).
  server.on("upgrade", (req, socket, head) => {
    if (!previewProxyTarget) {
      socket.destroy();
      return;
    }
    const upstream = httpRequest({
      hostname: previewProxyTarget.hostname,
      port: previewProxyTarget.port,
      path: req.url,
      method: req.method,
      headers: {
        ...req.headers,
        host: `${previewProxyTarget.hostname}:${previewProxyTarget.port}`,
      },
    });
    upstream.on("upgrade", (upRes, upSocket, upHead) => {
      const statusLine = `HTTP/1.1 ${upRes.statusCode} ${upRes.statusMessage}\r\n`;
      const headerLines = Object.entries(upRes.headers)
        .map(([k, v]) => `${k}: ${v}`)
        .join("\r\n");
      socket.write(`${statusLine}${headerLines}\r\n\r\n`);
      if (upHead?.length) upSocket.unshift(upHead);
      upSocket.pipe(socket);
      socket.pipe(upSocket);
      upSocket.on("error", () => socket.destroy());
      socket.on("error", () => upSocket.destroy());
    });
    upstream.on("error", () => socket.destroy());
    if (head?.length) upstream.write(head);
    upstream.end();
  });
  const tryPort = (p) => {
    const onError = (err) => {
      if (err && err.code === "EADDRINUSE" && attempt < 15) {
        attempt += 1;
        tryPort(p + 1);
      } else {
        previewPort = null;
        console.error(`Asteria preview server failed: ${err?.message || err}`);
      }
    };
    server.once("error", onError);
    server.listen(p, "127.0.0.1", () => {
      server.removeListener("error", onError);
      previewPort = p;
      if (previewProxyTarget) {
        console.log(
          `Asteria preview server on http://127.0.0.1:${p} (proxy → ${previewProxyTarget.origin})`,
        );
      } else {
        console.log(`Asteria preview server on http://127.0.0.1:${p} (workspace static)`);
        startPreviewWatcher();
      }
    });
  };
  tryPort(startPort);
}

// PREVIEW-3: reverse-proxy one HTTP request to the configured dev server. A dead dev server yields a
// clear 502 with the origin, not a hang, so the Preview tab can tell the user to start their server.
function proxyToDevServer(req, res, target) {
  const upstream = httpRequest(
    {
      hostname: target.hostname,
      port: target.port,
      path: req.url,
      method: req.method,
      headers: { ...req.headers, host: `${target.hostname}:${target.port}` },
    },
    (upRes) => {
      res.writeHead(upRes.statusCode || 502, upRes.headers);
      upRes.pipe(res);
    },
  );
  upstream.on("error", (err) => {
    if (!res.headersSent) res.writeHead(502, { "content-type": "text/plain; charset=utf-8" });
    res.end(
      `Preview proxy: dev server ${target.origin} is unreachable (${err.code || err.message}). Start it, then reload.`,
    );
  });
  req.pipe(upstream);
}

function broadcastPreviewReload() {
  for (const res of [...previewSseClients]) {
    try {
      res.write("data: reload\n\n");
    } catch {
      previewSseClients.delete(res);
    }
  }
}

// PREVIEW-2: watch the workspace and tell connected previews to reload on change. Ignore runtime
// churn (.asteria writes constantly during a run) and heavy/generated dirs, or the preview would
// reload-storm. Debounced so a burst of writes coalesces into one reload.
function startPreviewWatcher() {
  const root = path.resolve(workspace);
  try {
    fsWatch(root, { recursive: true }, (_event, filename) => {
      if (!filename) return;
      const rel = String(filename).replace(/\\/g, "/");
      if (/(^|\/)(\.asteria|\.git|node_modules|dist|\.venv|__pycache__)(\/|$)/i.test(rel)) return;
      if (previewReloadTimer) return;
      previewReloadTimer = setTimeout(() => {
        previewReloadTimer = null;
        broadcastPreviewReload();
      }, 150);
    });
  } catch (err) {
    console.error(`Asteria preview watcher failed: ${err?.message || err}`);
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
  const type =
    {
      ".html": "text/html; charset=utf-8",
      ".js": "text/javascript; charset=utf-8",
      ".css": "text/css; charset=utf-8",
      ".svg": "image/svg+xml",
    }[path.extname(file)] || "application/octet-stream";
  response.writeHead(200, { "content-type": type });
  response.end(await fs.readFile(file));
}

function readRequestJson(request) {
  return new Promise((resolve) => {
    const chunks = [];
    let size = 0;
    request.on("data", (chunk) => {
      chunks.push(Buffer.from(chunk));
      size += chunk.length;
      if (size > 64_000) request.destroy();
    });
    request.on("end", () => {
      try {
        const raw = Buffer.concat(chunks).toString("utf8");
        resolve(raw ? JSON.parse(raw) : {});
      } catch {
        resolve({});
      }
    });
    request.on("error", () => resolve({}));
  });
}

// Session import bundles can be large (a long task = many events), so they need a much higher cap
// than readRequestJson's 64KB. Still bounded (25MB) to avoid unbounded memory. Returns null if the
// body exceeds the cap (route replies 413) rather than silently truncating.
function readRequestBodyRaw(request, maxBytes = 25_000_000) {
  return new Promise((resolve) => {
    const chunks = [];
    let size = 0;
    let overflow = false;
    request.on("data", (chunk) => {
      if (overflow) return;
      size += chunk.length;
      if (size > maxBytes) {
        overflow = true;
        request.destroy();
        return;
      }
      chunks.push(Buffer.from(chunk));
    });
    request.on("end", () => resolve(overflow ? null : Buffer.concat(chunks).toString("utf8")));
    request.on("error", () => resolve(null));
  });
}

function sendJson(response, status, payload) {
  response.writeHead(status, { "content-type": "application/json; charset=utf-8" });
  response.end(JSON.stringify(payload, null, 2));
}

async function describeWorkspaceProfile(targetPath) {
  const resolved = path.resolve(String(targetPath || workspace));
  if (!existsSync(resolved) || !statSync(resolved).isDirectory()) {
    return { ok: false, error: `not a directory: ${resolved}` };
  }
  const described = await commandJson(["workspaces", "describe", "--root", resolved, "--json"]);
  if (described.ok === false) {
    return {
      ok: true,
      workspace_root: resolved,
      initialized: existsSync(path.join(resolved, ".asteria", "project.json")),
      has_git: existsSync(path.join(resolved, ".git")),
      has_agents_md: existsSync(path.join(resolved, "AGENTS.md")),
      project_name: workspaceBasename(resolved),
    };
  }
  const profile =
    described.profile && typeof described.profile === "object" ? described.profile : described;
  return { ok: true, ...profile };
}

async function listWorkspaceRegistry() {
  const listed = await commandJson(["workspaces", "list", "--json"]);
  const registry =
    listed.registry && typeof listed.registry === "object" ? listed.registry : listed;
  const recent = Array.isArray(registry.recent_workspaces) ? registry.recent_workspaces : [];
  const recentWithProfiles = [];
  for (const entry of recent.slice(0, 8)) {
    const root = String(entry.workspace_root || "");
    recentWithProfiles.push({
      ...entry,
      profile: root ? await describeWorkspaceProfile(root) : null,
    });
  }
  return {
    ok: true,
    workspace,
    runtimeRoot,
    current_workspace_root: registry.current_workspace_root || workspace,
    workspace_profile: await describeWorkspaceProfile(workspace),
    recent_workspaces: redact(recentWithProfiles),
    registry: redact(registry),
  };
}

async function openWorkspace(body) {
  const requested = String(body?.path || body?.workspace || "").trim();
  if (!requested) return { ok: false, error: "path is required" };
  if (!isAbsoluteWorkspacePath(requested)) {
    return { ok: false, error: "workspace path must be absolute" };
  }
  const resolved = path.resolve(requested);
  if (!existsSync(resolved) || !statSync(resolved).isDirectory()) {
    return { ok: false, error: `not a directory: ${resolved}` };
  }
  // Only a genuinely RUNNING job should block a workspace switch. liveJobs retains completed/failed
  // jobs (they hold the child handle + run_id for the jobs/stop routes), so `size > 0` was true after
  // any past run and permanently wedged workspace switching. Check live status instead.
  const activeJobs = [...liveJobs.values()].filter(
    (job) => job.status === "running" && !job.cancelled,
  );
  if (activeJobs.length > 0) {
    return { ok: false, error: "cannot switch workspace while a turn is still running" };
  }

  const registered = await commandJson(["workspaces", "register", "--root", resolved, "--json"]);
  if (registered.ok === false) {
    let message = registered.error || registered.stderr || "workspace registration failed";
    try {
      const parsed = JSON.parse(String(registered.stdout || "{}"));
      if (parsed.error) message = String(parsed.error);
    } catch {}
    return { ok: false, error: message };
  }

  workspace = path.resolve(String(registered.workspace || resolved));
  runtimeRoot = path.resolve(String(body?.runtime_root || workspace));
  routeClient.reconfigure({ runtimeRoot });
  routeClient.invalidateWorkspace(workspace);
  const profile =
    registered.profile && typeof registered.profile === "object"
      ? registered.profile
      : await describeWorkspaceProfile(workspace);
  return {
    ok: true,
    workspace,
    runtimeRoot,
    initialized: Boolean(registered.initialized),
    workspace_name: workspaceBasename(workspace),
    profile,
    registry: redact(registered.registry || {}),
  };
}

async function browseWorkspaceFolder() {
  if (process.platform === "win32") {
    const script = [
      "[void][System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms')",
      "$dialog = New-Object System.Windows.Forms.FolderBrowserDialog",
      "$dialog.Description = 'Select Asteria workspace folder'",
      "$dialog.ShowNewFolderButton = $true",
      "if ($dialog.ShowDialog() -eq 'OK') { Write-Output $dialog.SelectedPath }",
    ].join("; ");
    const completed = await runCommand(
      ["powershell", "-NoProfile", "-STA", "-Command", script],
      process.cwd(),
    );
    const selected = String(completed.stdout || "").trim();
    if (!selected) return { ok: true, cancelled: true, path: null };
    return { ok: true, cancelled: false, path: path.resolve(selected) };
  }
  if (process.platform === "darwin") {
    const completed = await runCommand(
      [
        "osascript",
        "-e",
        'POSIX path of (choose folder with prompt "Select Asteria workspace folder")',
      ],
      process.cwd(),
    );
    const selected = String(completed.stdout || "").trim();
    if (!selected) return { ok: true, cancelled: true, path: null };
    return { ok: true, cancelled: false, path: path.resolve(selected) };
  }
  const zenity = await runCommand(
    ["zenity", "--file-selection", "--directory", "--title=Select Asteria workspace folder"],
    process.cwd(),
  );
  const selected = String(zenity.stdout || "").trim();
  if (zenity.code !== 0 || !selected) return { ok: true, cancelled: true, path: null };
  return { ok: true, cancelled: false, path: path.resolve(selected) };
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
