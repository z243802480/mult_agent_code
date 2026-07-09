import { spawn } from "node:child_process";
import { promises as fs } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const studioDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const workspace = await fs.mkdtemp(path.join(os.tmpdir(), "asteria-studio-chat-lifecycle-"));
const port = Number(process.env.ASTERIA_STUDIO_CHAT_LIFECYCLE_PORT || 18789);

await fs.mkdir(path.join(workspace, ".asteria"), { recursive: true });
await fs.writeFile(
  path.join(workspace, ".asteria", "project.json"),
  JSON.stringify(
    {
      schema_version: "0.1.0",
      project_id: "studio-chat-lifecycle-smoke",
      name: "chat lifecycle smoke",
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
  const session = await postJson("/api/studio/sessions", {});
  const sessionId = session.session.session_id;
  const message = "如何去新疆旅游";

  await postJson(`/api/studio/sessions/${encodeURIComponent(sessionId)}/messages`, {
    mode: "auto",
    permission: "ask",
    message,
  });

  const { events } = await fetchEventsUntil(
    sessionId,
    (items) =>
      items.some((event) => event.type === "model_start" && event.status === "running") &&
      items.some((event) => event.type === "final_answer" && event.phase === "chat"),
  );

  const user = events.find((event) => event.type === "user_message");
  assert(
    user?.content_delta === message,
    `expected Chinese user message to round-trip, got ${user?.content_delta}`,
  );

  const modelStart = events.find(
    (event) =>
      event.type === "model_start" &&
      event.phase === "chat" &&
      String(event.event_id || "").startsWith("evt-model-"),
  );
  assert(Boolean(modelStart), "expected chat model_start lifecycle event");
  assert(modelStart.status === "running", `expected model_start running, got ${modelStart.status}`);

  const delta = events.find(
    (event) =>
      event.type === "model_delta" &&
      event.phase === "chat" &&
      event.parent_event_id === modelStart.event_id,
  );
  assert(Boolean(delta), "expected streaming model_delta linked to model_start");

  const completion = events.find(
    (event) =>
      event.type === "model_end" &&
      event.phase === "chat" &&
      event.status === "completed" &&
      event.parent_event_id === modelStart.event_id,
  );
  assert(Boolean(completion), "expected completed model_end linked to model_start");

  const finalAnswer = events.find(
    (event) => event.type === "final_answer" && event.phase === "chat",
  );
  assert(Boolean(finalAnswer), "expected final chat answer");
  const answerText = String(finalAnswer.content_delta || "");
  assert(
    !/Context refs:|Current session:|Next actions:/i.test(answerText),
    "final answer should not expose CLI context noise",
  );
  assert(
    !/[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/.test(answerText),
    "final answer should not contain control characters",
  );

  console.log("Studio chat lifecycle smoke passed");
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

async function fetchEventsUntil(sessionId, predicate) {
  const route = `/api/studio/sessions/${encodeURIComponent(sessionId)}/events`;
  const deadline = Date.now() + 8_000;
  let latest = { events: [] };
  while (Date.now() < deadline) {
    latest = await fetchJson(route);
    if (predicate(latest.events || [])) return latest;
    if (server.exitCode !== null) {
      throw new Error(`Studio server exited early. stdout=${stdout} stderr=${stderr}`);
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(`Timed out waiting for chat lifecycle events. stdout=${stdout} stderr=${stderr}`);
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
