import React, { useState } from "react";
import { CircleDot, Loader2 } from "lucide-react";
import type {
  AnyRecord,
  OverviewPayload,
  PermissionPreview,
  RunDetailPayload,
  StudioEvent,
} from "../../types";
import { asArray, asRecord, firstText, stripBackendWording, textOrFallback } from "./threadUtils";
import { actionLabel, latestActiveEvent, runtimeProgress } from "./runtimeNarrative";
import {
  decisionHint,
  preferredDecisionOptionId,
  runtimeNextStepSummary,
} from "./decisionGuidance";

// Exit reasons that mean the loop finished NORMALLY (the model stopped cleanly / the task completed),
// as opposed to a genuine interruption (tool_failed, *_budget_exhausted, loop_no_progress, max_rounds,
// budget_hard_stop). A successful completion is already conveyed by the final answer + the green
// "验证通过" badge, so it must NOT keep a dead "已停止: completed" next-step bar alive, nor be phrased
// as "已停止" (stopped) — that word implies interruption and reads as a contradiction under the badge.
const SUCCESS_EXIT_REASONS = new Set(["completed", "stop"]);

// A run's exit_reason is "noteworthy" only when it is present AND not a clean completion — i.e. it
// names something the user might act on or should be told stopped. A clean completion is silent.
function noteworthyExitReason(exitReason: unknown): boolean {
  const value = String(exitReason ?? "");
  return Boolean(value) && !SUCCESS_EXIT_REASONS.has(value);
}

// Localize a coarse low/medium/high tier for display (risk / budget). Data values stay English;
// only the surfaced label reads in Chinese so the card never mixes languages.
function tierLabel(tier: string): string {
  const map: Record<string, string> = { low: "低", medium: "中", high: "高" };
  return map[String(tier).toLowerCase()] ?? String(tier);
}

function DecisionCard({
  runId,
  decision,
  onResolveDecision,
  onAnswerDecision,
}: {
  runId: string;
  decision: AnyRecord;
  onResolveDecision: (runId: string, decisionId: string, optionId: string) => Promise<void>;
  onAnswerDecision?: (runId: string, decisionId: string, answer: string) => Promise<void>;
}) {
  const [busyOption, setBusyOption] = useState<string | null>(null);
  const [answer, setAnswer] = useState("");
  const [answering, setAnswering] = useState(false);
  const decisionId = String(decision.decision_id ?? "");
  const recommended =
    preferredDecisionOptionId(decision) || String(decision.recommended_option_id ?? "");
  const options = asArray(decision.options) as AnyRecord[];
  const impact = asRecord(decision.impact);
  const metadata = asRecord(decision.metadata);
  const permissionPreview = asRecord(metadata.permission_preview) as PermissionPreview;
  const hint = decisionHint(decision);
  const isOpenQuestion = String(metadata.kind ?? "") === "open_question";

  async function choose(optionId: string) {
    setBusyOption(optionId);
    try {
      await onResolveDecision(runId, decisionId, optionId);
    } finally {
      setBusyOption(null);
    }
  }

  async function submitAnswer() {
    const text = answer.trim();
    if (!text || !onAnswerDecision) return;
    setAnswering(true);
    try {
      await onAnswerDecision(runId, decisionId, text);
      setAnswer("");
    } finally {
      setAnswering(false);
    }
  }

  // Open-ended ask (Claude Code "ask"): the loop paused with a free-text question and no fixed
  // options — you answer in prose and the same loop resumes with your answer as guidance.
  if (decisionId && isOpenQuestion && onAnswerDecision) {
    return (
      <div className="decisionCard openQuestion">
        <div className="decisionHeader">
          <CircleDot size={15} />
          <strong>{textOrFallback(decision.question, "智能体有个问题要问你")}</strong>
        </div>
        {hint && (
          <div className="decisionMeta">
            <span className="decisionHint">{hint}</span>
          </div>
        )}
        <textarea
          className="openQuestionInput"
          value={answer}
          placeholder="输入你的回答…"
          rows={2}
          disabled={answering}
          onChange={(event) => setAnswer(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
              event.preventDefault();
              void submitAnswer();
            }
          }}
        />
        <div className="openQuestionActions">
          <button
            className="runtimeActionButton primary"
            disabled={!answer.trim() || answering}
            onClick={() => void submitAnswer()}
          >
            {answering ? <Loader2 size={13} className="spinning" /> : "发送回答"}
          </button>
          <small className="openQuestionHint">⌘/Ctrl + Enter</small>
        </div>
      </div>
    );
  }

  if (!decisionId || !options.length) return null;
  return (
    <div className="decisionCard">
      <div className="decisionHeader">
        <CircleDot size={15} />
        <strong>{textOrFallback(decision.question, "需要你决定")}</strong>
      </div>
      <div className="decisionMeta">
        {hint && <span className="decisionHint">{hint}</span>}
        {permissionPreview.action && <span>{permissionPreview.action}</span>}
        {permissionPreview.scope && <span>{permissionPreview.scope}</span>}
        {permissionPreview.network && <span>{permissionPreview.network}</span>}
        {recommended && <span>建议: {recommended.replace(/_/g, " ")}</span>}
        {Object.keys(impact).length > 0 && (
          <span>
            风险 {tierLabel(textOrFallback(impact.risk, "medium"))} / 预算{" "}
            {tierLabel(textOrFallback(impact.budget, "medium"))}
          </span>
        )}
      </div>
      <div className="decisionOptions">
        {options.map((option) => {
          const optionId = String(option.option_id ?? "");
          if (!optionId) return null;
          const label = textOrFallback(option.label ?? option.title, optionId);
          const description = String(option.description ?? option.tradeoff ?? "").trim();
          return (
            <button
              key={optionId}
              className={optionId === recommended ? "recommended" : ""}
              disabled={Boolean(busyOption)}
              onClick={() => void choose(optionId)}
            >
              <span>{label}</span>
              {description && <small>{description}</small>}
              {busyOption === optionId && <Loader2 size={13} className="spinning" />}
            </button>
          );
        })}
      </div>
    </div>
  );
}

/**
 * Single source of truth for "does this run have an actionable next step?" The bottom Next-action
 * bar (this component) and the per-turn SuggestedActions chips both key off this so the thread never
 * shows two competing next-step prompts — e.g. a stale inline "Decide" chip while the run has
 * actually passed review and the bar is offering Accept. When this is true the bar owns the next
 * step and the inline chips defer; when it is false (no lifecycle state) the inline chips are the
 * only hint and still render.
 */
export function runtimeSnapshotActionable(
  overview: OverviewPayload | null,
  runDetail: RunDetailPayload | null,
  events: StudioEvent[],
): boolean {
  const workflow = asRecord(overview?.workflow);
  const canReview = Boolean(workflow.can_review);
  const canAccept = Boolean(workflow.can_accept);
  const progress = runtimeProgress(runDetail);
  if (!Object.keys(progress).length && !runDetail?.ok && !canReview && !canAccept) return false;
  const activeEvent = latestActiveEvent(events);
  const loop = asRecord(progress.loop);
  const decisions = (runDetail?.decision_requests ?? []) as AnyRecord[];
  const mainAction = asRecord(runDetail?.main_action);
  const nextActionValue = firstText(
    String(mainAction.next_command ?? ""),
    String(progress.next_command ?? ""),
  );
  const pendingPermission = Boolean(
    activeEvent?.type === "permission_request" &&
    activeEvent.status === "waiting_user" &&
    activeEvent.job_id,
  );
  if (
    !decisions.length &&
    !pendingPermission &&
    !nextActionValue &&
    !noteworthyExitReason(loop.exit_reason) &&
    !canReview &&
    !canAccept
  )
    return false;
  return true;
}

export function RuntimeSnapshot({
  overview,
  runDetail,
  workspaceChangeCount = 0,
  events,
  onRuntimeAction,
  onOpenReview,
  onResolveDecision,
  onAnswerDecision,
}: {
  overview: OverviewPayload | null;
  runDetail: RunDetailPayload | null;
  workspaceChangeCount?: number;
  events: StudioEvent[];
  onRuntimeAction: (nextAction: string) => Promise<void>;
  onOpenReview: () => Promise<void>;
  onResolveDecision: (runId: string, decisionId: string, optionId: string) => Promise<void>;
  onAnswerDecision?: (runId: string, decisionId: string, answer: string) => Promise<void>;
}) {
  // No forced review gate. Mainstream coding agents (Claude Code, Cursor, Copilot) don't block
  // "done" behind a mandatory diff review — the diff is available to look at, and real questions get
  // resolved inline via the permission/decision cards, not a pre-accept approval wall. So the diff
  // button below just opens the read-only diff (optional); it never disables Mark done.
  const [busy, setBusy] = useState(false);
  if (!runtimeSnapshotActionable(overview, runDetail, events)) return null;

  const workflow = asRecord(overview?.workflow);
  const canReview = Boolean(workflow.can_review);
  const canAccept = Boolean(workflow.can_accept);
  const progress = runtimeProgress(runDetail);
  const activeEvent = latestActiveEvent(events);
  const loop = asRecord(progress.loop);
  const decisions = (runDetail?.decision_requests ?? []) as AnyRecord[];
  const mainAction = asRecord(runDetail?.main_action);
  const runId = String(runDetail?.run_id ?? "");
  const nextActionValue = firstText(
    String(mainAction.next_command ?? ""),
    String(progress.next_command ?? ""),
  );
  const mainActionKind = String(mainAction.kind ?? "");
  const pendingPermission =
    activeEvent?.type === "permission_request" &&
    activeEvent.status === "waiting_user" &&
    activeEvent.job_id
      ? activeEvent
      : null;
  // Prefer the localized actionLabel over the raw backend main_action.label (which is an English
  // command name like "Debug") so the next-step button reads in Chinese.
  const nextLabel = nextActionValue
    ? firstText(actionLabel(nextActionValue), String(mainAction.label ?? ""))
    : "";
  const acceptReady = canAccept || /^(?:asteria\s+)?accept\b/i.test(nextActionValue);
  const nextStep =
    runtimeNextStepSummary({
      decisions,
      nextActionValue,
      nextLabel,
      loop,
      canReview,
      canAccept,
      mainActionKind,
    }) ||
    textOrFallback(
      noteworthyExitReason(loop.exit_reason)
        ? `已停止: ${userFacingStateLabel(String(loop.exit_reason))}`
        : "",
      "当前没有需要处理的操作",
    );

  // Honest framing: under the default auto-promote config the edits are already in the real
  // workspace by the time Finalize is offered, so say so (change count is a real signal) rather
  // than implying a pre-write approval gate. Finalize records the run as done; it doesn't apply.
  const acceptStep =
    acceptReady && workspaceChangeCount > 0
      ? `工作区有 ${workspaceChangeCount} 个文件已改动——打开差异逐个保留或还原,或直接标记完成。`
      : null;

  // Gate the primary workflow actions so a double-click can't fire duplicate review/accept/decide
  // API calls (the sibling decision + permission cards already gate on busy; this bar did not).
  // (busy state is declared with the other hooks above, before the early return.)
  const runAction = async (fn: () => Promise<void> | void) => {
    if (busy) return;
    setBusy(true);
    try {
      await fn();
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="runtimeSnapshot compact" aria-label="下一步">
      <span
        className={`runtimeStatus ${decisions.length || pendingPermission ? "waiting_user" : canReview || canAccept || nextActionValue ? "running" : "completed"}`}
      >
        {decisions.length || pendingPermission
          ? "待你处理"
          : acceptReady
            ? workspaceChangeCount > 0
              ? "已应用"
              : "就绪"
            : canReview
              ? "待查看"
              : nextActionValue
                ? "就绪"
                : "已停止"}
      </span>
      <span className="runtimeSnapshotText">{acceptStep ?? nextStep}</span>
      <div className="runtimeSnapshotActions">
        {(canReview || acceptReady) && !decisions.length && !pendingPermission ? (
          <>
            {canReview ? (
              <button
                className="runtimeActionButton primary"
                type="button"
                disabled={busy}
                onClick={() => void runAction(() => onRuntimeAction("review"))}
              >
                {busy ? <Loader2 size={13} className="spinning" /> : "查看"}
              </button>
            ) : null}
            {acceptReady ? (
              <>
                <button
                  className="runtimeActionButton reviewChanges"
                  type="button"
                  disabled={busy}
                  onClick={() => void runAction(() => onOpenReview())}
                >
                  {workspaceChangeCount > 0 ? `查看 ${workspaceChangeCount} 处改动` : "查看改动"}
                </button>
                <button
                  className="runtimeActionButton primary accept"
                  type="button"
                  disabled={busy}
                  onClick={() => void runAction(() => onRuntimeAction(nextActionValue || "accept"))}
                >
                  {busy ? <Loader2 size={13} className="spinning" /> : "标记完成"}
                </button>
              </>
            ) : null}
          </>
        ) : decisions.length ? (
          <button
            className="runtimeActionButton"
            type="button"
            disabled={busy}
            onClick={() => void runAction(() => onRuntimeAction("decide --list-pending"))}
          >
            决定
          </button>
        ) : nextActionValue ? (
          <button
            className="runtimeActionButton"
            type="button"
            disabled={busy}
            onClick={() => void runAction(() => onRuntimeAction(nextActionValue))}
          >
            {nextLabel}
          </button>
        ) : null}
      </div>
      {runId &&
        decisions
          .slice(0, 2)
          .map((decision) => (
            <DecisionCard
              key={String(decision.decision_id ?? JSON.stringify(decision))}
              runId={runId}
              decision={decision}
              onResolveDecision={onResolveDecision}
              onAnswerDecision={onAnswerDecision}
            />
          ))}
    </section>
  );
}

export function userFacingStateLabel(value: string): string {
  const normalized = String(value || "")
    .trim()
    .toLowerCase();
  if (!normalized) return "";
  // A clean completion is not a failure state — never surface it as "已停止". Callers already gate on
  // noteworthyExitReason, so this is defensive: if ever asked to label a success reason, stay silent.
  if (SUCCESS_EXIT_REASONS.has(normalized)) return "";
  if (normalized.includes("provider") || normalized.includes("model-check"))
    return "模型连接出问题了";
  if (normalized.includes("tool_failed")) return "某一步失败了";
  if (normalized.includes("max_rounds")) return "需要一个决定";
  // S78 auto-repair terminal reasons (must precede the generic "repair" catch below, since
  // "repair_budget_exhausted" also contains "repair"): auto-repair already retried and stopped
  // honestly, so frame it as "I tried" — not "want me to keep trying?".
  if (normalized.includes("repair_budget_exhausted"))
    return "我自动重试了几次还是失败——你来看看,还是换个思路?";
  if (normalized.includes("loop_no_progress"))
    return "同样的失败一直重复、毫无进展——你来看看,还是换个思路?";
  // S79 auto-replan terminal reason (must precede the generic "replan"/"repair" catch, since
  // "replan_budget_exhausted" contains "replan"): auto-replan re-approached the task and stopped.
  if (normalized.includes("replan_budget_exhausted"))
    return "我换了两次思路重做还是失败——你来看看,还是重新规划任务?";
  if (normalized.includes("repair_limit") || normalized.includes("repair"))
    return "某一步失败了——要我继续尝试,还是换个思路?";
  if (normalized.includes("budget_hard_stop")) return "已暂停——需要你的输入";
  return stripBackendWording(value.replace(/_/g, " "));
}
