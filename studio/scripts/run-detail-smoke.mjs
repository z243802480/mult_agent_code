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
  const detail = await fetchJson(`http://127.0.0.1:${port}/api/runs/${runId}`);
  for (const key of ["run_loop_summary", "final_report_summary", "model_route_timeline", "goal_policy"]) {
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


