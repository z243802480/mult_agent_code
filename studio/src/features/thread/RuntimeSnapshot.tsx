import React, { useState } from "react";
import { CircleDot, Loader2 } from "lucide-react";
import type { AnyRecord, OverviewPayload, RunDetailPayload, StudioEvent } from "../../types";
import { PermissionCard } from "../../components/PermissionCard";
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


export function RuntimeSnapshot({
  overview,
  runDetail,
  events,
  onRuntimeAction,
  onResolveDecision,
  onPermit,
}: {
  overview: OverviewPayload | null;
  runDetail: RunDetailPayload | null;
  events: StudioEvent[];
  onRuntimeAction: (nextAction: string) => Promise<void>;
  onResolveDecision: (runId: string, decisionId: string, optionId: string) => Promise<void>;
  onPermit: (jobId: string, action: "allow" | "deny") => Promise<void>;
}) {
  const workflow = asRecord(overview?.workflow);
  const canReview = Boolean(workflow.can_review);
  const canAccept = Boolean(workflow.can_accept);
  const progress = runtimeProgress(runDetail);
  if (!Object.keys(progress).length && !runDetail?.ok && !canReview && !canAccept) return null;
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
  if (!decisions.length && !pendingPermission && !nextActionValue && !loop.exit_reason && !canReview && !canAccept) return null;

  return (
    <section className="runtimeSnapshot compact" aria-label="Next action">
      <span className={`runtimeStatus ${decisions.length || pendingPermission ? "waiting_user" : canReview || canAccept || nextActionValue ? "running" : "completed"}`}>
        {decisions.length || pendingPermission ? "needs input" : canAccept ? "accept" : canReview ? "review" : nextActionValue ? "ready" : "stopped"}
      </span>
      <span className="runtimeSnapshotText">{nextStep}</span>
      <div className="runtimeSnapshotActions">
        {(canReview || canAccept) && !decisions.length && !pendingPermission ? (
          <>
            {canReview ? (
              <button className="runtimeActionButton primary" type="button" onClick={() => void onRuntimeAction("review")}>
                Review
              </button>
            ) : null}
            {canAccept ? (
              <button className="runtimeActionButton primary accept" type="button" onClick={() => void onRuntimeAction("accept")}>
                Accept
              </button>
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
      {pendingPermission && (
        <PermissionCard
          event={pendingPermission}
          onAllow={() => onPermit(pendingPermission.job_id!, "allow")}
          onDeny={() => onPermit(pendingPermission.job_id!, "deny")}
        />
      )}
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

