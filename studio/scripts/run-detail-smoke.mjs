import { spawn } from "node:child_process";
import { promises as fs } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const studioDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const workspace = await fs.mkdtemp(path.join(os.tmpdir(), "asteria-studio-smoke-"));
const runId = "run-20990101-0001";
const runDir = path.join(workspace, ".asteria", "runs", runId);
await fs.mkdir(runDir, { recursive: true });
await fs.mkdir(path.join(workspace, ".asteria", "evidence_bundles"), { recursive: true });

await writeJson("run.json", {
  run_id: runId,
  goal: "Smoke-test Studio run detail payload",
  status: "reviewed",
  current_phase: "review",
});
await writeJson("run_loop_summary.json", {
  iteration_count: 1,
  stop_reason: "review_passed",
  latest_evidence_pointer: "final_report.md",
  workflow_state: "review_passed",
  current_blocker: "none",
  recommended_next_command: "asteria accept --latest",
});
await writeJson("agent_loop_run_summary.json", {
  schema_version: "0.1.0",
  run_id: runId,
  task_id: "task-0001",
  created_at: "2099-01-01T00:00:00Z",
  status: "blocked",
  exit_reason: "max_rounds",
  rounds_completed: 2,
  max_rounds: 2,
  summary: "Loop stopped after reaching max rounds.",
  recommended_command: "status --debug",
  latest_decision_id: "loop-decision-0001",
  latest_execution_id: "loop-execution-0001",
  latest_observation_id: "loop-observation-0001",
  latest_action: "replan",
  evidence_refs: ["agent_loop_decisions.jsonl"],
});
await writeJson("final_report_summary.json", {
  workflow_state: "review_passed",
  current_blocker: "none",
  recommended_next_command: "asteria accept --latest",
  model_route_timeline_path: ".asteria/runs/run-20990101-0001/model_route_timeline.json",
});
await writeJson("model_route_timeline.json", {
  route_timeline: [
    {
      purpose: "goal_loop",
      selected_tier: "medium",
      reason: "Smoke test route rationale",
      capability_feedback: "sufficient",
    },
  ],
});
await writeJson("goal_policy.json", {
  category: "none",
  reason: "No policy blocker in smoke fixture",
  recommended_action: "accept",
});
await writeJson("cost_report.json", { total_model_calls: 1 });
await writeJson("agent_run_graph.json", {
  schema_version: "0.1.0",
  agent_run_graph_id: "graph-0001",
  run_id: runId,
  status: "blocked",
  coordination_modes: ["readonly_batch_selection"],
  max_concurrency_observed: 2,
  child_worker_plans: [],
  collaboration_summary: {
    total_workers: 2,
    successful_workers: 1,
    failed_workers: 1,
    blocked_workers: 0,
    total_model_calls: 2,
    total_tool_calls: 1,
    artifact_refs: ["artifact.md"],
    validation_refs: ["validation.json"],
    failure_evidence_refs: ["failure.json"],
    merge_strategy: "review_promote",
    collaboration_protocol: {
      isolation_model: "candidate_workspace",
      review_agent_role: "review",
      debug_agent_role: "repair",
      merge_gate_role: "validate",
      promotion_queue_role: "promote",
    },
    strategy_modes: ["readonly_fanout"],
    next_actions: ["Inspect failed worker evidence."],
  },
  updated_at: "2099-01-01T00:00:00Z",
});
await writeJsonl("workers.jsonl", [
  {
    schema_version: "0.1.0",
    worker_invocation_id: "worker-0001",
    run_id: runId,
    task_id: "task-0001",
    agent_id: "planner",
    runtime_profile_id: "profile-0001",
    status: "succeeded",
    started_at: "2099-01-01T00:00:00Z",
    worker_kind: "planner",
    parallel_safety: "readonly",
    child_plan_refs: ["child-plan-0001"],
  },
  {
    schema_version: "0.1.0",
    worker_invocation_id: "worker-0002",
    run_id: runId,
    task_id: "task-0002",
    agent_id: "readonly-worker",
    runtime_profile_id: "profile-0002",
    status: "failed",
    started_at: "2099-01-01T00:00:01Z",
    parent_worker_invocation_id: "worker-0001",
    parent_task_id: "task-0001",
    worker_kind: "subagent",
    parallel_safety: "readonly_fanout",
    child_plan_refs: ["child-plan-0002"],
  },
]);
await writeJsonl("worker_results.jsonl", [
  {
    schema_version: "0.1.0",
    worker_result_id: "worker-result-0001",
    worker_invocation_id: "worker-0001",
    run_id: runId,
    task_id: "task-0001",
    status: "succeeded",
    artifact_refs: ["artifact.md"],
    validation_refs: ["validation.json"],
    failure_evidence_refs: [],
    cost: { model_calls: 1, tool_calls: 1 },
    summary: "Planner worker succeeded.",
  },
  {
    schema_version: "0.1.0",
    worker_result_id: "worker-result-0002",
    worker_invocation_id: "worker-0002",
    run_id: runId,
    task_id: "task-0002",
    status: "failed",
    artifact_refs: [],
    validation_refs: [],
    failure_evidence_refs: ["failure.json"],
    cost: { model_calls: 1, tool_calls: 0 },
    summary: "Readonly child worker failed for smoke evidence.",
  },
]);
await writeJsonl("user_progress.jsonl", [
  {
    event_id: "upe-0001",
    sequence: 1,
    channel: "progress",
    event_type: "message",
    phase: "review",
    status: "completed",
    title: "Runtime progress",
    summary: "Read from user_progress first.",
    display_level: "main",
    created_at: "2099-01-01T00:00:00Z",
  },
]);
await writeJsonl("events.jsonl", [
  {
    event_id: "evt-legacy",
    type: "phase_changed",
    actor: "Legacy",
    summary: "Legacy event should not be the primary timeline.",
    created_at: "2099-01-01T00:00:00Z",
  },
]);
await writeJsonl("mcp_invocations.jsonl", [
  {
    mcp_invocation_id: "mcp-0001",
    server_name: "docs",
    tool_name: "echo",
    status: "success",
    summary: "MCP echo completed",
  },
]);
await writeJsonl("skill_invocations.jsonl", [
  {
    skill_invocation_id: "skill-0001",
    skill_name: "documents",
    status: "success",
    summary: "Document skill completed",
  },
]);
await fs.writeFile(
  path.join(workspace, ".asteria", "evidence_bundles", "evidence-smoke.manifest.json"),
  `${JSON.stringify({
    v0_2_rolling_validation: {
      status: "needs_evidence",
      sample_count: 3,
      required_sample_count: { min: 3, max: 5 },
      coverage: { route: true, context: true, capability: true, loop: true, worker: false },
      missing_evidence_categories: ["worker"],
      next_actions: ["Collect worker evidence for at least one scoped task."],
    },
  }, null, 2)}\n`,
  "utf8"
);

const port = Number(process.env.ASTERIA_STUDIO_SMOKE_PORT || 18787);
const server = spawn(process.execPath, ["server.mjs", "--workspace", workspace, "--port", String(port)], {
  cwd: studioDir,
  stdio: ["ignore", "pipe", "pipe"],
});

let stdout = "";
let stderr = "";
server.stdout.on("data", (chunk) => { stdout += String(chunk); });
server.stderr.on("data", (chunk) => { stderr += String(chunk); });

try {
  await waitForHealth(port);
  const overview = await fetchJson(`http://127.0.0.1:${port}/api/overview`);
  if (!Array.isArray(overview.runs) || !overview.runs.some((run) => run.run_id === runId)) {
    throw new Error("/api/overview did not list the smoke run");
  }
  if (overview.v0_2_rolling_validation?.status !== "needs_evidence") {
    throw new Error("/api/overview did not expose v0_2_rolling_validation");
  }
  const detail = await fetchJson(`http://127.0.0.1:${port}/api/runs/${runId}`);
  for (const key of ["agent_loop_run_summary", "run_loop_summary", "final_report_summary", "model_route_timeline", "goal_policy", "worker_tree"]) {
    if (!Object.prototype.hasOwnProperty.call(detail, key)) {
      throw new Error(`/api/runs/:id missing ${key}`);
    }
    if (!detail[key] || typeof detail[key] !== "object" || Array.isArray(detail[key])) {
      throw new Error(`/api/runs/:id returned invalid ${key}`);
    }
  }
  if (detail.run_loop_summary.workflow_state !== "review_passed") {
    throw new Error("run_loop_summary content was not returned correctly");
  }
  if (detail.agent_loop_run_summary.exit_reason !== "max_rounds") {
    throw new Error("agent_loop_run_summary content was not returned correctly");
  }
  if (detail.worker_tree.total_workers !== 2 || detail.worker_tree.roots?.[0]?.children?.[0]?.worker_invocation_id !== "worker-0002") {
    throw new Error("worker_tree was not built from worker evidence");
  }
  if (!Array.isArray(detail.model_route_timeline.route_timeline)) {
    throw new Error("model_route_timeline.route_timeline was not returned");
  }
  if (detail.timeline_events_source !== "user_progress") {
    throw new Error("run detail should prefer user_progress.jsonl for timeline events");
  }
  if (!Array.isArray(detail.events) || detail.events[0]?.source !== "runtime_user_progress") {
    throw new Error("run detail events were not mapped from user_progress.jsonl");
  }
  if (!Array.isArray(detail.legacy_events) || detail.legacy_events[0]?.event_id !== "evt-legacy") {
    throw new Error("legacy events should remain available as fallback evidence");
  }
  if (!Array.isArray(detail.mcp_invocations) || detail.mcp_invocations[0]?.mcp_invocation_id !== "mcp-0001") {
    throw new Error("mcp_invocations should be available for Inspector");
  }
  if (!Array.isArray(detail.skill_invocations) || detail.skill_invocations[0]?.skill_invocation_id !== "skill-0001") {
    throw new Error("skill_invocations should be available for Inspector");
  }
  console.log("Studio run detail smoke passed");
} finally {
  server.kill("SIGTERM");
  await new Promise((resolve) => setTimeout(resolve, 200));
  await fs.rm(workspace, { recursive: true, force: true });
}

async function writeJson(name, value) {
  await fs.writeFile(path.join(runDir, name), `${JSON.stringify(value, null, 2)}\n`, "utf8");
}

async function writeJsonl(name, rows) {
  await fs.writeFile(
    path.join(runDir, name),
    `${rows.map((row) => JSON.stringify(row)).join("\n")}\n`,
    "utf8"
  );
}

async function waitForHealth(targetPort) {
  const deadline = Date.now() + 10_000;
  let lastError;
  while (Date.now() < deadline) {
    try {
      const health = await fetchJson(`http://127.0.0.1:${targetPort}/api/health`);
      if (health.ok) return;
    } catch (error) {
      lastError = error;
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(`Studio server did not become healthy. stdout=${stdout} stderr=${stderr} last=${lastError}`);
}

async function fetchJson(url) {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`${url} returned ${response.status}`);
  }
  return response.json();
}


