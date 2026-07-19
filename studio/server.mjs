import { spawn } from "node:child_process";
import { createServer } from "node:http";
import { existsSync, statSync, promises as fs } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { RuntimeRouteClient } from "./lib/runtime-route-client.mjs";
import { redact, redactText, tailText, percentile } from "./lib/text-utils.mjs";
import { readJson, readJsonlTail } from "./lib/run-io.mjs";
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
import {
  MAX_ATTACHMENT_BYTES,
  attachmentMimeFor,
  resolveAttachmentRequest,
  saveAttachment,
} from "./lib/attachments.mjs";
import { createPreviewSubsystem, normalizeProxyTarget } from "./lib/preview-server.mjs";
import { createEventBus } from "./lib/event-bus.mjs";
import { parseSessionText, writeSessionJson } from "./lib/session-store.mjs";
import { renderSessionReplayHtml } from "./lib/session-replay.mjs";
import { eventsAfter, parseSince } from "./lib/event-cursor.mjs";
import { createJobRegistry } from "./lib/jobs.mjs";
import { blockedEvent, blockingJob, mutatesWorkspace } from "./lib/run-conflict.mjs";
import { createRunDetailReader } from "./lib/run-detail-reader.mjs";
import { createChatAnswer } from "./lib/chat-answer.mjs";
import { createChatRoutes } from "./lib/chat-routes.mjs";
import {
  MODEL_STRATEGY_IDS,
  MODEL_TIERS,
  mapModelNames,
  mapModelStrategy,
} from "./lib/run-flags.mjs";
import { latestMainFinalEvent } from "./lib/run-evidence-transforms.mjs";

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
// Live-job registry (in-memory active/terminal job map + bounding prune) lives in ./lib/jobs.mjs;
// chat jobs, runtime jobs, the /jobs + /stop routes, and the workspace-switch guard all share it.
const { liveJobs, pruneLiveJobs } = createJobRegistry();
// Git helpers live in ./lib/git.mjs; wire them with a live workspace getter (the active
// workspace is reassigned on switch) + the protected-path-aware safety guard.
const {
  readWorkspaceGitStatus,
  readWorkspaceGitDiff,
  stageWorkspaceGitFile,
  discardWorkspaceGitFile,
  createWorkspaceSnapshot,
  workspaceSnapshotDiff,
  restoreWorkspaceSnapshot,
  ensureShadowBaseline,
} = createGitHelpers({ getWorkspace: () => workspace, runCommand });
// PREVIEW-3: opt-in reverse proxy to a running dev server (Vite/Next/CRA/etc.) so SPA/framework apps
// — which need a bundler, not static files — can be previewed. OPT-IN only (an explicit target),
// never an auto-probe of arbitrary localhost ports, which would risk proxying an unrelated app.
const previewProxyTarget = normalizeProxyTarget(
  args.previewProxy || process.env.ASTERIA_PREVIEW_PROXY,
);
// The preview subsystem (dedicated static/proxy server + live-reload watcher) lives in
// ./lib/preview-server.mjs and owns its own port/SSE/timer state; `previewProxyTarget` is computed
// here from args and injected. `getPreviewPort()` replaces the old module-level `previewPort`.
const { startPreviewServer, getPreviewPort } = createPreviewSubsystem({
  getWorkspace: () => workspace,
  previewProxyTarget,
});
// Run-evidence reader subsystem (readRunDetail + its 14 helpers) lives in ./lib/run-detail-reader.mjs.
// Only `workspace` is live-injected (mutable let, reassigned on openWorkspace); python/moduleName are
// stable consts. Five names are re-exported because code outside the evidence subgraph calls them
// (handleApi/readChatContext → readRunDetail; handleRuntimeAction → runtimeActionFor; startRuntimeJob →
// runtimeActionByKind/userProgressToStudioEvent; permissionPreviewForMode → permissionPreview).
const {
  readRunDetail,
  runtimeActionFor,
  runtimeActionByKind,
  userProgressToStudioEvent,
  permissionPreview,
} = createRunDetailReader({ getWorkspace: () => workspace, python, moduleName });

// Event bus (SSE fan-out + events.jsonl/session.json persistence) lives in ./lib/event-bus.mjs;
// wire it with a live workspace getter + the sessionPath helper (both derive from the active
// workspace, which is reassigned on openWorkspace). Chat and runtime job paths both append here.
const { sseClients, notifySSE, appendEvent } = createEventBus({
  getWorkspace: () => workspace,
  sessionPath,
});
// Chat answer generation (Tier 1: buildChatAnswer + the model call, sanitizers, local fallbacks and
// the chat lifecycle emitters) lives in ./lib/chat-answer.mjs. It must be wired after the event bus,
// whose appendEvent it writes through. Both mutable lets are live-injected; the rest are stable
// consts or hoisted server functions. Nothing here calls it directly any more — it is consumed whole
// by the chat routes below, which own the chat job that drives it.
const chatAnswer = createChatAnswer({
  getWorkspace: () => workspace,
  getRuntimeRoot: () => runtimeRoot,
  python,
  chatBackend,
  appendEvent,
  sessionPath,
  readRunDetail,
  overview,
  commandJson,
  runCommand,
  modelRouteSummary,
});
// Chat + goal-submission routes (Tier 2) live in ./lib/chat-routes.mjs: the five endpoints handleApi
// dispatches to, plus the pending-approval map, the chat job, and the studio->runtime command
// translation they own. What they only *drive* is injected and stays here: the execute layer
// (startRuntimeJob / runtimeCommand), the event bus, the job registry, and the session lifecycle.
const {
  submitUserGoal,
  handleRuntimeAction,
  handleDecisionResolve,
  handleDecisionAnswer,
  handlePermission,
} = createChatRoutes({
  getWorkspace: () => workspace,
  python,
  moduleName,
  routeClient,
  appendEvent,
  notifySSE,
  sessionPath,
  liveJobs,
  startRuntimeJob,
  applyAutonomyForTier,
  loadStudioSettings,
  runtimeCommand,
  ensureSession,
  resolvedSessionId,
  readSessionEvents,
  currentRunId,
  commandJson,
  permissionPreview,
  runtimeActionFor,
  chatAnswer,
});

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
  if (WARM_WORKER_ENABLED) console.log("warm worker: enabled (ADR-0029 ②) — pre-warming");
  startPreviewServer(port + 1);
  prewarmWorkerAtBoot();
});

async function handleApi(request, response, url) {
  if (request.method === "GET" && url.pathname === "/api/health") {
    sendJson(response, 200, {
      ok: true,
      workspace,
      runtimeRoot,
      python,
      moduleName,
      mid_run_steer: MID_RUN_STEER_ENABLED,
    });
    return;
  }
  if (request.method === "GET" && url.pathname === "/api/studio/sessions") {
    sendJson(response, 200, { ok: true, sessions: decorateSessionRunStatus(await listSessions()) });
    return;
  }
  if (request.method === "POST" && url.pathname === "/api/studio/sessions") {
    sendJson(response, 200, { ok: true, session: await createSession() });
    return;
  }
  if (request.method === "GET" && url.pathname === "/api/studio/attachments") {
    const absolute = resolveAttachmentRequest(workspace, url.searchParams.get("path"));
    if (!absolute) {
      sendJson(response, 400, { ok: false, error: "invalid attachment path" });
      return;
    }
    try {
      const bytes = await fs.readFile(absolute);
      response.writeHead(200, {
        "Content-Type": attachmentMimeFor(absolute),
        // Content-addressed: the bytes at this path can never change.
        "Cache-Control": "public, max-age=31536000, immutable",
      });
      response.end(bytes);
    } catch {
      sendJson(response, 404, { ok: false, error: "attachment not found" });
    }
    return;
  }
  if (request.method === "POST" && url.pathname === "/api/studio/attachments") {
    const sessionId = String(url.searchParams.get("session") || "");
    if (!isSafeId(sessionId)) {
      sendJson(response, 400, { ok: false, error: "invalid session id" });
      return;
    }
    const buffer = await readRequestBodyBinary(request, MAX_ATTACHMENT_BYTES);
    if (buffer === null) {
      sendJson(response, 413, { ok: false, error: "attachment too large" });
      return;
    }
    sendJson(response, 200, await saveAttachment({ workspace, sessionId, buffer }));
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
  // G15 会话回放导出: a self-contained HTML replay page (inline CSS/JS, zero external requests) —
  // the forwardable review artifact; the JSON bundle below stays the lossless backup format.
  if (
    request.method === "GET" &&
    url.pathname.match(/^\/api\/studio\/sessions\/[^/]+\/export\.html$/)
  ) {
    const sessionId = decodeURIComponent(url.pathname.split("/").at(-2) || "");
    const loaded = await readSession(sessionId);
    if (!loaded.ok) {
      sendJson(response, 404, loaded);
      return;
    }
    const html = renderSessionReplayHtml(loaded.session, loaded.events ?? []);
    const filename = `asteria-replay-${sessionId}.html`.replace(/[^a-zA-Z0-9._-]/g, "_");
    response.writeHead(200, {
      "content-type": "text/html; charset=utf-8",
      "content-disposition": `attachment; filename="${filename}"`,
    });
    response.end(html);
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
    const since = parseSince(url.searchParams.get("since"));
    sendJson(response, 200, {
      ok: true,
      events: eventsAfter(await readSessionEvents(sessionId), since),
    });
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
    // Replay only what the client has not seen. Without this, every reconnect (and a long run can
    // reconnect many times) re-pushed the ENTIRE transcript, so the cost of dropping a connection grew
    // with the length of the run — worst exactly when the run is longest.
    const since = parseSince(url.searchParams.get("since"));
    const existingEvents = eventsAfter(await readSessionEvents(sessionId), since);
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
  if (request.method === "POST" && url.pathname.match(/^\/api\/studio\/sessions\/[^/]+\/pause$/)) {
    const sessionId = decodeURIComponent(url.pathname.split("/").at(-2) || "");
    sendJson(response, 200, await pauseSessionRun(sessionId));
    return;
  }
  if (request.method === "POST" && url.pathname.match(/^\/api\/studio\/sessions\/[^/]+\/stop$/)) {
    const sessionId = decodeURIComponent(url.pathname.split("/").at(-2) || "");
    sendJson(response, 200, stopSessionJobs(sessionId));
    return;
  }
  if (request.method === "POST" && url.pathname.match(/^\/api\/studio\/sessions\/[^/]+\/steer$/)) {
    const sessionId = decodeURIComponent(url.pathname.split("/").at(-2) || "");
    const body = await readRequestJson(request);
    sendJson(response, 200, await steerSessionRun(sessionId, body?.instruction));
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
      ok: getPreviewPort() != null,
      port: getPreviewPort(),
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
  // G7 rewind 文件回滚: preview what restoring a shadow snapshot would change, then restore it.
  if (request.method === "POST" && url.pathname === "/api/studio/git/snapshot-diff") {
    sendJson(response, 200, await workspaceSnapshotDiff(await readRequestJson(request)));
    return;
  }
  if (request.method === "POST" && url.pathname === "/api/studio/git/restore-snapshot") {
    sendJson(response, 200, await restoreWorkspaceSnapshot(await readRequestJson(request)));
    return;
  }
  if (request.method === "GET" && url.pathname === "/api/studio/settings") {
    sendJson(response, 200, { ok: true, settings: await buildSettingsPayload() });
    return;
  }
  if (request.method === "POST" && url.pathname === "/api/studio/settings") {
    const body = await readRequestJson(request);
    // Patch semantics: each panel saves only the field it owns. A field that is present must be
    // valid (rejected at the door, never coerced — a silently-corrected save would show the user a
    // value they did not pick); a field that is absent is left alone.
    const patch = {};
    if (body?.permissionMode !== undefined) {
      const mode = String(body.permissionMode || "");
      if (!PERMISSION_TIER_IDS.includes(mode)) {
        sendJson(response, 400, { ok: false, error: "invalid permissionMode" });
        return;
      }
      patch.permissionMode = mode;
    }
    if (body?.modelStrategy !== undefined) {
      const strategy = String(body.modelStrategy || "");
      if (!MODEL_STRATEGY_IDS.includes(strategy)) {
        sendJson(response, 400, { ok: false, error: "invalid modelStrategy" });
        return;
      }
      patch.modelStrategy = strategy;
    }
    if (body?.modelNames !== undefined) {
      const names = body.modelNames;
      if (!names || typeof names !== "object" || Array.isArray(names)) {
        sendJson(response, 400, { ok: false, error: "modelNames must be an object" });
        return;
      }
      const cleaned = {};
      for (const [tier, name] of Object.entries(names)) {
        if (!MODEL_TIERS.includes(String(tier))) {
          sendJson(response, 400, { ok: false, error: `invalid model tier: ${tier}` });
          return;
        }
        if (name !== null && typeof name !== "string") {
          sendJson(response, 400, { ok: false, error: `model name for ${tier} must be a string` });
          return;
        }
        // A blank box means "stop pinning this tier", so it drops the key rather than storing "" —
        // an empty string here would read downstream as a model literally named "".
        const trimmed = String(name ?? "").trim();
        if (trimmed) cleaned[String(tier)] = trimmed;
      }
      // Whole-object write, not a per-tier merge: the panel always sends every tier it knows about,
      // so a merge would make an un-pinned tier impossible to clear.
      patch.modelNames = cleaned;
    }
    if (!Object.keys(patch).length) {
      sendJson(response, 400, { ok: false, error: "no writable setting in request" });
      return;
    }
    await saveStudioSettings(patch);
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

/** Map user_progress channel → studio event type */
/**
 * While a subprocess is live, tail the current run's user_progress.jsonl every 1.2s
 * and emit new entries as SSE events.  Returns a stop function.
 */
// Immediacy budget: the FIRST look is soon (subprocess cold-start still dominates, but every
// 100ms shaved off the first runtime line is felt), then we poll briskly. A brisk poll would
// re-read a growing file each tick, so we gate the read on a size change (one stat/tick) — idle
// ticks cost a stat, not a full re-read, and the seq-dedup below is still the correctness belt.
const TAIL_FIRST_DELAY_MS = 300;
const TAIL_POLL_MS = 500;

function tailUserProgress(sessionId, jobId) {
  let stopped = false;
  let lastSeq = 0;
  let lastSize = -1;
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
          // Skip the read entirely when nothing was appended since the last tick — lets us poll at
          // 500ms without paying a full re-read on every idle tick during a quiet model call.
          const { size } = await fs.stat(progressPath);
          if (size === lastSize) {
            if (!stopped) setTimeout(poll, TAIL_POLL_MS);
            return;
          }
          lastSize = size;
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

    if (!stopped) setTimeout(poll, TAIL_POLL_MS);
  }

  // Brief delay so the subprocess has time to start writing, then look soon.
  setTimeout(poll, TAIL_FIRST_DELAY_MS);
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
  const running = jobs.filter((job) => job.status === "running").length;
  return {
    ok: true,
    running,
    // A run whose job has reached a terminal status in the registry has SETTLED — the final event may
    // still be a beat behind flushing to disk, but the process did NOT die unexpectedly. The client
    // uses this to avoid crying "已中断" during the normal completion race (the job flips terminal a
    // beat before its final_answer event lands). Absent any job record (server restarted / pruned past
    // the grace window), settled is false and the client falls back to the debounced interruption check.
    settled: jobs.length > 0 && running === 0,
    jobs,
  };
}

// Pause ≠ Stop. Stop kills the process tree; the work in flight is gone. Pause drops a signal file in
// the run directory and lets the runtime notice it at its next TURN BOUNDARY — after the current tool
// batch finishes, before the next model call. Nothing is half-executed, the process exits on its own,
// and `resume` picks the run back up. So: no taskkill here, on purpose.
async function currentRunId() {
  try {
    const raw = await fs.readFile(path.join(workspace, ".asteria", "current_session.json"), "utf8");
    return String(JSON.parse(raw).session_id || "").trim();
  } catch {
    return "";
  }
}

async function pauseSessionRun(sessionId) {
  if (!isSafeId(sessionId)) return { ok: false, error: "invalid session id" };
  const running = [...liveJobs.values()].filter(
    (job) => job.session_id === sessionId && job.status === "running",
  );
  if (!running.length) return { ok: false, error: "no running job" };
  // A run_id only exists once the runtime has created the run. Before that there is no run directory
  // to signal — say so instead of silently doing nothing and letting the UI claim it paused.
  // A job only learns its run_id when it FINISHES (the id is scraped from its output), so while the
  // run is actually in flight — the only time pause matters — job.run_id is still null. Fall back to
  // the workspace's current run, which is exactly what `asteria pause` targets and exactly the run
  // this job is driving.
  const runIds = new Set(running.map((job) => job.run_id).filter(Boolean));
  if (!runIds.size) {
    const current = await currentRunId();
    if (current) runIds.add(current);
  }
  if (!runIds.size) {
    return { ok: false, error: "run has not started yet — nothing to pause (use Stop to cancel)" };
  }
  const paused = [];
  for (const runId of runIds) {
    if (!isSafeId(runId)) continue;
    const runDir = path.join(workspace, ".asteria", "runs", String(runId));
    try {
      await fs.mkdir(runDir, { recursive: true });
      await fs.writeFile(path.join(runDir, "pause.request"), "paused from Studio", "utf8");
      paused.push(runId);
    } catch {}
  }
  if (!paused.length) return { ok: false, error: "could not write the pause signal" };
  return { ok: true, paused, at: "next turn boundary" };
}

// ADR-0029 ①: hand a running run a new instruction. Same run-dir targeting as pause (a live job's
// run_id is null until it finishes, so fall back to the workspace's current run). We APPEND a JSON
// line so several steers queue and drain in order — matching run_control.take_steer's parser — and
// echo the instruction into the thread as the user's own message so they see it landed. The runtime
// only reads it when agent_loop.mid_run_steer is on (set by applyAutonomyForTier when enabled).
async function steerSessionRun(sessionId, instruction) {
  if (!MID_RUN_STEER_ENABLED) return { ok: false, error: "mid-run steer is disabled" };
  if (!isSafeId(sessionId)) return { ok: false, error: "invalid session id" };
  const text = String(instruction || "").trim();
  if (!text) return { ok: false, error: "empty instruction" };
  const running = [...liveJobs.values()].filter(
    (job) => job.session_id === sessionId && job.status === "running",
  );
  if (!running.length) return { ok: false, error: "no running job to steer" };
  const runIds = new Set(running.map((job) => job.run_id).filter(Boolean));
  if (!runIds.size) {
    const current = await currentRunId();
    if (current) runIds.add(current);
  }
  if (!runIds.size) {
    return { ok: false, error: "run has not started yet — nothing to steer" };
  }
  const steered = [];
  for (const runId of runIds) {
    if (!isSafeId(runId)) continue;
    const runDir = path.join(workspace, ".asteria", "runs", String(runId));
    try {
      await fs.mkdir(runDir, { recursive: true });
      await fs.appendFile(
        path.join(runDir, "steer.request"),
        JSON.stringify({ instruction: text }) + "\n",
        "utf8",
      );
      steered.push(runId);
    } catch {}
  }
  if (!steered.length) return { ok: false, error: "could not write the steer signal" };
  // Echo the steer into the thread as the user's own turn (same shape as a normal send) so the
  // instruction is visible immediately, not only once the model happens to reference it.
  await appendEvent(sessionId, {
    type: "user_message",
    status: "completed",
    title: "User",
    summary: text,
    content_delta: text,
    data: { mid_run_steer: true },
  });
  return { ok: true, steered, at: "next turn boundary" };
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
      loop.auto_replan_goal === autonomous &&
      loop.mid_run_steer === MID_RUN_STEER_ENABLED
    ) {
      return autonomous; // already in the desired state — skip the rewrite
    }
    loop.auto_repair = autonomous;
    loop.auto_replan = autonomous;
    loop.auto_replan_goal = autonomous;
    // ADR-0029 ①: enable the runtime's mid-run steer read only when the BFF feature flag is on;
    // otherwise leave it explicitly off so a running run ignores steer.request (today's behaviour).
    loop.mid_run_steer = MID_RUN_STEER_ENABLED;
    policy.agent_loop = loop;
    await fs.writeFile(policyPath, `${JSON.stringify(policy, null, 2)}\n`, "utf8");
    return autonomous;
  } catch {
    return null; // never block a run on a policy patch
  }
}

// ── Warm worker (ADR-0029 ②) ─────────────────────────────────────────────────
// One long-lived `python -m asteria_runtime.studio_worker` that has already paid the ~50-module
// import cost, so runs after boot start warm instead of cold-spawning (the import graph alone is
// ~254ms per cold run). Serial by design: it serves one run at a time, which is what makes the
// per-request event-sink env override inside the worker safe. Concurrent runs, custom-command modes,
// and ANY worker trouble (not ready, busy, crashed) transparently fall back to the cold spawn — so
// turning this on can only remove latency, never change an outcome. Default ON (2026-07-16 DecisionPoint:
// pure-latency, cold-fallback, zero-behaviour-change proven by real-stack E2E, changelog 1.2.74/1.2.75);
// set ASTERIA_STUDIO_WARM_WORKER=0 (or false) to force the cold path for debugging / rollback.
const WARM_WORKER_ENABLED =
  String(process.env.ASTERIA_STUDIO_WARM_WORKER ?? "1").toLowerCase() !== "0" &&
  String(process.env.ASTERIA_STUDIO_WARM_WORKER ?? "1").toLowerCase() !== "false";
// ADR-0029 ①: mid-run steer. When on, a message typed during a run is delivered to the running agent
// at its next turn boundary (via steer.request → the spine's take_steer read) instead of being queued
// for after the run. Default ON (2026-07-16 DecisionPoint, changelog 1.2.76): the Composer offers
// "insert now (takes effect next turn)" for a running job. Set ASTERIA_STUDIO_MID_RUN_STEER=0 (or
// false) to restore the honest queue-for-after behaviour (the runtime then never reads the signal).
const MID_RUN_STEER_ENABLED =
  String(process.env.ASTERIA_STUDIO_MID_RUN_STEER ?? "1").toLowerCase() !== "0" &&
  String(process.env.ASTERIA_STUDIO_MID_RUN_STEER ?? "1").toLowerCase() !== "false";
const WARM_CONTROL_PREFIX = "@@ASTERIA_WORKER@@ ";
const WARM_WORKER_MAX_RUNS = 50; // recycle after N runs so any slow per-run leak stays bounded
let warmWorker = null; // { child, pid, ready, busy, runCount, active, buf }

function spawnWarmWorker() {
  const child = spawn(python, ["-m", `${moduleName}.studio_worker`], {
    cwd: runtimeRoot,
    env: { ...process.env, PYTHONIOENCODING: "utf-8" },
    windowsHide: true,
  });
  const w = {
    child,
    pid: child.pid,
    ready: false,
    busy: false,
    runCount: 0,
    active: null,
    buf: "",
  };
  child.stdout.on("data", (chunk) => handleWarmStdout(w, chunk.toString("utf8")));
  child.stderr.on("data", () => {}); // process-level worker noise; per-run diagnostics ride user_progress
  child.on("close", () => handleWarmClose(w));
  child.on("error", () => handleWarmClose(w));
  warmWorker = w;
  return w;
}

function ensureWarmWorker() {
  if (!warmWorker) return spawnWarmWorker();
  return warmWorker;
}

// Pre-warm at boot so even the first user run is warm — the import cost is paid now, in the background.
function prewarmWorkerAtBoot() {
  if (!WARM_WORKER_ENABLED) return;
  try {
    ensureWarmWorker();
  } catch {}
}

function finalizeWarmActive(active, w, { code, runIdHint }) {
  active.stopTail();
  active.job.child = null;
  w.active = null;
  w.busy = false;
  void finalizeRuntimeJob({
    job: active.job,
    jobId: active.jobId,
    sessionId: active.sessionId,
    command: active.command,
    code,
    runIdHint: runIdHint ?? active.runId,
  });
}

function handleWarmClose(w) {
  if (warmWorker === w) warmWorker = null;
  const active = w.active;
  if (!active) return;
  // The worker died with a run in flight. A user Stop tree-killed it (job.cancelled) → finalize as a
  // clean stop; otherwise it crashed → non-zero exit so the honest failure path runs. Either way the
  // next run re-warms a fresh worker.
  finalizeWarmActive(active, w, { code: active.job.cancelled ? 0 : 1, runIdHint: null });
}

function handleWarmControl(w, msg) {
  if (msg.event === "ready") {
    w.ready = true;
    return;
  }
  const active = w.active;
  if (!active || (msg.id && active.jobId !== msg.id)) return; // stale / mismatched request id
  if (msg.event === "done" || msg.event === "error") {
    if (msg.run_id) {
      active.runId = String(msg.run_id);
      rememberJobRunId(active.jobId, active.runId);
    }
    w.runCount += 1;
    finalizeWarmActive(active, w, {
      code: typeof msg.exit_code === "number" ? msg.exit_code : msg.event === "error" ? 1 : 0,
      runIdHint: active.runId,
    });
    if (w.runCount >= WARM_WORKER_MAX_RUNS) {
      try {
        w.child.kill("SIGTERM"); // recycle; next run re-warms
      } catch {}
      if (warmWorker === w) warmWorker = null;
    }
  }
}

function handleWarmStdout(w, text) {
  w.buf += text;
  let idx;
  while ((idx = w.buf.indexOf("\n")) >= 0) {
    const line = w.buf.slice(0, idx);
    w.buf = w.buf.slice(idx + 1);
    if (!line) continue;
    if (line.startsWith(WARM_CONTROL_PREFIX)) {
      let msg;
      try {
        msg = JSON.parse(line.slice(WARM_CONTROL_PREFIX.length));
      } catch {
        continue;
      }
      handleWarmControl(w, msg);
    } else if (w.active) {
      // Incidental worker stdout during a run — mirror the cold path's inspector "Runtime output".
      const clean = redactText(line);
      void appendEvent(w.active.sessionId, {
        type: "tool_delta",
        status: "running",
        title: "Runtime output",
        summary: summarizeRuntimeChunk(clean),
        content_delta: `${clean}\n`,
        display_level: "inspector",
        command: w.active.command,
      });
    }
  }
}

// Returns true if the warm worker accepted the run (caller then skips the cold spawn); false on any
// unavailability so the caller falls back to a cold subprocess.
function dispatchWarmRun({ job, jobId, sessionId, mode, goal, command, stopTail, warmParams }) {
  const w = ensureWarmWorker();
  if (!w || !w.ready || w.busy || !w.child || !w.child.stdin || !w.child.stdin.writable)
    return false;
  const request = {
    id: jobId,
    mode: "run",
    root: workspace,
    goal,
    max_iterations: 8,
    max_tasks_per_iteration: 1,
    no_research: true,
    event_sink: sessionPath(sessionId, "events.jsonl"),
    session_id: sessionId,
    phase: phaseForMode(mode),
    // The cold path carries the user's choices as CLI flags; the worker reads JSON, so they must be
    // spelled out here or studio_worker silently falls back to its own defaults — for the tier that
    // is an autonomy UPGRADE for anyone who picked "ask first", and for the model strategy it means
    // the picked strategy is ignored. The caller owns the values (see warmRunParams).
    ...warmParams,
  };
  try {
    w.child.stdin.write(`${JSON.stringify(request)}\n`);
  } catch {
    return false;
  }
  w.busy = true;
  w.active = { job, jobId, sessionId, command, stopTail, runId: null };
  job.child = w.child; // a Stop tree-kills the worker; it re-warms afterward
  job.pid = w.child.pid;
  job.warm = true;
  liveJobs.set(jobId, job);
  return true;
}

/**
 * Start a runtime job, unless another run is already writing this workspace.
 *
 * Returns {started:true, job} or {started:false, blockedBy}. The refusal is announced from in here
 * rather than left to each caller: a caller that ignores the result still leaves the user with an
 * explanation on the thread, instead of a message that vanished. See lib/run-conflict.mjs for why
 * one-writer-at-a-time is the only honest option while every session shares one workspace.
 *
 * KEEP THIS FUNCTION SYNCHRONOUS through the guard. Nothing awaits between blockingJob() and
 * liveJobs.set(), so on a single-threaded event loop the check-and-claim is atomic and two requests
 * arriving together cannot both win. submitUserGoal's earlier check has awaits after it and is only
 * there for the narrative; this one is the gate. An await slipped in below would quietly restore the
 * very race this guards.
 */
function startRuntimeJob(sessionId, mode, goal, commandOverride = null, options = {}) {
  pruneLiveJobs();
  const blockedBy = blockingJob(liveJobs.values(), mode);
  if (blockedBy) {
    void appendEvent(sessionId, blockedEvent(blockedBy));
    return { started: false, blockedBy };
  }
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
    // Carried so the guard can tell the next user WHICH run holds the workspace. Not exposed by
    // sessionJobsPayload — it stays server-side, for the notice.
    goal,
    command,
    started_at_ms: Date.now(),
    run_id: null,
    follow_up_mode: options.followUpMode || null,
  };
  liveJobs.set(jobId, job);

  // F9 (dogfood 2026-07-19): for a NON-git workspace, advance the shadow-diff baseline at each
  // fresh writing run's start so the Changes pane can show "what THIS run changed". Fire-and-forget
  // on purpose — this function must stay synchronous through the cross-run guard above, and the
  // baseline is a best-effort UX aid, never a gate. Race window (run writes before the snapshot
  // finishes) is covered by the run's planning phase: the doer's first file write is seconds away,
  // the snapshot of a small non-git workspace is sub-second; a real repo returns immediately.
  // Freshness is the CALLER's explicit claim (`options.freshRun`), NOT inferred from
  // `!commandOverride` — every caller passes a command (see the warm-worker lesson below, 1.2.103:
  // that inference was never once true). Continuations (continue/resume/follow-up/decide) make no
  // claim, so the run's original baseline survives and the pane stays cumulative across them.
  if (options.freshRun && mutatesWorkspace(mode)) {
    void ensureShadowBaseline(`pre-run ${mode}`).catch(() => {});
  }

  void appendEvent(sessionId, {
    type: "tool_start",
    status: "running",
    title: "Processing started",
    summary: "Processing started.",
    display_level: "inspector",
    command,
  });

  const stopTail = tailUserProgress(sessionId, jobId);

  // ADR-0029 ②: a plain run/goal can go to the warm worker (imports already paid). A custom command
  // (continue/resume/follow-up) or any worker unavailability falls through to the cold spawn below.
  //
  // Eligibility is the CALLER's explicit claim, not `!commandOverride` as it was until 1.2.103. Every
  // caller passes a command (has done since the chat routes moved to lib/ in ae3e358, a day BEFORE
  // the warm worker landed), so that guard was never once false and the worker — enabled, pre-warmed,
  // holding a process — handled zero runs from birth. Only a caller knows whether its command is a
  // plain run the worker can reproduce from `warmParams`, or a custom one it cannot.
  if (WARM_WORKER_ENABLED && options.warmParams && (mode === "run" || mode === "goal")) {
    if (
      dispatchWarmRun({
        job,
        jobId,
        sessionId,
        mode,
        goal,
        command,
        stopTail,
        warmParams: options.warmParams,
      })
    )
      return { started: true, job };
  }

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
    await finalizeRuntimeJob({ job, jobId, sessionId, command, code, stdout, stderr });
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
  return { started: true, job };
}

// Shared completion path for a runtime job — reached from BOTH the cold subprocess's `close`
// event and the warm worker's `done`/`error` control message (ADR-0029 ②). Kept identical so a
// warm run and a cold run reach the exact same honest terminal status: a zero exit code only means
// "did not crash", so we trust the runtime's own conclusion event (from user_progress) over it.
// `runIdHint` lets the warm path pass the run_id it got back explicitly (the cold path scrapes it
// from stdout); `stdout`/`stderr` are empty for the warm path, whose output rides its own channels.
async function finalizeRuntimeJob({
  job,
  jobId,
  sessionId,
  command,
  code,
  stdout = "",
  stderr = "",
  runIdHint = null,
}) {
  // G7 rewind: shadow-checkpoint the workspace at every turn end (stopped runs included — rolling
  // back a half-finished stop is a prime use case). Silently absent on non-git workspaces; the
  // rewind UI then says honestly that only the conversation can rewind.
  const turnSnapshot = await createWorkspaceSnapshot(`job ${jobId}`);
  const snapshotData = turnSnapshot.ok ? { workspace_snapshot: turnSnapshot.snapshot } : null;
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
      data: snapshotData ?? undefined,
    });
    return;
  }
  rememberJobRunId(jobId, runIdHint || extractRunId(stdout) || extractRunId(stderr));
  const completedRunId = job.run_id || runIdHint || extractRunId(stdout) || extractRunId(stderr);
  const userProgressRows = completedRunId ? await readRunUserProgress(completedRunId) : [];
  const mainFinal = latestMainFinalEvent(userProgressRows);
  // A zero exit code only means the process did not crash — NOT that the goal was met. The `run`
  // CLI returns 0 for blocked / paused / unverified runs too (it prints the recap and returns
  // without keying the exit code off run status). The runtime's own conclusion event carries the
  // real terminal status (run_command.py emits it as `status=run_status`); trust that over the exit
  // code so a blocked or paused run is never stamped "completed" on the jobs badge or the tool_end.
  const runTerminalStatus = String(mainFinal?.status || "").toLowerCase();
  const processFailed = code !== 0;
  const runIncomplete =
    !processFailed && runTerminalStatus !== "" && runTerminalStatus !== "completed";
  job.status = processFailed ? "failed" : runIncomplete ? runTerminalStatus : "completed";
  liveJobs.set(jobId, job);
  const needsAttention = processFailed || runIncomplete;
  void appendEvent(sessionId, {
    type: "tool_end",
    status: job.status,
    title: needsAttention ? "Processing needs attention" : "Processing completed",
    summary: needsAttention
      ? "The task needs attention; preparing the reason and next step."
      : "Processing completed; preparing the result.",
    command,
    display_level: "inspector",
    run_id: completedRunId || undefined,
    content_delta: stderr
      ? `stderr:
${stderr}`
      : stdout.slice(-4000),
    // The snapshot rides the session-side settle event too: its Z timestamp sorts with the turn's
    // own events, so the rewind anchor survives even if the runtime final's ordering drifts.
    data: snapshotData ?? undefined,
  });
  if (mainFinal) {
    const mapped = userProgressToStudioEvent(mainFinal, sessionId, completedRunId || "");
    // Keep the namespaced event_id (see live-tail note above) so this persisted final dedups
    // cleanly against the runtime re-read instead of appearing twice.
    void appendEvent(sessionId, {
      ...mapped,
      job_id: jobId,
      data: snapshotData ? { ...(mapped.data || {}), ...snapshotData } : mapped.data,
    });
  } else {
    // ADR-0012: when the runtime emitted no main-thread conversational final, do NOT synthesize the
    // diagnostic report as the reply. Show an honest short line and point to the Inspector for detail.
    // And with no conclusion event we have no run status either — a bare exit-0 is NOT proof the goal
    // was met, so the copy must not assert "Result prepared / completed". Say the run finished and
    // point to the Inspector; the truthful verdict, if any, lives there.
    const honest =
      code === 0
        ? "Finished. Open the Inspector to review what changed and the verification details."
        : friendlyErrorText(stderr || stdout) ||
          "The task needs attention — open the Inspector for the reason and next step.";
    void appendEvent(sessionId, {
      type: code === 0 ? "final_answer" : "error",
      status: code === 0 ? "completed" : "failed",
      title: code === 0 ? "Finished" : "Needs attention",
      summary:
        code === 0
          ? "The run finished — open the Inspector for what changed and verification."
          : "The task needs attention; here is the reason and suggestion.",
      phase: code === 0 ? "result" : "review",
      display_level: "main",
      content_delta: honest,
      evidence_refs: [sessionPath(sessionId, "events.jsonl")],
      artifact_refs: runArtifactRefs(completedRunId),
      run_id: completedRunId || undefined,
      job_id: jobId,
      data: {
        ...(code === 0 ? {} : { error_category: friendlyErrorCategory(stderr || stdout) }),
        ...(snapshotData || {}),
      },
    });
  }
  const followUpMode = job.follow_up_mode;
  if (code === 0 && followUpMode) {
    const followUp = runtimeActionByKind(followUpMode);
    if (followUp) {
      startRuntimeJob(sessionId, followUp.mode, followUp.goal, followUp.command);
    }
  }
}

/** Build final text for run/resume modes — reads final_report.md and eval_report.json */
/** Build final text for review mode — reads review_report.md and eval_report.json */
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

function nonEmptyRecord(value) {
  return (
    value && typeof value === "object" && !Array.isArray(value) && Object.keys(value).length > 0
  );
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
  await writeSessionJson(sessionPath(sessionId, "session.json"), session);
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
    // parseSessionText salvages torn files (concurrent-write tail garbage) instead of letting a
    // stray byte make the whole session silently vanish from listSessions.
    const session = parseSessionText(raw);
    if (!session) return { ok: false, error: "session unreadable" };
    return { ok: true, session, events: await readSessionEvents(sessionId) };
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
    session = parseSessionText(raw) ?? { session_id: sessionId };
  } catch {
    session = { session_id: sessionId };
  }
  session.deleted_at = new Date().toISOString();
  await writeSessionJson(file, session);
  return { ok: true, deleted: sessionId, soft_deleted: true };
}

async function restoreSession(sessionId) {
  if (!isSafeId(sessionId)) return { ok: false, error: "invalid session id" };
  const file = sessionPath(sessionId, "session.json");
  if (!existsSync(file)) return { ok: false, error: "session not found" };
  const session = parseSessionText(await fs.readFile(file, "utf8").catch(() => ""));
  if (!session) return { ok: false, error: "session unreadable" };
  // Clear the marker without touching updated_at, so the session slots back into its original
  // position in the list (undo = put it back exactly, not bump to the top).
  delete session.deleted_at;
  await writeSessionJson(file, session);
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
  await writeSessionJson(sessionPath(sessionId, "session.json"), session);
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
  const session = parseSessionText(await fs.readFile(file, "utf8").catch(() => ""));
  if (!session) return { ok: false, error: "session unreadable" };
  if (body?.title) session.title = String(body.title).slice(0, 120);
  if (body?.goal_preview) session.goal_preview = String(body.goal_preview).slice(0, 160);
  // Archive (G3): reversible like soft-delete, but user-intentional shelving — the session stays
  // listed under the 已归档 filter instead of vanishing from the sidebar.
  if (typeof body?.archived === "boolean") {
    if (body.archived) session.archived_at = new Date().toISOString();
    else delete session.archived_at;
  }
  if (body?.ui_state && typeof body.ui_state === "object") {
    session.ui_state = { ...(session.ui_state || {}), ...body.ui_state };
  }
  session.updated_at = new Date().toISOString();
  await writeSessionJson(file, session);
  return { ok: true, session };
}

// Sidebar status badges (G3): project each session's latest live job onto the list response —
// "running" while a job is alive, "completed"/"failed" for the retention window after it settles
// (pruneLiveJobs keeps terminal jobs ~10min), absent otherwise. Purely in-memory; no event scan.
function decorateSessionRunStatus(sessions) {
  const latest = new Map();
  for (const job of liveJobs.values()) {
    if (!job.session_id) continue;
    const prev = latest.get(job.session_id);
    if (!prev || (job.started_at_ms || 0) > (prev.started_at_ms || 0)) {
      latest.set(job.session_id, job);
    }
  }
  return sessions.map((session) => {
    const job = latest.get(session.session_id);
    const status =
      job && ["running", "completed", "failed"].includes(job.status) ? job.status : null;
    return status ? { ...session, run_status: status } : session;
  });
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

async function readSessionEvents(sessionId) {
  if (!isSafeId(sessionId)) return [];
  const file = sessionPath(sessionId, "events.jsonl");
  if (!existsSync(file)) return [];
  let events = (await fs.readFile(file, "utf8"))
    .split(/\r?\n/)
    .filter(Boolean)
    .map((line, index) => {
      let event;
      try {
        event = redact(JSON.parse(line));
      } catch {
        event = { type: "raw", content_delta: redactText(line) };
      }
      // Events written before `seq` existed (and unparseable lines) fall back to their line index,
      // which is exactly what the event bus seeds its counter from — so the numbering is continuous
      // across the upgrade instead of restarting at 0 and replaying the whole transcript.
      if (typeof event.seq !== "number") event.seq = index;
      return event;
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
  // G7: the session-persisted copy of a runtime final carries BFF-side enrichment (the turn's
  // workspace_snapshot, attached at finalize). When the authoritative runtime re-read replaces
  // that copy, graft the enrichment onto the survivor — replacing must not LOSE it.
  const sessionSnapshots = new Map();
  for (const event of sessionEvents) {
    const snap = event?.data?.workspace_snapshot;
    if (snap && event.event_id) sessionSnapshots.set(event.event_id, snap);
  }
  const enrichedRuntimeEvents = runtimeEvents.map((event) => {
    const snap = sessionSnapshots.get(event.event_id);
    if (!snap || event?.data?.workspace_snapshot) return event;
    return { ...event, data: { ...(event.data || {}), workspace_snapshot: snap } };
  });
  // Sort by PARSED time, not string compare: session events carry UTC "Z" stamps while runtime
  // user-progress rows carry local "+08:00" stamps — localeCompare ordered those by date STRING,
  // shoving same-moment runtime rows a whole "day" away (caught live: a turn's final landed after
  // the NEXT turn's user message). Unparseable stamps inherit the last seen key (carry-forward,
  // same fixed-total-order pattern as the client's mergeEventLists — a null-equals-everything
  // comparator is intransitive and silently mis-sorts).
  let lastTs = 0;
  return [...filteredSessionEvents, ...enrichedRuntimeEvents]
    .map((event, index) => {
      const parsed = Date.parse(String(event.created_at || ""));
      if (Number.isFinite(parsed)) lastTs = parsed;
      return { event, index, key: Number.isFinite(parsed) ? parsed : lastTs };
    })
    .sort((a, b) => (a.key !== b.key ? a.key - b.key : a.index - b.index))
    .map((entry) => entry.event);
}

function sessionPath(sessionId, file = "") {
  return path.join(workspace, ".asteria", "studio", "sessions", sessionId, file);
}

// Single canonical permission tier vocabulary (mirrors studio/src/permissionTiers.ts and the
// runtime --permission-level contract via lib/run-flags.mjs). The persisted default seeds
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
// value is always the one actually in effect. permissionMode and modelStrategy are the persisted/
// writable fields; everything else stays server-derived.
async function buildSettingsPayload() {
  const persisted = await loadStudioSettings();
  const permissionMode = PERMISSION_TIER_IDS.includes(persisted.permissionMode)
    ? persisted.permissionMode
    : "reviewed_auto";
  return {
    workMode: "engineering",
    permissionMode,
    // Degraded through the same functions the run path uses, so the panel can never show a choice
    // the runtime would not actually receive.
    modelStrategy: mapModelStrategy(persisted.modelStrategy),
    modelNames: mapModelNames(persisted.modelNames),
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

async function readRunUserProgress(runId) {
  if (!runId) return [];
  const progressPath = path.join(workspace, ".asteria", "runs", runId, "user_progress.jsonl");
  return readJsonlTail(progressPath, 500);
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
/**
 * Body as raw bytes. readRequestBodyRaw decodes to utf8, which silently mangles binary uploads.
 *
 * Resolves BEFORE destroying on overflow: `request.destroy()` with no error argument emits
 * 'aborted'/'close' but neither 'end' nor 'error', so a promise that only listens for those two
 * never settles and the caller hangs forever.
 */
function readRequestBodyBinary(request, maxBytes) {
  return new Promise((resolve) => {
    const chunks = [];
    let size = 0;
    let settled = false;
    const settle = (value) => {
      if (settled) return;
      settled = true;
      resolve(value);
    };
    request.on("data", (chunk) => {
      if (settled) return;
      size += chunk.length;
      if (size > maxBytes) {
        settle(null);
        request.destroy();
        return;
      }
      chunks.push(Buffer.from(chunk));
    });
    request.on("end", () => settle(Buffer.concat(chunks)));
    request.on("error", () => settle(null));
    request.on("aborted", () => settle(null));
    request.on("close", () => settle(null));
  });
}

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
