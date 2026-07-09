import type { AnyRecord } from "../../types";
import { asArray, asRecord } from "./threadUtils";

export function decisionMetadata(decision: AnyRecord): AnyRecord {
  return asRecord(decision.metadata);
}

export function decisionKind(decision: AnyRecord): string {
  return String(decisionMetadata(decision).kind || "").trim();
}

export function preferredDecisionOptionId(decision: AnyRecord): string {
  const metadata = decisionMetadata(decision);
  const kind = decisionKind(decision);
  const requestTypes = asArray(metadata.request_types).map((item) => String(item));
  const options = asArray(decision.options) as AnyRecord[];

  if (kind === "execution_policy_approval") {
    if (options.some((option) => option.option_id === "approve_once")) return "approve_once";
  }
  if (kind === "runtime_request" || requestTypes.length > 0) {
    if (options.some((option) => option.option_id === "review_contract")) return "review_contract";
  }
  if (kind === "replan_decision" || metadata.reason === "repair_limit") {
    if (options.some((option) => option.option_id === "create_repair_task"))
      return "create_repair_task";
  }
  if (options.some((option) => option.option_id === "review_contract")) return "review_contract";

  const recommended = String(decision.recommended_option_id ?? "").trim();
  if (recommended) return recommended;
  const fallback = String(decision.default_option_id ?? "").trim();
  if (fallback) return fallback;
  return String(options[0]?.option_id ?? "").trim();
}

export function decisionHint(decision: AnyRecord): string {
  const kind = decisionKind(decision);
  const preferred = preferredDecisionOptionId(decision);

  if (kind === "runtime_request") {
    return preferred === "review_contract"
      ? "允许扩大范围——你确认后会自动继续工作。"
      : "确认智能体该如何处理这件事。";
  }
  if (kind === "execution_policy_approval") {
    return preferred === "approve_once"
      ? "本次批准这条命令——确认后智能体会继续。"
      : "批准这个待处理的操作,智能体才能继续。";
  }
  if (kind === "replan_decision" || asRecord(decision.metadata).reason === "repair_limit") {
    return "某一步失败了——要我继续尝试,还是换个思路?";
  }
  return "";
}

export function pendingDecisionSummary(decisions: AnyRecord[]): string {
  if (!decisions.length) return "";
  const primary = decisions[0];
  const hint = decisionHint(primary);
  if (hint) return hint;
  const count = decisions.length;
  return `有 ${count} 个决定需要你处理。`;
}

export function runtimeNextStepSummary(params: {
  decisions: AnyRecord[];
  nextActionValue: string;
  nextLabel: string;
  loop: AnyRecord;
  canReview: boolean;
  canAccept: boolean;
  mainActionKind: string;
}): string {
  const { decisions, nextActionValue, nextLabel, loop, canReview, canAccept, mainActionKind } =
    params;

  if (decisions.length) return pendingDecisionSummary(decisions);
  // Honest affordance, not a verdict: the frontend only knows the run reached an accept/review-able
  // state from a capability flag — it must not assert "Review passed" / "Task complete" (a verdict it
  // doesn't hold). State + next action only; any "passed" wording must come from a real runtime event.
  if (canAccept) return "改动已应用到你的工作区——查看差异后标记完成。";
  if (canReview) return "可以查看了——打开改动进行核对。";

  const normalized = nextActionValue.trim().toLowerCase();
  const exitReason = String(loop.exit_reason ?? "").toLowerCase();

  // S78 auto-repair terminal reasons must be matched before the generic repair/debug catch below
  // (which recommends "debug"): auto-repair already retried within budget and stopped honestly, so
  // frame it as "I tried" rather than "want me to keep trying?".
  if (exitReason.includes("repair_budget_exhausted")) {
    return "我自动重试了几次还是失败——你来看看,还是换个思路?";
  }
  if (exitReason.includes("loop_no_progress")) {
    return "同样的失败一直重复、毫无进展——你来看看,还是换个思路?";
  }
  // S79 auto-replan terminal reason (must precede any generic replan/repair catch, since
  // "replan_budget_exhausted" contains "replan"): auto-replan already re-approached this task within
  // budget and stopped honestly — recommend a human goal-level replan, not "keep trying?".
  if (exitReason.includes("replan_budget_exhausted")) {
    return "我换了两次思路重做还是失败——你来看看,还是重新规划任务?";
  }
  if (
    mainActionKind === "debug" ||
    normalized.includes("debug") ||
    normalized.includes("repair") ||
    exitReason.includes("repair")
  ) {
    return "某一步失败了——要我继续尝试,还是换个思路?";
  }
  if (normalized.includes("decide")) {
    return "处理下面的决定卡片以继续。";
  }
  if (
    normalized.includes("resume") ||
    normalized.includes("continue") ||
    normalized.includes("run")
  ) {
    return `可以继续了——点击 ${nextLabel || "继续"}。`;
  }
  if (exitReason.includes("max_rounds") || exitReason.includes("budget")) {
    return "已暂停——查看下方的决定卡片或下一步操作。";
  }
  if (nextActionValue) return `可以${nextLabel || "进行下一步"}了。`;
  return "";
}
