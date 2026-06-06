import { spawn } from "node:child_process";
import { promises as fs } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const studioDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const workspace = await fs.mkdtemp(path.join(os.tmpdir(), "asteria-s20-smoke-"));
const runId = "run-20990102-0001";
const runDir = path.join(workspace, ".asteria", "runs", runId);
await fs.mkdir(runDir, { recursive: true });
await writeWorkspaceConfig();

await writeJson("run.json", {
  run_id: runId,
  goal: "Smoke-test worker progress and promotion preview",
  status: "running",
  current_phase: "execute",
});
await writeJson("run_loop_summary.json", {
  iteration_count: 1,
  stop_reason: "workers_in_progress",
  workflow_state: "running",
  runtime_progress: {
    schema_version: "0.1.0",
    workflow_state: "running",
    path: "Plan/Todo -> Tool Use -> Verify -> Next step",
    active_stage: "execute",
    current_step: "Background tasks running.",
    next_command: "asteria status",
    permission_boundary: "reviewed_auto",
  },
});
await writeJson("agent_run_graph.json", {
  schema_version: "0.1.0",
  run_id: runId,
  status: "running",
  coordination_modes: ["parallel_safe_batch_selection"],
  collaboration_summary: { total_workers: 2, successful_workers: 1, failed_workers: 0 },
});
await writeJsonl("workers.jsonl", [
  {
    schema_version: "0.1.0",
    worker_invocation_id: "worker-0001",
    run_id: runId,
    task_id: "task-0001",
    agent_id: "CoderAgent",
    runtime_profile_id: "runtime-profile-0001",
    execution_profile_id: "harness",
    spawn_kind: "harness_write",
    fake_path: true,
    status: "succeeded",
    started_at: "2099-01-02T00:00:00Z",
    parallel_safety: "disjoint_writes",
    worker_kind: "implementation_child",
  },
  {
    schema_version: "0.1.0",
    worker_invocation_id: "worker-0002",
    run_id: runId,
    task_id: "task-0002",
    agent_id: "CoderAgent",
    runtime_profile_id: "runtime-profile-0002",
    execution_profile_id: "harness",
    spawn_kind: "harness_write",
    fake_path: true,
    status: "running",
    started_at: "2099-01-02T00:00:01Z",
    parent_worker_invocation_id: "worker-0001",
    parallel_safety: "disjoint_writes",
    worker_kind: "implementation_child",
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
    summary: "Alpha worker done.",
    cost: { model_calls: 1, tool_calls: 2 },
  },
  {
    schema_version: "0.1.0",
    worker_result_id: "worker-result-0002",
    worker_invocation_id: "worker-0002",
    run_id: runId,
    task_id: "task-0002",
    status: "running",
    summary: "Beta worker in progress.",
    cost: { model_calls: 0, tool_calls: 0 },
  },
]);
await writeJsonl("candidate_exports.jsonl", [
  {
    schema_version: "0.1.0",
    candidate_export_id: "candidate-export-0001",
    run_id: runId,
    task_id: "task-0001",
    candidate_id: "candidate-smoke-1",
    workspace: path.join(runDir, "cw", "smoke1"),
    changed_files: ["out/alpha.txt"],
    write_scope: ["out/alpha.txt"],
    execution_profile_id: "harness",
    export_status: "ready",
    spawn_kind: "harness_write",
    created_at: "2099-01-02T00:00:05Z",
  },
]);
await writeJsonl("merge_gate_dry_runs.jsonl", [
  {
    schema_version: "0.1.0",
    merge_gate_dry_run_id: "merge-gate-dry-run-0001",
    run_id: runId,
    dry_run: true,
    ok: true,
    task_results: [{ task_id: "task-0001", merge_gate: { ok: true, promotable_files: ["out/alpha.txt"], violations: [] } }],
    disjoint_write_gate: { ok: true, violations: [] },
    batch_violations: [],
    summary: "Merge gate dry-run passed.",
    created_at: "2099-01-02T00:00:06Z",
  },
]);
await writeJsonl("candidate_promotions.jsonl", [
  {
    schema_version: "0.1.0",
    promotion_id: "promotion-0001",
    run_id: runId,
    task_id: "task-0001",
    candidate_id: "candidate-smoke-1",
    workspace: path.join(runDir, "cw", "smoke1"),
    strategy: "temp_workspace",
    workspace_policy: "isolated_copy",
    backend_reason: "smoke",
    promotable_files: ["out/alpha.txt"],
    promoted_files: [],
    status: "pending_manual_approval",
    approval_mode: "manual",
    merge_gate: { ok: true, promotable_files: ["out/alpha.txt"], violations: [] },
    created_at: "2099-01-02T00:00:07Z",
    updated_at: "2099-01-02T00:00:07Z",
  },
]);

const port = Number(process.env.ASTERIA_STUDIO_SMOKE_PORT || 18788);
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
  const detail = await fetchJson(`http://127.0.0.1:${port}/api/runs/${runId}`);
  if (!detail.promotion_preview || detail.promotion_preview.export_count !== 1) {
    throw new Error("promotion_preview missing or invalid");
  }
  if (detail.promotion_preview.merge_preview_status !== "ready") {
    throw new Error(`expected merge_preview_status ready, got ${detail.promotion_preview.merge_preview_status}`);
  }
  if (!String(detail.promotion_preview.merge_preview_summary).includes("Merge preview")) {
    throw new Error("merge preview summary should use user-facing wording");
  }
  if (detail.promotion_preview.pending_promotions !== 1) {
    throw new Error("expected one pending promotion");
  }
  if (!Array.isArray(detail.candidate_exports) || detail.candidate_exports.length !== 1) {
    throw new Error("candidate_exports not exposed");
  }
  const workerSummary = detail.runtime_progress?.worker_summary;
  if (!workerSummary || workerSummary.total !== 2) {
    throw new Error("worker_summary not enriched on runtime_progress");
  }
  if (workerSummary.progress_percent !== 50) {
    throw new Error(`expected progress_percent 50, got ${workerSummary.progress_percent}`);
  }
  if (!Array.isArray(workerSummary.workers) || workerSummary.workers.length !== 2) {
    throw new Error("worker_summary.workers not populated");
  }
  if (!String(workerSummary.promotion_hint).includes("waiting for your review")) {
    throw new Error("worker_summary.promotion_hint missing");
  }
  if (detail.worker_tree.roots?.[0]?.execution_profile_id !== "harness") {
    throw new Error("worker_tree should expose execution_profile_id");
  }
  console.log("Studio S20 worker promotion smoke passed");
} finally {
  server.kill("SIGTERM");
  await new Promise((resolve) => setTimeout(resolve, 200));
  await fs.rm(workspace, { recursive: true, force: true });
}

async function writeJson(name, value) {
  await fs.writeFile(path.join(runDir, name), `${JSON.stringify(value, null, 2)}\n`, "utf8");
}

async function writeJsonl(name, rows) {
  await fs.writeFile(path.join(runDir, name), `${rows.map((row) => JSON.stringify(row)).join("\n")}\n`, "utf8");
}

async function writeWorkspaceConfig() {
  const agentDir = path.join(workspace, ".asteria");
  await fs.mkdir(agentDir, { recursive: true });
  await fs.writeFile(path.join(agentDir, "project.json"), `${JSON.stringify({ schema_version: "0.1.0", project_id: "s20-smoke" }, null, 2)}\n`, "utf8");
  await fs.writeFile(path.join(agentDir, "policies.json"), `${JSON.stringify({ schema_version: "0.1.0", protected_paths: [".git/"] }, null, 2)}\n`, "utf8");
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

async function fetchJson(url, init = undefined) {
  const response = await fetch(url, init);
  if (!response.ok) throw new Error(`${url} returned ${response.status}`);
  return response.json();
}
