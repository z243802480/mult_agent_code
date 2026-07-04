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
    if (options.some((option) => option.option_id === "create_repair_task")) return "create_repair_task";
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
      ? "Allow the expanded scope — work continues automatically after you confirm."
      : "Confirm how the agent should handle this.";
  }
  if (kind === "execution_policy_approval") {
    return preferred === "approve_once"
      ? "Approve this command once — the agent will continue after confirmation."
      : "Approve the pending operation so the agent can continue.";
  }
  if (kind === "replan_decision" || asRecord(decision.metadata).reason === "repair_limit") {
    return "A step failed — want me to keep trying or take a different approach?";
  }
  return "";
}

export function pendingDecisionSummary(decisions: AnyRecord[]): string {
  if (!decisions.length) return "";
  const primary = decisions[0];
  const hint = decisionHint(primary);
  if (hint) return hint;
  const count = decisions.length;
  return `${count} decision${count === 1 ? "" : "s"} need your input.`;
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
  const {
    decisions,
    nextActionValue,
    nextLabel,
    loop,
    canReview,
    canAccept,
    mainActionKind,
  } = params;

  if (decisions.length) return pendingDecisionSummary(decisions);
  // Honest affordance, not a verdict: the frontend only knows the run reached an accept/review-able
  // state from a capability flag — it must not assert "Review passed" / "Task complete" (a verdict it
  // doesn't hold). State + next action only; any "passed" wording must come from a real runtime event.
  if (canAccept) return "Changes are applied to your workspace — review the diff, then mark it done.";
  if (canReview) return "Ready for review — open the changes to verify.";

  const normalized = nextActionValue.trim().toLowerCase();
  const exitReason = String(loop.exit_reason ?? "").toLowerCase();

  // S78 auto-repair terminal reasons must be matched before the generic repair/debug catch below
  // (which recommends "debug"): auto-repair already retried within budget and stopped honestly, so
  // frame it as "I tried" rather than "want me to keep trying?".
  if (exitReason.includes("repair_budget_exhausted")) {
    return "I auto-retried a few times but it still fails — take a look or try a different approach?";
  }
  if (exitReason.includes("loop_no_progress")) {
    return "The same failure keeps repeating with no progress — take a look or try a different approach?";
  }
  if (
    mainActionKind === "debug"
    || normalized.includes("debug")
    || normalized.includes("repair")
    || exitReason.includes("repair")
  ) {
    return "A step failed — want me to keep trying or take a different approach?";
  }
  if (normalized.includes("decide")) {
    return "Resolve the decision card below to continue.";
  }
  if (normalized.includes("resume") || normalized.includes("continue") || normalized.includes("run")) {
    return `Ready to continue — tap ${nextLabel || "Continue"}.`;
  }
  if (exitReason.includes("max_rounds") || exitReason.includes("budget")) {
    return "Paused — check the decision card or next action below.";
  }
  if (nextActionValue) return `Ready for ${nextLabel || "the next step"}.`;
  return "";
}
