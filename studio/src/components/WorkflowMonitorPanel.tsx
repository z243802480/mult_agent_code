import React from "react";
import type { AnyRecord, RunDetailPayload } from "../types";
import { Metric, Status } from "./Shared";
import { firstText } from "../narrative";
import { asArray, asRecord } from "../features/inspector/inspectorUtils";

export type WorkflowEvidenceSelection = {
  title: string;
  kind: string;
  summary: string;
  item: AnyRecord;
};

export function WorkflowMonitorPanel({
  runDetail,
  selectedKey,
  onSelectEvidence,
}: {
  runDetail: RunDetailPayload;
  selectedKey: string;
  onSelectEvidence: (selection: WorkflowEvidenceSelection) => void;
}) {
  const workflow = asRecord(runDetail.orchestration_workflow);
  const steps = asArray(workflow.steps) as AnyRecord[];
  if (!steps.length) return null;

  const workflowId = firstText(String(workflow.workflow_id ?? ""), "workflow");
  const mergeStatus = String(workflow.merge_status ?? "n/a");
  const verifierStatus = String(workflow.verifier_status ?? "n/a");

  return (
    <div className="evidenceBlock workflowMonitorPanel" aria-label="L3 workflow monitor">
      <small>Workflow monitor · {workflowId}</small>
      <div className="workflowMonitorStats">
        <Metric
          label="Steps"
          value={`${String(workflow.completed_steps ?? 0)}/${String(workflow.step_count ?? steps.length)}`}
          tone={Number(workflow.failed_steps ?? 0) ? "bad" : "good"}
        />
        <Metric label="Merge" value={mergeStatus} tone={mergeStatus === "passed" ? "good" : mergeStatus === "failed" ? "bad" : "warn"} />
        <Metric label="Verifier" value={verifierStatus} tone={verifierStatus === "passed" ? "good" : verifierStatus === "failed" ? "bad" : "warn"} />
        <Metric
          label="Checkpoint"
          value={String(workflow.resume_checkpoint ?? "none")}
          tone={workflow.resume_checkpoint ? "good" : "warn"}
        />
      </div>
      <div className="workflowMonitorList">
        {steps.map((step, index) => {
          const stepId = firstText(String(step.step_id ?? ""), `step-${index + 1}`);
          const status = String(step.status ?? "unknown");
          const kind = String(step.kind ?? "");
          const phaseId = String(step.phase_id ?? "");
          const isolation = asArray(step.isolation_unit_ids).map(String);
          const stepMerge = String(step.merge_status ?? "");
          const key = `workflow:${stepId}`;
          return (
            <button
              key={`${stepId}-${index}`}
              className={`workflowMonitorItem ${selectedKey === key ? "active" : ""}`}
              onClick={() =>
                onSelectEvidence({
                  title: stepId,
                  kind: "workflow",
                  summary: `${phaseId} · ${kind} · ${status}`,
                  item: step,
                })
              }
            >
              <span className="workflowMonitorSummary">
                <span>{phaseId}/{stepId}</span>
                <Status status={status as "completed" | "failed" | "running" | "blocked"} />
              </span>
              <pre>
                {[
                  `kind=${kind}`,
                  step.live_execution ? "live=true" : "",
                  isolation.length ? `isolation=${isolation.join(", ")}` : "",
                  stepMerge ? `merge=${stepMerge}` : "",
                  step.verifier_status ? `verifier=${String(step.verifier_status)}` : "",
                  asArray(step.worker_ids).length ? `workers=${asArray(step.worker_ids).join(", ")}` : "",
                ]
                  .filter(Boolean)
                  .join("\n")}
              </pre>
            </button>
          );
        })}
      </div>
    </div>
  );
}
