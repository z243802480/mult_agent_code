import React, { useMemo } from "react";
import type { AnyRecord, RunDetailPayload } from "../types";

const PHASES = [
  { id: "understand", label: "Understand" },
  { id: "plan", label: "Plan" },
  { id: "execute", label: "Execute" },
  { id: "review", label: "Verify" },
  { id: "result", label: "Result" },
] as const;

function runtimeProgress(runDetail: RunDetailPayload | null): AnyRecord {
  const direct = (runDetail?.runtime_progress ?? {}) as AnyRecord;
  if (Object.keys(direct).length) return direct;
  const finalSummary = (runDetail?.final_report_summary ?? {}) as AnyRecord;
  const finalProgress = (finalSummary.runtime_progress ?? {}) as AnyRecord;
  if (Object.keys(finalProgress).length) return finalProgress;
  const loopSummary = (runDetail?.run_loop_summary ?? {}) as AnyRecord;
  return (loopSummary.runtime_progress ?? {}) as AnyRecord;
}

function activePhaseId(progress: AnyRecord, isRunning: boolean): string {
  const explicit = String(progress.current_phase ?? progress.phase ?? "").toLowerCase();
  if (explicit.includes("plan")) return "plan";
  if (explicit.includes("execute") || explicit.includes("tool")) return "execute";
  if (explicit.includes("review") || explicit.includes("verify")) return "review";
  if (explicit.includes("result") || explicit.includes("accept")) return "result";
  if (explicit.includes("understand")) return "understand";
  const workflow = String(progress.workflow_state ?? "").toLowerCase();
  if (workflow.includes("review")) return "review";
  if (workflow.includes("accept") || workflow.includes("done")) return "result";
  if (workflow.includes("execute") || workflow.includes("run")) return "execute";
  if (workflow.includes("plan")) return "plan";
  return isRunning ? "execute" : "result";
}

export function WorkflowPhaseStrip({
  runDetail,
  isRunning,
  compact = false,
  hidden = false,
}: {
  runDetail: RunDetailPayload | null;
  isRunning: boolean;
  compact?: boolean;
  hidden?: boolean;
}) {
  const progress = useMemo(() => runtimeProgress(runDetail), [runDetail]);
  const active = activePhaseId(progress, isRunning);
  const activeIndex = PHASES.findIndex((phase) => phase.id === active);

  if (hidden) return null;
  if (!runDetail?.ok && !isRunning) return null;

  if (compact) {
    return (
      <div className="workflowPhaseInline" aria-label="Task phase">
        {PHASES.map((phase, index) => {
          const state = index < activeIndex ? "done" : index === activeIndex ? "active" : "pending";
          return (
            <span key={phase.id} className={`workflowPhaseDot ${state}`} title={phase.label}>
              {phase.label}
            </span>
          );
        })}
      </div>
    );
  }

  return (
    <div className="workflowPhaseStrip" aria-label="Task phase">
      {PHASES.map((phase, index) => {
        const state = index < activeIndex ? "done" : index === activeIndex ? "active" : "pending";
        return (
          <span key={phase.id} className={`workflowPhasePill ${state}`}>
            {phase.label}
          </span>
        );
      })}
    </div>
  );
}
