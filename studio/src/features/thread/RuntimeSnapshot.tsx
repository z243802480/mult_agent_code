import React, { useState } from "react";
import { CircleDot, Loader2 } from "lucide-react";
import type { AnyRecord, OverviewPayload, PermissionPreview, RunDetailPayload, StudioEvent } from "../../types";
import { asArray, asRecord, firstText, stripBackendWording, textOrFallback } from "./threadUtils";
import { actionLabel, latestActiveEvent, runtimeProgress } from "./runtimeNarrative";
import { decisionHint, pendingDecisionSummary, preferredDecisionOptionId, runtimeNextStepSummary } from "./decisionGuidance";

function DecisionCard({
  runId,
  decision,
  onResolveDecision,
}: {
  runId: string;
  decision: AnyRecord;
  onResolveDecision: (runId: string, decisionId: string, optionId: string) => Promise<void>;
}) {
  const [busyOption, setBusyOption] = useState<string | null>(null);
  const decisionId = String(decision.decision_id ?? "");
  const recommended = preferredDecisionOptionId(decision) || String(decision.recommended_option_id ?? "");
  const options = asArray(decision.options) as AnyRecord[];
  const impact = asRecord(decision.impact);
  const metadata = asRecord(decision.metadata);
  const permissionPreview = asRecord(metadata.permission_preview) as PermissionPreview;
  const hint = decisionHint(decision);

  async function choose(optionId: string) {
    setBusyOption(optionId);
    try {
      await onResolveDecision(runId, decisionId, optionId);
    } finally {
      setBusyOption(null);
    }
  }

  if (!decisionId || !options.length) return null;
  return (
    <div className="decisionCard">
      <div className="decisionHeader">
        <CircleDot size={15} />
        <strong>{textOrFallback(decision.question, "Decision needed")}</strong>
      </div>
      <div className="decisionMeta">
        {hint && <span className="decisionHint">{hint}</span>}
        {permissionPreview.action && <span>{permissionPreview.action}</span>}
        {permissionPreview.scope && <span>{permissionPreview.scope}</span>}
        {permissionPreview.network && <span>{permissionPreview.network}</span>}
        {recommended && <span>Suggested: {recommended.replace(/_/g, " ")}</span>}
        {Object.keys(impact).length > 0 && (
          <span>
            Risk {textOrFallback(impact.risk, "medium")} / Budget {textOrFallback(impact.budget, "medium")}
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
  const nextActionValue = firstText(String(mainAction.next_command ?? ""), String(progress.next_command ?? ""));
  const pendingPermission = Boolean(
    activeEvent?.type === "permission_request" && activeEvent.status === "waiting_user" && activeEvent.job_id,
  );
  if (!decisions.length && !pendingPermission && !nextActionValue && !loop.exit_reason && !canReview && !canAccept) return false;
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
}: {
  overview: OverviewPayload | null;
  runDetail: RunDetailPayload | null;
  workspaceChangeCount?: number;
  events: StudioEvent[];
  onRuntimeAction: (nextAction: string) => Promise<void>;
  onOpenReview: () => Promise<void>;
  onResolveDecision: (runId: string, decisionId: string, optionId: string) => Promise<void>;
}) {
  // Hooks must run unconditionally and before any early return (rules of hooks). Diff-review gate
  // (slice #5): when an Accept is offered and the workspace has changes, require the user to open
  // the read-only diff review at least once before Accept is enabled. The key is (runId, changeCount)
  // so a new run or a changed diff re-arms the gate — "look before you accept" against the same scope.
  const [reviewedKey, setReviewedKey] = useState<string | null>(null);
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
  const nextActionValue = firstText(String(mainAction.next_command ?? ""), String(progress.next_command ?? ""));
  const mainActionKind = String(mainAction.kind ?? "");
  const pendingPermission = activeEvent?.type === "permission_request" && activeEvent.status === "waiting_user" && activeEvent.job_id
    ? activeEvent
    : null;
  const nextLabel = nextActionValue ? firstText(String(mainAction.label ?? ""), actionLabel(nextActionValue)) : "";
  const acceptReady = canAccept || /^(?:asteria\s+)?accept\b/i.test(nextActionValue);
  const reviewGateKey = `${runId}:${workspaceChangeCount}`;
  const needsDiffReview = acceptReady && workspaceChangeCount > 0 && reviewedKey !== reviewGateKey;
  const nextStep = runtimeNextStepSummary({
    decisions,
    nextActionValue,
    nextLabel,
    loop,
    canReview,
    canAccept,
    mainActionKind,
  }) || textOrFallback(
    loop.exit_reason ? `Stopped: ${userFacingStateLabel(String(loop.exit_reason))}` : "",
    "No action needed right now",
  );

  // Honest framing: under the default auto-promote config the edits are already in the real
  // workspace by the time Finalize is offered, so say so (change count is a real signal) rather
  // than implying a pre-write approval gate. Finalize records the run as done; it doesn't apply.
  const acceptStep = acceptReady && workspaceChangeCount > 0
    ? `${workspaceChangeCount} file${workspaceChangeCount === 1 ? "" : "s"} changed in your workspace — review the diff (keep or revert per file), then finalize.`
    : null;

  return (
    <section className="runtimeSnapshot compact" aria-label="Next action">
      <span className={`runtimeStatus ${decisions.length || pendingPermission ? "waiting_user" : canReview || canAccept || nextActionValue ? "running" : "completed"}`}>
        {decisions.length || pendingPermission ? "needs input" : acceptReady ? (workspaceChangeCount > 0 ? "applied" : "ready") : canReview ? "review" : nextActionValue ? "ready" : "stopped"}
      </span>
      <span className="runtimeSnapshotText">{acceptStep ?? nextStep}</span>
      <div className="runtimeSnapshotActions">
        {(canReview || acceptReady) && !decisions.length && !pendingPermission ? (
          <>
            {canReview ? (
              <button className="runtimeActionButton primary" type="button" onClick={() => void onRuntimeAction("review")}>
                Review
              </button>
            ) : null}
            {acceptReady ? (
              <>
                <button
                  className={`runtimeActionButton reviewChanges${needsDiffReview ? " gateActive" : ""}`}
                  type="button"
                  onClick={() => { setReviewedKey(reviewGateKey); void onOpenReview(); }}
                >
                  {workspaceChangeCount > 0 ? `Review ${workspaceChangeCount} changes` : "Review changes"}
                </button>
                <button
                  className="runtimeActionButton primary accept"
                  type="button"
                  disabled={needsDiffReview}
                  title={needsDiffReview ? `Review the ${workspaceChangeCount} change(s) before accepting` : undefined}
                  onClick={() => void onRuntimeAction(nextActionValue || "accept")}
                >
                  Finalize
                </button>
              </>
            ) : null}
          </>
        ) : decisions.length ? (
          <button className="runtimeActionButton" type="button" onClick={() => void onRuntimeAction("decide --list-pending")}>
            Decide
          </button>
        ) : nextActionValue ? (
          <button className="runtimeActionButton" type="button" onClick={() => void onRuntimeAction(nextActionValue)}>
            {nextLabel}
          </button>
        ) : null}
      </div>
      {runId && decisions.slice(0, 2).map((decision) => (
        <DecisionCard
          key={String(decision.decision_id ?? JSON.stringify(decision))}
          runId={runId}
          decision={decision}
          onResolveDecision={onResolveDecision}
        />
      ))}
    </section>
  );
}

export function userFacingStateLabel(value: string): string {
  const normalized = String(value || "").trim().toLowerCase();
  if (!normalized) return "";
  if (normalized.includes("provider") || normalized.includes("model-check")) return "model connection issue";
  if (normalized.includes("tool_failed")) return "tool step failed";
  if (normalized.includes("max_rounds")) return "needs a decision";
  if (normalized.includes("repair_limit") || normalized.includes("repair")) return "repair step needed — use Debug or resolve the decision card";
  if (normalized.includes("budget_hard_stop")) return "budget limit reached";
  return stripBackendWording(value.replace(/_/g, " "));
}

