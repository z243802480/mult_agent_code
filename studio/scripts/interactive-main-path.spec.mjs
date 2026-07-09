import { spawn } from "node:child_process";
import { promises as fs } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";

const studioDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const port = Number(process.env.ASTERIA_STUDIO_INTERACTIVE_PORT || 18794);
const runId = "run-20990101-0002";

let workspace;
let runDir;
let server;

test.beforeEach(async () => {
  workspace = await fs.mkdtemp(path.join(os.tmpdir(), "asteria-studio-interactive-"));
  runDir = path.join(workspace, ".asteria", "runs", runId);
  await fs.mkdir(runDir, { recursive: true });
  await fs.mkdir(path.join(workspace, ".asteria", "evidence_bundles"), { recursive: true });
  await writeWorkspaceConfig();
  await writeFixture();

  server = spawn(
    process.execPath,
    ["server.mjs", "--workspace", workspace, "--port", String(port)],
    {
      cwd: studioDir,
      stdio: ["ignore", "pipe", "pipe"],
      env: { ...process.env, ASTERIA_STUDIO_CHAT_BACKEND: "local" },
    },
  );
  await waitForHealth();
});

test.afterEach(async () => {
  server?.kill("SIGTERM");
  await new Promise((resolve) => setTimeout(resolve, 200));
  if (process.env.KEEP_INTERACTIVE_WORKSPACE) {
    console.log(`Keeping interactive smoke workspace: ${workspace}`);
    return;
  }
  if (workspace) await fs.rm(workspace, { recursive: true, force: true });
});

test("Studio main path resolves decisions and allows confirmed next action", async ({ page }) => {
  await driveToPermissionRequest(page);
  await page.locator(".permissionAllow").click();
  await expect(page.locator(".permissionCard.resolved.allow")).toBeVisible({ timeout: 10_000 });
});

test("Studio main path can cancel a gated next action", async ({ page }) => {
  await driveToPermissionRequest(page);
  await page.locator(".permissionDeny").click();
  await expect(page.locator(".permissionCard.resolved.deny")).toBeVisible({ timeout: 10_000 });
});

test("Studio composer exposes product slash actions", async ({ page }) => {
  await page.goto(`http://127.0.0.1:${port}/`);
  await page.locator(".composer textarea").fill("/");
  await expect(page.locator(".slashMenu", { hasText: "Plan" })).toBeVisible();
  await expect(page.locator(".slashMenu", { hasText: "Goal" })).toBeVisible();
  await page.locator(".slashMenu button").filter({ hasText: "Plan" }).click();
  await expect(page.locator(".composerModeSummary", { hasText: "Plan" })).toBeVisible();
  await expect(page.locator(".composer textarea")).toHaveValue(/Create a plan for/);
});

async function driveToPermissionRequest(page) {
  await page.goto(`http://127.0.0.1:${port}/`);

  await expect(
    page.locator(".conversationTurn", { hasText: "Smoke-test Studio interactive path" }),
  ).toBeVisible();
  await expect(page.locator(".workflowMonitorCompact")).toHaveCount(0);
  await expect(page.locator(".threadProcessControls")).toHaveCount(0);
  await expect(page.locator(".runtimeLoopSignals")).toHaveCount(0);
  await expect(
    page.locator(".runtimeSnapshot", { hasText: "1 decision need your input." }),
  ).toBeVisible();
  const actionFollowsTurn = await page.evaluate(() => {
    const turn = document.querySelector(".conversationTurn");
    const action = document.querySelector(".runtimeSnapshot");
    return Boolean(
      turn && action && turn.compareDocumentPosition(action) & Node.DOCUMENT_POSITION_FOLLOWING,
    );
  });
  expect(actionFollowsTurn).toBe(true);
  await expect(page.getByText("Choose the next Studio path.")).toBeVisible();
  await expect(
    page.locator(".decisionOptions button").filter({ hasText: "Continue" }),
  ).toBeVisible();

  await page.locator(".decisionOptions button").filter({ hasText: "Continue" }).click();
  await expect(page.getByText(/Decision action: resolve|Decision action/i)).toBeVisible({
    timeout: 20_000,
  });
  await expect(page.locator(".runtimeActionButton").filter({ hasText: "Accept" })).toBeVisible({
    timeout: 20_000,
  });
  await expect(
    page.locator(".runtimeActionButton").filter({ hasText: "Review changes" }),
  ).toBeVisible();

  await page.getByTitle(/Hide side panel/).click();
  await expect(page.locator(".appShell.panelCollapsed")).toBeVisible();
  await page.locator(".runtimeActionButton").filter({ hasText: "Review changes" }).click();
  await expect(page.locator(".appShell.panelOpen")).toBeVisible();
  await expect(page.locator(".diffReviewPane", { hasText: "Diff review" })).toBeVisible();

  const actionResponse = page.waitForResponse(
    (response) =>
      response.url().includes("/runtime-actions") && response.request().method() === "POST",
  );
  await page.locator(".runtimeActionButton").filter({ hasText: "Accept" }).click();
  await actionResponse;
  await expect(page.locator(".permissionCard")).toBeVisible({ timeout: 10_000 });
  await expect(
    page.locator(".permissionPreview", { hasText: "Accept the reviewed result" }),
  ).toBeVisible();
  await expect(
    page.locator(".permissionPreview", { hasText: "No network access requested." }),
  ).toBeVisible();
  await expect(page.locator(".permissionPreview", { hasText: "Risk · low" })).toBeVisible();
  await expect(page.locator(".permissionAllow")).toBeVisible();
  await expect(page.locator(".permissionDeny")).toBeVisible();
}

async function writeFixture() {
  await writeJson("run.json", {
    run_id: runId,
    goal: "Smoke-test Studio interactive path",
    status: "reviewed",
    current_phase: "review",
  });
  await writeJson("goal_spec.json", {
    normalized_goal: "Smoke-test Studio interactive path",
    original_goal: "Smoke-test Studio interactive path",
  });
  const runtimeProgress = {
    schema_version: "0.1.0",
    workflow_state: "review_passed",
    path: "Plan/Todo -> Tool Use -> Verify -> Next step",
    active_stage: "verify",
    current_step: "Review passed; accept when ready.",
    next_command: "asteria accept --latest",
    current_blocker: null,
    permission_boundary: "reviewed_auto",
    todo: {
      current: {
        id: "task-0001",
        content: "Smoke-test Studio interactive path",
        status: "completed",
      },
      summary: "All 1 todo item(s) are complete and verified.",
      counts: { total: 1, completed: 1 },
    },
    tool_use: { target_task_id: "task-0001", status: "done", summary: "Smoke evidence recorded." },
    verification: { status: "passed", summary: "Smoke validation passed." },
    loop: {
      exit_reason: "review_passed",
      recommended_command: "asteria accept --latest",
      rounds: 1,
      rounds_completed: 1,
      max_rounds: 2,
      recovery: {
        required: true,
        satisfied: true,
        reason: "Loop exit is covered by `stop` recovery semantics.",
        latest_action: "stop",
        observation_status: "succeeded",
        observation_next_recommended_action: "stop",
      },
      budget: {
        status: "within_budget",
        highest_label: "model_calls",
        highest_ratio: 0.1,
        model_calls: 1,
        tool_budget_units: 1,
        repair_attempts: 0,
      },
      context_pressure: {
        status: "within_budget",
        context_window_ratio: 0.24,
        latest_context_estimated_tokens: 48_000,
        max_context_estimated_tokens: 48_000,
        context_compactions: 0,
      },
    },
    evidence_refs: ["run_loop_summary.json", "final_report_summary.json"],
  };
  await writeJson("run_loop_summary.json", {
    schema_version: "0.1.0",
    run_id: runId,
    iteration_count: 1,
    stop_reason: "review_passed",
    workflow_state: "review_passed",
    current_blocker: null,
    recommended_next_command: "asteria accept --latest",
    runtime_progress: runtimeProgress,
  });
  await writeJson("final_report_summary.json", {
    schema_version: "0.1.0",
    workflow_state: "review_passed",
    current_blocker: null,
    recommended_next_command: "asteria accept --latest",
    runtime_progress: runtimeProgress,
  });
  await writeJson("cost_report.json", costReportFixture());
  await writeJson("agent_loop_run_summary.json", {});
  await writeJson("agent_run_graph.json", {
    schema_version: "0.1.0",
    run_id: runId,
    status: "reviewed",
    collaboration_summary: { total_workers: 1, successful_workers: 1, failed_workers: 0 },
  });
  await writeJsonl("workers.jsonl", [
    {
      schema_version: "0.1.0",
      worker_invocation_id: "worker-0001",
      run_id: runId,
      task_id: "task-0001",
      agent_id: "review-worker",
      runtime_profile_id: "profile-0001",
      status: "succeeded",
      worker_kind: "review",
      parallel_safety: "readonly",
      started_at: "2099-01-01T00:00:00Z",
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
      summary: "Worker completed.",
      artifact_refs: [],
      validation_refs: [],
      failure_evidence_refs: [],
      cost: { model_calls: 0, tool_calls: 1 },
    },
  ]);
  await writeJsonl("decisions.jsonl", [
    {
      schema_version: "0.1.0",
      decision_id: "decision-0001",
      status: "pending",
      question: "Choose the next Studio path.",
      recommended_option_id: "continue",
      options: [
        {
          option_id: "continue",
          label: "Continue",
          tradeoff: "Resolve and continue to acceptance.",
          action: "create_task",
        },
        {
          option_id: "stop",
          label: "Stop",
          tradeoff: "Keep the reviewed result as-is.",
          action: "record_constraint",
        },
      ],
      default_option_id: "continue",
      impact: { scope: "low", budget: "low", risk: "low", quality: "medium" },
      selected_option_id: null,
      created_at: "2099-01-01T00:00:00Z",
      metadata: {},
      resolved_at: null,
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
      summary: "Interactive smoke progress.",
      transcript_kind: "verification",
      ui_intent: "work_progress",
      actions: [],
      evidence_refs: ["run_loop_summary.json"],
      display_level: "main",
      created_at: "2099-01-01T00:00:00Z",
    },
  ]);
}

async function writeWorkspaceConfig() {
  const agentDir = path.join(workspace, ".asteria");
  await fs.writeFile(
    path.join(agentDir, "project.json"),
    `${JSON.stringify(
      {
        schema_version: "0.1.0",
        project_id: "studio-interactive-main-path-smoke",
        name: "Studio interactive main path smoke",
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
      },
      null,
      2,
    )}\n`,
    "utf8",
  );
  await fs.writeFile(
    path.join(agentDir, "policies.json"),
    `${JSON.stringify(
      {
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
      },
      null,
      2,
    )}\n`,
    "utf8",
  );
}

async function writeJson(name, value) {
  await fs.writeFile(path.join(runDir, name), `${JSON.stringify(value, null, 2)}\n`, "utf8");
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
    latest_context_estimated_tokens: 48_000,
    max_context_estimated_tokens: 48_000,
    context_window_tokens: 200_000,
    context_window_ratio: 0.24,
    context_pressure_status: "within_budget",
    latest_context_sections: {
      messages: 16_000,
      system_tools: 10_000,
      project_rules: 6_000,
      memory: 4_000,
      tool_output: 12_000,
    },
    user_decisions: 0,
    status: "within_budget",
    warnings: [],
  };
}

async function writeJsonl(name, rows) {
  await fs.writeFile(
    path.join(runDir, name),
    `${rows.map((row) => JSON.stringify(row)).join("\n")}\n`,
    "utf8",
  );
}

async function waitForHealth() {
  const deadline = Date.now() + 10_000;
  let stderr = "";
  server.stderr.on("data", (chunk) => {
    stderr += String(chunk);
  });
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`http://127.0.0.1:${port}/api/health`);
      const health = await response.json();
      if (health.ok) return;
    } catch {}
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(`Studio server did not become healthy. stderr=${stderr}`);
}
