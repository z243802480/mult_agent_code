// Chat + goal-submission routes - Tier 2 of the chat subsystem, and the last of the server.mjs split.
//
// The HTTP endpoint layer handleApi dispatches to: submitUserGoal (the main composer entry point,
// including intent routing and the chat/plan/run fork), handleRuntimeAction, the two decision
// endpoints, and handlePermission. Plus the machinery they own outright - the pending-approval map,
// the chat job and its SSE tail, the studio<->runtime command translation, and the acknowledgement
// and progress events they emit.
//
// What it deliberately does NOT own, and takes by injection instead:
//   - startRuntimeJob / runtimeCommand / phaseForMode - the execute layer. These routes *drive* it;
//     it also serves plan/run/review/resume paths that have nothing to do with chat, so it stays.
//   - the event bus (appendEvent/notifySSE), the job registry (liveJobs), the session lifecycle
//     (ensureSession/readSessionEvents), and the evidence readers - all shared with other routes.
//   - chat answer generation (./chat-answer.mjs), wired by server.mjs and passed in whole.
//
// `workspace` is a mutable `let` in server.mjs (reassigned by openWorkspace), so it arrives as a live
// getter: capturing it by value would pin these routes to whichever repo was open at boot.
import { existsSync, statSync, promises as fs } from "node:fs";
import path from "node:path";
import { intentAuditFor, routeUserIntent } from "../intent-router.mjs";
import { buildRouteMessageWithChatContext } from "./chat-route-context.mjs";
import { mapPermissionLevel, withPermissionLevel } from "./permission-level.mjs";
import { redact, redactText } from "./text-utils.mjs";
import { readJsonlTail } from "./run-io.mjs";
import { friendlyErrorText, friendlyErrorTitle, friendlyErrorSummary } from "./friendly-error.mjs";
import { latestDecisions } from "./run-evidence-transforms.mjs";
import { isSafeId } from "./workspace-paths.mjs";

export function createChatRoutes({
  getWorkspace,
  python,
  moduleName,
  routeClient,
  appendEvent,
  notifySSE,
  sessionPath,
  liveJobs,
  startRuntimeJob,
  applyAutonomyForTier,
  runtimeCommand,
  ensureSession,
  resolvedSessionId,
  readSessionEvents,
  currentRunId,
  commandJson,
  permissionPreview,
  runtimeActionFor,
  chatAnswer,
}) {
  // Destructured (not accessed as chatAnswer.x) so the moved call sites stay byte-identical.
  const {
    buildChatAnswer,
    readChatContext,
    sideAskContextHint,
    hideManualChatModelStart,
    appendChatFallbackLifecycle,
  } = chatAnswer;
  const pendingJobs = new Map(); // jobId -> { sessionId, mode, goal, command }

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
    //
    // AND: a guardrail that deliberately kept an explicit plan-of-content in chat
    // (routeUserIntent line ~103: "Plan a travel itinerary" → chat) must not be undone by the
    // orchestration layer merely echoing the raw requested mode back (source "explicit_mode").
    // routeUserIntent already weighed the explicit mode and chose chat on purpose; the echo is not
    // new signal. Without this guard the message ran a real `asteria plan` job while the audit still
    // read "answered in chat" — a lying audit event plus a nonsensical run on a non-coding request.
    const guardrailKeptInChat = route.mode === "chat" && orchestrated?.source === "explicit_mode";
    if (orchestrated && orchestrationHasRouteSignal(orchestrated) && !guardrailKeptInChat) {
      mode = orchestrated.mode;
      executionRoute = orchestrated;
      route.mode = mode;
      route.reason = orchestrated.reason || route.reason;
      route.source = orchestrated.source || route.source;
      route.capability_id = orchestrated.capability_id || null;
      // Confidence describes the FINAL decision. Leaving the base router's confidence here (e.g. the
      // "medium" of a run guess) would let the recomputed audit report a confidence that belongs to
      // the mode the override just discarded — the same stale-snapshot shape this override guards.
      route.confidence = orchestrated.confidence || "high";
      if (chatHandoff) {
        route.chat_execute_handoff = true;
        route.reason = orchestrated.reason
          ? `${orchestrated.reason} (re-routed with recent chat context)`
          : "Strong route re-evaluated after recent chat context.";
      }
    }

    // Compute the audit from the FINAL route, after any orchestration override — an audit built from
    // the pre-override route reports selected_mode=chat while a plan/run job actually starts. The
    // audit is the honest record of what happened; it must reflect the route the dispatcher uses.
    const audit = intentAuditFor(goal, requestedMode, permission, route);

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
      const preview = permissionPreviewForMode(mode);
      const pendingJobId = `pending-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`;
      pendingJobs.set(pendingJobId, { sessionId: activeSessionId, mode, goal, command });
      await appendEvent(activeSessionId, {
        type: "permission_request",
        status: "waiting_user",
        title: "待批准",
        summary: "这一步可能会修改文件或运行本地操作。确认后继续；取消则不做任何改动。",
        command,
        data: { permission_preview: preview },
        job_id: pendingJobId,
        content_delta: "确认后开始；取消则什么都不会运行。",
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
        title: "待批准",
        summary: action.permissionSummary,
        command: action.command,
        data: { permission_preview: action.permissionPreview },
        job_id: pendingJobId,
        content_delta: "确认后开始；取消则什么都不会运行。",
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
    const workspace = getWorkspace();
    const session = await ensureSession(sessionId);
    const activeSessionId = resolvedSessionId(session, sessionId);
    const runId = String(body?.run_id || "").trim();
    const decisionId = String(body?.decision_id || "").trim();
    const optionId = String(body?.option_id || "").trim();
    if (!isSafeId(runId) || !isSafeId(decisionId) || !isSafeDecisionOptionId(optionId)) {
      return { ok: false, error: "invalid decision selection" };
    }
    const runDir = path.join(workspace, ".asteria", "runs", runId);
    const decisions = latestDecisions(
      await readJsonlTail(path.join(runDir, "decisions.jsonl"), 200),
    );
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
    const workspace = getWorkspace();
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
    const decisions = latestDecisions(
      await readJsonlTail(path.join(runDir, "decisions.jsonl"), 200),
    );
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

  function permissionPreviewForMode(mode) {
    const normalized = String(mode || "").toLowerCase();
    if (normalized === "review") {
      return permissionPreview({
        action: "查看当前结果",
        impact: "读取项目改动与验证证据。",
        scope: "当前工作区（只读）",
        network: "不需要网络访问。",
        risk: "low",
        reversible: "不会修改任何文件。",
      });
    }
    return permissionPreview({
      action:
        normalized === "resume" || normalized === "continue" ? "继续当前目标" : "开始处理这个目标",
      impact: "可能会修改工作区文件并运行本地验证。",
      scope: "当前工作区",
      network: "可能会联系模型服务商；外部工具仍需单独批准。",
      risk: "medium",
      reversible: "改动在接受前都可查看。",
    });
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

  async function resolveStudioOrchestrationRoute(goal, requestedMode) {
    const workspace = getWorkspace();
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
    const workspace = getWorkspace();
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

  const CONTINUABLE_STUDIO_PHASES = new Set(["ACCEPTED", "DONE", "REVIEW"]);

  async function handleChatMode(
    sessionId,
    goal,
    route = null,
    audit = null,
    displayLevel = "main",
  ) {
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

  // Only the five endpoints handleApi dispatches to; everything else above is internal.
  return {
    submitUserGoal,
    handleRuntimeAction,
    handleDecisionResolve,
    handleDecisionAnswer,
    handlePermission,
  };
}
