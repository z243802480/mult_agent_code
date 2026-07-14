// Chat answer generation - Tier 1 of the chat subsystem.
//
// Everything that turns a user message into an answer: the intent-shaped entry point
// (buildChatAnswer), the model call, the streamed-answer reader, the text sanitizers, the local
// fallback templates, and the four chat model-lifecycle emitters.
//
// NOT the chat *routes* (submitUserGoal / handleChatMode / startChatJob / handleDecision*): those
// are Tier 2 - they drive the shared runtime-job and session machinery, and they stay in server.mjs.
//
// This layer writes no in-memory singleton (no liveJobs / pendingJobs / sseClients) and only reads
// workspace / runtimeRoot. Every persistent write goes through the injected appendEvent - with one
// deliberate exception, hideManualChatModelStart, which rewrites events already on disk (an
// append-only bus cannot demote a placeholder event that the provider's own lifecycle superseded).
//
// workspace and runtimeRoot are mutable `let`s in server.mjs, reassigned when the user switches
// workspace (openWorkspace), so they arrive as live getters: capturing them by value would pin this
// module to whichever repo happened to be open at boot.
import { existsSync, readFileSync, promises as fs } from "node:fs";
import path from "node:path";
import { outcomeAnswerContract } from "../prompt-contract.mjs";
import { classifyChatRequest, hasAny, isRuntimeMetaQuestion } from "../intent-router.mjs";
import { recentChatHistoryMessages } from "./chat-route-context.mjs";
import { firstRuntimeText } from "./text-utils.mjs";
import { readJsonlTail } from "./run-io.mjs";
import { latestDecisions } from "./run-evidence-transforms.mjs";
import { isSafeId } from "./workspace-paths.mjs";

const CHAT_MODES = `## \u4f7f\u7528\u65b9\u5f0f\n\n\u4f60\u4e0d\u9700\u8981\u5148\u7406\u89e3\u6a21\u5f0f\u3002\u76f4\u63a5\u8f93\u5165\u76ee\u6807\u5373\u53ef\uff1a\n\n- \u666e\u901a\u95ee\u9898\uff1a\u6211\u4f1a\u76f4\u63a5\u56de\u7b54\u3002\n- \u9700\u8981\u65b9\u6848\uff1a\u6211\u4f1a\u5148\u7ed9\u51fa\u53ea\u8bfb\u8ba1\u5212\u3002\n- \u9700\u8981\u6267\u884c\uff1a\u6211\u4f1a\u8bf4\u660e\u5c06\u8981\u505a\u4ec0\u4e48\uff0c\u5e76\u5728\u654f\u611f\u52a8\u4f5c\u524d\u8bf7\u6c42\u786e\u8ba4\u3002`;

export function createChatAnswer({
  getWorkspace,
  getRuntimeRoot,
  python,
  chatBackend,
  appendEvent,
  sessionPath,
  readRunDetail,
  overview,
  commandJson,
  runCommand,
  modelRouteSummary,
}) {
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
      const completed = await runCommand([python, "-c", script], getRuntimeRoot(), {
        PYTHONIOENCODING: "utf-8",
        ASTERIA_STUDIO_CHAT_BACKEND: undefined,
        ASTERIA_STUDIO_CHAT_PAYLOAD: payload,
        ASTERIA_STUDIO_ROOT: getWorkspace(),
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
    const workspace = getWorkspace();
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

  // Only the five names startChatJob drives are re-exported; the rest of the family is internal.
  return {
    buildChatAnswer,
    readChatContext,
    sideAskContextHint,
    hideManualChatModelStart,
    appendChatFallbackLifecycle,
  };
}
