import React from "react";
import type { RunDetailPayload } from "../types";
import { Metric } from "./Shared";
import { asArray, asRecord } from "../features/inspector/inspectorUtils";

/** Compact L3 workflow summary for Thread main path (S71). */
export function WorkflowMonitorCompact({ runDetail }: { runDetail: RunDetailPayload | null | undefined }) {
  const workflow = asRecord(runDetail?.orchestration_workflow);
  const steps = asArray(workflow.steps);
  if (!steps.length) return null;

  const workflowId = String(workflow.workflow_id ?? "workflow");
  const mergeStatus = String(workflow.merge_status ?? "n/a");
  const verifierStatus = String(workflow.verifier_status ?? "n/a");
  const checkpoint = String(workflow.resume_checkpoint ?? "none");
  const completed = Number(workflow.completed_steps ?? 0);
  const total = Number(workflow.step_count ?? steps.length);
  const failed = Number(workflow.failed_steps ?? 0);

  return (
    <section className="workflowMonitorCompact" aria-label="L3 workflow summary">
      <small>L3 workflow · {workflowId}</small>
      <div className="workflowMonitorCompactStats">
        <Metric label="Steps" value={`${completed}/${total}`} tone={failed ? "bad" : "good"} />
        <Metric label="Merge" value={mergeStatus} tone={mergeStatus === "passed" ? "good" : mergeStatus === "failed" ? "bad" : "warn"} />
        <Metric label="Verifier" value={verifierStatus} tone={verifierStatus === "passed" ? "good" : verifierStatus === "failed" ? "bad" : "warn"} />
        <Metric label="Checkpoint" value={checkpoint} tone={checkpoint !== "none" ? "good" : "warn"} />
      </div>
    </section>
  );
}
