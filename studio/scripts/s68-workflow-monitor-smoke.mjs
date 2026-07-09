#!/usr/bin/env node
/**
 * S68 workflow monitor smoke — run detail exposes orchestration_workflow from runner JSONL.
 *
 *   node studio/scripts/s68-workflow-monitor-smoke.mjs
 */

import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  buildOrchestrationWorkflowMonitor,
  projectWorkflowStep,
} from "../lib/orchestration-workflow-monitor.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "../..");

async function writeJsonl(filePath, rows) {
  await fs.mkdir(path.dirname(filePath), { recursive: true });
  await fs.writeFile(filePath, rows.map((row) => JSON.stringify(row)).join("\n") + "\n", "utf8");
}

const workspace = await fs.mkdtemp(path.join(os.tmpdir(), "asteria-s68-workflow-"));
const runId = "run-s68-workflow-smoke";
const runDir = path.join(workspace, ".asteria", "runs", runId);
await fs.mkdir(runDir, { recursive: true });

const rows = [
  {
    step_id: "readonly-live",
    phase_id: "explore",
    kind: "readonly_fanout",
    status: "completed",
    variables: { worker_ids: ["worker-0001", "worker-0002"] },
    swarm_plan: { live_execution: true, worker_ids: ["worker-0001", "worker-0002"] },
    recorded_at: "2026-06-07T12:00:00+08:00",
  },
  {
    step_id: "disjoint-live",
    phase_id: "write",
    kind: "disjoint_write_fanout",
    status: "completed",
    variables: {
      merge_gate_ok: true,
      isolation_unit_ids: ["export-001", "export-002"],
      worker_ids: ["worker-0003", "worker-0004"],
    },
    swarm_plan: { live_execution: true, merge_status: "passed" },
    recorded_at: "2026-06-07T12:01:00+08:00",
  },
  {
    step_id: "merge-checkpoint",
    phase_id: "merge",
    kind: "merge_checkpoint",
    status: "completed",
    variables: { merge_gate_ok: true, workers_jsonl_present: true },
    recorded_at: "2026-06-07T12:02:00+08:00",
  },
];

await writeJsonl(path.join(runDir, "orchestration_runner_state.jsonl"), rows);

const step = projectWorkflowStep(rows[1]);
if (step.merge_status !== "passed" || step.isolation_unit_ids.length !== 2) {
  throw new Error("projectWorkflowStep failed for disjoint step");
}

const monitor = buildOrchestrationWorkflowMonitor(rows, "wave7-l3-live-probe");
if (!monitor || monitor.step_count !== 3) {
  throw new Error("buildOrchestrationWorkflowMonitor should expose 3 steps");
}
if (monitor.merge_status !== "passed" || monitor.resume_checkpoint !== "merge-checkpoint") {
  throw new Error("workflow monitor merge checkpoint projection failed");
}

console.log(JSON.stringify({ ok: true, workspace, runId, monitor }, null, 2));
