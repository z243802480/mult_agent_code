/**
 * Build L3 workflow monitor projection from orchestration_runner_state.jsonl (S68).
 * Mirrors Python orchestration_workflow_monitor.py for Studio server evidence client.
 */

function asRecord(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : {};
}

function mergeStatusFromRecord(record) {
  const variables = asRecord(record.variables);
  const swarm = asRecord(record.swarm_plan);
  if (variables.merge_gate_ok === true) return "passed";
  if (variables.merge_gate_ok === false) return "failed";
  if (swarm.merge_status) return String(swarm.merge_status);
  if (record.kind === "merge_checkpoint") {
    if (variables.merge_gate_ok === false) return "failed";
    return record.status === "completed" ? "passed" : "pending";
  }
  return null;
}

function isolationUnitIds(record) {
  const variables = asRecord(record.variables);
  const swarm = asRecord(record.swarm_plan);
  const ids = [];
  for (const source of [variables, swarm]) {
    if (Array.isArray(source.isolation_unit_ids)) {
      for (const item of source.isolation_unit_ids) {
        if (item) ids.push(String(item));
      }
    }
  }
  return ids;
}

export function projectWorkflowStep(record) {
  const row = asRecord(record);
  const variables = asRecord(row.variables);
  const swarm = asRecord(row.swarm_plan);
  return {
    step_id: String(row.step_id || ""),
    phase_id: String(row.phase_id || ""),
    kind: String(row.kind || ""),
    status: String(row.status || ""),
    isolation_unit_ids: isolationUnitIds(row),
    merge_status: mergeStatusFromRecord(row),
    live_execution: swarm.live_execution === true,
    worker_ids: Array.isArray(swarm.worker_ids) ? swarm.worker_ids.map(String) : [],
    recorded_at: String(row.recorded_at || ""),
    variables,
  };
}

export function buildOrchestrationWorkflowMonitor(rows, workflowId = null) {
  if (!Array.isArray(rows) || !rows.length) return null;

  const deduped = new Map();
  for (const row of rows) {
    const record = asRecord(row);
    if (record.step_id) deduped.set(String(record.step_id), record);
  }
  const steps = [...deduped.values()].map(projectWorkflowStep);
  steps.sort((a, b) => `${a.phase_id}:${a.step_id}`.localeCompare(`${b.phase_id}:${b.step_id}`));

  const completed = steps.filter((step) => step.status === "completed").length;
  const failed = steps.filter((step) => step.status === "failed").length;
  const mergeSteps = steps.filter((step) => step.kind === "merge_checkpoint");
  const lastMerge = mergeSteps.length ? mergeSteps[mergeSteps.length - 1] : null;

  let inferredWorkflowId = workflowId;
  if (!inferredWorkflowId) {
    for (const row of deduped.values()) {
      const swarm = asRecord(row.swarm_plan);
      const parent = String(swarm.task_id || swarm.parent_task_id || "");
      if (parent.includes(":")) {
        inferredWorkflowId = parent.split(":")[0];
        break;
      }
    }
  }

  return {
    schema_version: "0.1.0",
    source: "orchestration_runner_state.jsonl",
    workflow_id: inferredWorkflowId || "unknown",
    step_count: steps.length,
    completed_steps: completed,
    failed_steps: failed,
    resume_checkpoint: lastMerge?.step_id || null,
    merge_status: lastMerge?.merge_status || null,
    steps,
  };
}
