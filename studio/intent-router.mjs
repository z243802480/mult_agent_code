const EXPLICIT_MODES = new Set(["chat", "plan", "run", "review", "resume"]);

export function hasAny(text, needles) {
  const source = String(text);
  return needles.some((needle) => source.includes(needle));
}

export function isRuntimeMetaQuestion(input) {
  const lower = String(input || "").toLowerCase();
  return hasAny(lower, [
    "status", "next", "project status", "current run", "latest run", "blocked", "decisionpoint",
    "model route", "route rationale", "cheap mode", "cost mode", "why this model",
    "项目状态", "项目什么状态", "现在项目", "现在什么状态", "下一步", "最近的 run",
    "为什么用", "模型路线", "省钱模式", "后台", "run_loop",
  ]);
}

export function classifyChatRequest(message) {
  const lower = String(message || "").toLowerCase();
  if (/\b(itinerary|trip|travel|qingdao|xinjiang)\b/.test(lower) || hasAny(lower, ["旅游", "旅行", "行程", "青岛", "新疆"])) return "travel_plan";
  if (/\b(study plan|learn|learning|english)\b/.test(lower) || hasAny(lower, ["学习", "英语", "学习计划"])) return "learning_plan";
  if (/\b(prd|proposal|outline|content plan|writing plan)\b/.test(lower) || hasAny(lower, ["写作", "内容", "文案", "方案", "大纲"])) return "content_plan";
  return "general";
}

export function routeUserIntent(message, requestedMode = "auto", permission = "ask") {
  const explicit = EXPLICIT_MODES.has(requestedMode) ? requestedMode : "auto";
  const lower = String(message || "").toLowerCase();
  const kind = classifyChatRequest(message);
  const asksRuntime = isRuntimeMetaQuestion(lower);
  const wantsWorkspaceEdit = /\b(implement|fix|change|modify|edit|add|create|delete|rename|refactor|write|run tests?)\b/.test(lower)
    || hasAny(lower, ["实现", "修复", "修改", "编辑", "新增", "添加", "创建文件", "删除", "重构", "写入", "跑测试", "执行"]);
  const asksGeneral = !wantsWorkspaceEdit && !asksRuntime && (
    message.length < 240
    || /\b(what is|how to|why)\b/.test(lower)
    || hasAny(lower, ["怎么", "如何", "为什么", "是什么"])
  );
  const wantsWorkspaceAnalysis = /\b(analy[sz]e|compare|summari[sz]e|read-only)\b/.test(lower)
    || hasAny(lower, ["只读", "分析这个项目", "分析代码", "总结这个项目", "检查仓库"]);
  const asksForContentPlan = /\b(plan|itinerary|schedule|trip|travel|study plan|learning plan)\b/.test(lower)
    || hasAny(lower, ["计划", "规划", "行程", "旅游", "旅行", "学习计划", "方案"]);

  if (explicit === "chat") {
    return { mode: "chat", source: "user", permission, confidence: "explicit", intent_kind: kind, reason: "User selected chat; Studio will answer directly without starting a runtime run." };
  }
  if (explicit === "plan" && !wantsWorkspaceEdit && !wantsWorkspaceAnalysis) {
    return { mode: "chat", source: "guardrail", permission, confidence: "high", intent_kind: kind, reason: "Plan override looked like an ordinary content-planning request, so Studio answered in chat instead of starting the development runtime." };
  }
  if (explicit !== "auto") {
    return { mode: explicit, source: "user", permission, confidence: "explicit", intent_kind: kind, reason: `User selected ${explicit}; intent router will not override the explicit mode.` };
  }
  if (wantsWorkspaceAnalysis) {
    return { mode: "plan", source: "auto", permission, confidence: "medium", intent_kind: kind, reason: "This looks like read-only workspace analysis, so Studio routes it to the development planner." };
  }
  if (asksRuntime || asksGeneral || (asksForContentPlan && !wantsWorkspaceEdit && !wantsWorkspaceAnalysis)) {
    return { mode: "chat", source: "auto", permission, confidence: asksRuntime ? "high" : "medium", intent_kind: kind, reason: "This looks like a conversational/content request, so Studio keeps it in chat and does not start the runtime." };
  }
  if (wantsWorkspaceEdit) {
    if (permission === "allow") {
      return { mode: "run", source: "auto", permission, confidence: "medium", intent_kind: kind, reason: "This looks like a workspace-changing task and permission allows execution, so Studio routes it to run." };
    }
    return { mode: "plan", source: "auto", permission, confidence: "medium", intent_kind: kind, reason: "This looks like a workspace-changing task; because write permission is not pre-approved, Studio routes it to a read-only development plan first." };
  }
  if (message.length >= 240) {
    return { mode: "chat", source: "auto", permission, confidence: "low", intent_kind: kind, reason: "This is a large content request without workspace-change intent, so Studio answers in chat instead of creating runtime artifacts." };
  }
  return { mode: "chat", source: "auto", permission, confidence: "low", intent_kind: kind, reason: "No workspace execution intent was detected, so Studio keeps the message in chat." };
}

export function intentAuditFor(message, requestedMode, permission, route) {
  const intentKind = route.intent_kind || classifyChatRequest(message);
  const routeMode = route.mode || "chat";
  return {
    schema_version: "0.1.0",
    route: routeMode,
    intent_kind: intentKind,
    permission_effect: permissionEffectFor(routeMode, permission),
    requested_mode: requestedMode || "auto",
    selected_mode: routeMode,
    route_source: route.source || "auto",
    confidence: route.confidence || "unknown",
    reason: route.reason || "",
    user_visible: false,
    prompt_enrichment: promptEnrichmentFor(intentKind, routeMode),
  };
}

export function permissionEffectFor(mode, permission) {
  if (mode === "chat") return "read_only";
  if (mode === "plan") return "read_only";
  if (mode === "run") return permission === "allow" ? "execute_allowed" : "needs_permission";
  if (mode === "review") return "read_only_evidence";
  if (mode === "resume") return permission === "allow" ? "execute_allowed" : "needs_permission";
  return "unknown";
}

export function promptEnrichmentFor(kind, mode) {
  if (mode !== "chat") return "runtime_mode_no_chat_enrichment";
  if (kind === "general") return "general_assistant_answer";
  return "outcome_oriented_answer_contract";
}
