/**
 * S71 Thread workflow compact card smoke — run detail with orchestration_workflow renders summary fields.
 */
import assert from "node:assert/strict";
import { buildOrchestrationWorkflowMonitor } from "../lib/orchestration-workflow-monitor.mjs";

const rows = [
  {
    step_id: "adversarial-review",
    phase_id: "verify",
    kind: "adversarial_review",
    status: "completed",
    recorded_at: "2026-06-07T12:00:00+08:00",
    variables: { verifier_passed: true, adversarial_ok: true },
    swarm_plan: { verifier_status: "passed", live_execution: true },
  },
  {
    step_id: "merge-checkpoint",
    phase_id: "merge",
    kind: "merge_checkpoint",
    status: "completed",
    recorded_at: "2026-06-07T12:01:00+08:00",
    variables: { merge_gate_ok: true, verifier_gate_ok: true },
    swarm_plan: {},
  },
];

const monitor = buildOrchestrationWorkflowMonitor(rows, "s69-verifier-probe");
assert.ok(monitor, "monitor should be built");
assert.equal(monitor.workflow_id, "s69-verifier-probe");
assert.equal(monitor.step_count, 2);
assert.equal(monitor.completed_steps, 2);
assert.equal(monitor.merge_status, "passed");
assert.equal(monitor.verifier_status, "passed");
assert.equal(monitor.resume_checkpoint, "merge-checkpoint");

const steps = monitor.steps;
const verifyStep = steps.find((step) => step.kind === "adversarial_review");
const mergeStep = steps.find((step) => step.kind === "merge_checkpoint");
assert.equal(verifyStep?.verifier_status, "passed");
assert.equal(mergeStep?.merge_status, "passed");

console.log(JSON.stringify({ ok: true, monitor }, null, 2));
