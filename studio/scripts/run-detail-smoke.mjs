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
await writeWorkspaceConfig();

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
  runtime_progress: {
    schema_version: "0.1.0",
    workflow_state: "review_passed",
    path: "Plan/Todo -> Tool Use -> Verify -> Next step",
    active_stage: "verify",
    current_step: "Run `asteria accept --latest`.",
    next_command: "asteria accept --latest",
    current_blocker: null,
    permission_boundary: "reviewed_auto",
    todo: {
      current: { id: "task-0001", content: "Smoke-test Studio run detail payload", status: "completed" },
      summary: "All 1 todo item(s) are complete and verified.",
      counts: { total: 1, completed: 1 },
    },
    tool_use: { target_task_id: "task-0001", status: "done", summary: "Smoke evidence recorded." },
    verification: { status: "passed", summary: "Smoke validation passed." },
    loop: { exit_reason: "review_passed", rounds: 1 },
    evidence_refs: ["run_loop_summary.json"],
  },
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
  runtime_progress: {
    schema_version: "0.1.0",
    workflow_state: "review_passed",
    path: "Plan/Todo -> Tool Use -> Verify -> Next step",
    active_stage: "verify",
    current_step: "Run `asteria accept --latest`.",
    next_command: "asteria accept --latest",
    current_blocker: null,
    permission_boundary: "reviewed_auto",
    todo: {
      current: { id: "task-0001", content: "Smoke-test Studio run detail payload", status: "completed" },
      summary: "All 1 todo item(s) are complete and verified.",
      counts: { total: 1, completed: 1 },
    },
    tool_use: { target_task_id: "task-0001", status: "done", summary: "Smoke evidence recorded." },
    verification: { status: "passed", summary: "Smoke validation passed." },
    loop: { exit_reason: "review_passed", rounds: 1 },
    evidence_refs: ["final_report_summary.json"],
  },
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
await writeJson("cost_report.json", costReportFixture());
await writeJsonl("decisions.jsonl", [
  {
    schema_version: "0.1.0",
    decision_id: "decision-0001",
    status: "pending",
    question: "Choose the next Studio smoke path.",
    recommended_option_id: "continue",
    options: [
      { option_id: "continue", label: "Continue", tradeoff: "Resume the runtime path.", action: "create_task" },
      { option_id: "stop", label: "Stop", tradeoff: "Record the current result.", action: "record_constraint" },
    ],
    default_option_id: "continue",
    impact: { scope: "low", budget: "low", risk: "low", quality: "medium" },
    selected_option_id: null,
    created_at: "2099-01-01T00:00:00Z",
    metadata: {
      kind: "runtime_request",
      runtime_request_ids: ["runtime-request-0001"],
    },
    resolved_at: null,
  },
]);
await writeJsonl("runtime_requests.jsonl", [
  {
    schema_version: "0.1.0",
    runtime_request_id: "runtime-request-0001",
    run_id: runId,
    task_id: "task-0001",
    request_type: "scope_expansion",
    risk: "medium",
    reason: "Need to update the scoped smoke files.",
    details: {
      read_scope: ["src/current.py"],
      write_scope: ["src/new.py", "tests/test_new.py"],
    },
    status: "decision_created",
    decision_id: "decision-0001",
    created_at: "2099-01-01T00:00:00Z",
  },
]);
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
    title: "Progress",
    summary: "Read from user_progress first.",
    transcript_kind: "verification",
    ui_intent: "work_progress",
    actions: [],
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
  if (overview.diagnostics_loaded !== false) {
    throw new Error("/api/overview should be lightweight and mark diagnostics_loaded=false");
  }
  const diagnostics = await fetchJson(`http://127.0.0.1:${port}/api/diagnostics`);
  if (diagnostics.diagnostics_loaded !== true) {
    throw new Error("/api/diagnostics should mark diagnostics_loaded=true");
  }
  const detail = await fetchJson(`http://127.0.0.1:${port}/api/runs/${runId}`);
  for (const key of ["agent_loop_run_summary", "run_loop_summary", "runtime_progress", "main_action", "final_report_summary", "model_route_timeline", "goal_policy", "worker_tree"]) {
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
  if (detail.runtime_progress?.active_stage !== "verify" || detail.runtime_progress?.todo?.counts?.completed !== 1) {
    throw new Error("/api/runs/:id did not expose final summary runtime_progress");
  }
  if (!Array.isArray(detail.decision_requests) || detail.decision_requests[0]?.decision_id !== "decision-0001") {
    throw new Error("/api/runs/:id did not expose pending decision requests");
  }
  if (detail.decision_requests[0]?.metadata?.permission_preview?.scope !== "Read: src/current.py; Write: src/new.py, tests/test_new.py") {
    throw new Error("/api/runs/:id did not enrich runtime request decisions with exact permission scope");
  }
  if (detail.runtime_requests?.[0]?.runtime_request_id !== "runtime-request-0001") {
    throw new Error("/api/runs/:id did not keep runtime requests available for Inspector");
  }
  if (detail.main_action?.kind !== "decide" || detail.main_action?.decision_count !== 1) {
    throw new Error("/api/runs/:id did not expose a decision-backed main_action");
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
  const sessionCreate = await fetchJson(`http://127.0.0.1:${port}/api/studio/sessions`, { method: "POST" });
  const sessionId = sessionCreate.session?.session_id;
  if (!sessionId) throw new Error("Studio session was not created for runtime action smoke");
  const actionResult = await fetchJson(`http://127.0.0.1:${port}/api/studio/sessions/${sessionId}/runtime-actions`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ next_action: "asteria accept --latest", permission: "ask" }),
  });
  if (!actionResult.ok || actionResult.needs_permission !== true || actionResult.action !== "accept") {
    throw new Error("Accept action should become a permission request");
  }
  const actionEvents = await fetchJson(`http://127.0.0.1:${port}/api/studio/sessions/${sessionId}/events`);
  if (!actionEvents.events?.some((event) => event.type === "permission_request" && event.job_id === actionResult.job_id)) {
    throw new Error("Runtime action did not write a permission request event");
  }
  const rejected = await fetchJson(`http://127.0.0.1:${port}/api/studio/sessions/${sessionId}/runtime-actions`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ next_action: "rm -rf ." }),
  });
  if (rejected.ok !== false) {
    throw new Error("Unsupported runtime action should be rejected");
  }
  const resolved = await fetchJson(`http://127.0.0.1:${port}/api/studio/sessions/${sessionId}/decisions/resolve`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ run_id: runId, decision_id: "decision-0001", option_id: "continue" }),
  });
  if (!resolved.ok || resolved.started !== true || resolved.decision_id !== "decision-0001") {
    throw new Error("Decision resolve action should start the controlled runtime path");
  }
  await waitFor(async () => {
    const afterDecision = await fetchJson(`http://127.0.0.1:${port}/api/runs/${runId}`);
    return afterDecision.main_action?.kind === "accept"
      && afterDecision.main_action?.requires_permission === true
      && afterDecision.decision_requests?.length === 0;
  }, "resolved decision did not restore the accept main_action");
  console.log("Studio run detail smoke passed");
} finally {
  server.kill("SIGTERM");
  await new Promise((resolve) => setTimeout(resolve, 200));
  await fs.rm(workspace, { recursive: true, force: true });
}

async function writeJson(name, value) {
  await fs.writeFile(path.join(runDir, name), `${JSON.stringify(value, null, 2)}\n`, "utf8");
}

async function writeWorkspaceConfig() {
  const agentDir = path.join(workspace, ".asteria");
  await fs.writeFile(path.join(agentDir, "project.json"), `${JSON.stringify({
    schema_version: "0.1.0",
    project_id: "studio-run-detail-smoke",
    name: "Studio run detail smoke",
    workspace_type: "empty_workspace",
    created_at: "2099-01-01T00:00:00Z",
    updated_at: "2099-01-01T00:00:00Z",
    languages: [],
    frameworks: [],
    package_managers: [],
    commands: {
      install: null,
      run: null,
      test: null,
      lint: null,
      typecheck: null,
      build: null,
      format: null,
    },
    important_paths: [],
    protected_paths: [".env", "secrets/", ".git/"],
    root_guidance_path: "AGENTS.md",
    default_policy_path: ".asteria/policies.json",
  }, null, 2)}\n`, "utf8");
  await fs.writeFile(path.join(agentDir, "policies.json"), `${JSON.stringify({
    schema_version: "0.1.0",
    decision_granularity: "balanced",
    budgets: {
      max_model_calls_per_goal: 10,
      max_tool_calls_per_goal: 20,
      max_total_minutes_per_goal: 5,
      max_iterations_per_goal: 3,
      max_repair_attempts_total: 1,
      max_repair_attempts_per_task: 1,
      max_replans_per_task: 1,
      max_research_calls: 0,
      max_user_decisions: 3,
    },
    context: {
      compaction_threshold: 0.75,
      hard_stop_threshold: 0.9,
      phase_boundary_compaction: false,
      handoff_compaction: false,
    },
    permissions: {
      allow_network: false,
      allow_shell: false,
      allow_destructive_shell: false,
      allow_global_package_install: false,
      allow_secret_file_read: false,
      allow_remote_push: false,
      allow_deploy: false,
      allow_restore_delete_created_files: false,
    },
    protected_paths: [".env", "secrets/", ".git/"],
    hooks: {
      enabled: false,
      plugins_enabled: false,
      allowed_hook_names: [],
      redacted_data_keys: [],
      handler_timeout_ms: 1000,
    },
    promotion: {
      manual_approval_default: true,
      release_blocking_statuses: [],
      max_pending_release_promotions: 0,
      max_blocked_release_promotions: 0,
    },
    model_routing: {},
    commands: {},
  }, null, 2)}\n`, "utf8");
}

function costReportFixture() {
  return {
    schema_version: "0.1.0",
    run_id: runId,
    model_calls: 0,
    tool_calls: 0,
    estimated_input_tokens: 0,
    estimated_output_tokens: 0,
    strong_model_calls: 0,
    cheap_model_calls: 0,
    repair_attempts: 0,
    research_calls: 0,
    context_compactions: 0,
    user_decisions: 0,
    status: "within_budget",
    warnings: [],
  };
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

async function waitFor(predicate, message) {
  const deadline = Date.now() + 10_000;
  while (Date.now() < deadline) {
    if (await predicate()) return;
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(message);
}

async function fetchJson(url, init = undefined) {
  const response = await fetch(url, init);
  if (!response.ok) {
    throw new Error(`${url} returned ${response.status}`);
  }
  return response.json();
}


