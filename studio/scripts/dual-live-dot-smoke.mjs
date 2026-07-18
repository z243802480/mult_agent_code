import { spawn } from "node:child_process";
import { promises as fs } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

// Dual live dot (G3 / Wave N1 verification debt): TWO sessions must show run_status "running"
// AT THE SAME TIME in one /api/studio/sessions response — the data condition behind two green
// dots in the sidebar. The projection (decorateSessionRunStatus) and the poll loop were verified
// in isolation in 1.2.83; this closes the missing end-to-end: real BFF, two real chat jobs.
//
// Chat mode on purpose: since S87, two WRITER runs in one workspace are refused by design
// (run-conflict.mjs), so read-only chat is the only legitimate dual-running combination left —
// which is exactly what this smoke pins down.

const studioDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const workspace = await fs.mkdtemp(path.join(os.tmpdir(), "asteria-studio-dual-dot-"));
const port = Number(process.env.ASTERIA_STUDIO_DUAL_DOT_PORT || 18830);

await fs.mkdir(path.join(workspace, ".asteria"), { recursive: true });
await fs.writeFile(
  path.join(workspace, ".asteria", "project.json"),
  JSON.stringify(
    {
      schema_version: "0.1.0",
      project_id: "studio-dual-dot-smoke",
      name: "dual live dot smoke",
      workspace_type: "empty_workspace",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
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
  ),
);
await fs.writeFile(
  path.join(workspace, ".asteria", "policies.json"),
  JSON.stringify(
    {
      schema_version: "0.1.0",
      decision_granularity: "balanced",
      budgets: {
        max_model_calls_per_goal: 10,
        max_tool_calls_per_goal: 10,
        max_total_minutes_per_goal: 5,
        max_iterations_per_goal: 2,
        max_repair_attempts_total: 1,
        max_repair_attempts_per_task: 1,
        max_replans_per_task: 1,
        max_research_calls: 0,
        max_user_decisions: 1,
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
  ),
);

const server = spawn(
  process.execPath,
  ["server.mjs", "--workspace", workspace, "--port", String(port)],
  {
    cwd: studioDir,
    stdio: ["ignore", "pipe", "pipe"],
    env: {
      ...process.env,
      ASTERIA_STUDIO_CHAT_BACKEND: "model",
      AGENT_MODEL_PROVIDER: "fake",
      AGENT_MODEL_MEDIUM_PROVIDER: "fake",
      AGENT_MODEL_CHEAP_PROVIDER: "fake",
      AGENT_MODEL_STRONG_PROVIDER: "fake",
      ASTERIA_HOME: workspace,
      PYTHONPATH: path.resolve(studioDir, "..", "src"),
    },
  },
);

let stdout = "";
let stderr = "";
server.stdout.on("data", (chunk) => {
  stdout += String(chunk);
});
server.stderr.on("data", (chunk) => {
  stderr += String(chunk);
});

try {
  await waitForHealth();

  const a = (await postJson("/api/studio/sessions", {})).session.session_id;
  const b = (await postJson("/api/studio/sessions", {})).session.session_id;
  assert(a && b && a !== b, "expected two distinct sessions");

  // Fire both chat turns back to back so their jobs overlap (a fake-provider chat still spawns a
  // real python subprocess, so each job stays running for a second or two).
  await Promise.all([
    postJson(`/api/studio/sessions/${encodeURIComponent(a)}/messages`, {
      mode: "chat",
      message: "第一个会话的问题：介绍一下这个项目",
    }),
    postJson(`/api/studio/sessions/${encodeURIComponent(b)}/messages`, {
      mode: "chat",
      message: "第二个会话的问题：介绍一下这个项目",
    }),
  ]);

  // The dual-dot condition: ONE list response where BOTH sessions project run_status running.
  const runStatusOf = (payload, sid) =>
    (payload.sessions || []).find((s) => s.session_id === sid)?.run_status;
  let sawBothRunning = false;
  const deadline = Date.now() + 15_000;
  while (Date.now() < deadline) {
    const payload = await fetchJson("/api/studio/sessions");
    if (runStatusOf(payload, a) === "running" && runStatusOf(payload, b) === "running") {
      sawBothRunning = true;
      break;
    }
    if (server.exitCode !== null) {
      throw new Error(`Studio server exited early. stdout=${stdout} stderr=${stderr}`);
    }
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  assert(
    sawBothRunning,
    `never observed both sessions running in one response. stdout=${stdout} stderr=${stderr}`,
  );

  // Not a stale read: both jobs finish and the projection follows them out of "running".
  const settleDeadline = Date.now() + 20_000;
  let finalA;
  let finalB;
  while (Date.now() < settleDeadline) {
    const payload = await fetchJson("/api/studio/sessions");
    finalA = runStatusOf(payload, a);
    finalB = runStatusOf(payload, b);
    if (finalA !== "running" && finalB !== "running") break;
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  assert(
    finalA === "completed" && finalB === "completed",
    `expected both chat jobs to complete, got a=${finalA} b=${finalB}. stderr=${stderr}`,
  );

  console.log("Dual live dot smoke passed");
} finally {
  server.kill("SIGTERM");
  await new Promise((resolve) => setTimeout(resolve, 200));
  await fs.rm(workspace, { recursive: true, force: true });
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

async function waitForHealth() {
  const deadline = Date.now() + 10_000;
  let lastError;
  while (Date.now() < deadline) {
    try {
      const health = await fetchJson("/api/health");
      if (health.ok) return;
    } catch (error) {
      lastError = error;
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(
    `Studio server did not become healthy. stdout=${stdout} stderr=${stderr} last=${lastError}`,
  );
}

async function fetchJson(route) {
  const response = await fetch(`http://127.0.0.1:${port}${route}`);
  if (!response.ok)
    throw new Error(`${route} returned ${response.status}: ${await response.text()}`);
  return response.json();
}

async function postJson(route, body) {
  const response = await fetch(`http://127.0.0.1:${port}${route}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw new Error(`${route} returned ${response.status}: ${await response.text()}`);
  }
  return response.json();
}
