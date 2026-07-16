import { spawn } from "node:child_process";
import { promises as fs } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const studioDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const workspace = await fs.mkdtemp(path.join(os.tmpdir(), "asteria-studio-s8-resume-"));
const port = Number(process.env.ASTERIA_STUDIO_S8_RESUME_PORT || 18815);
const firstRunId = "run-20990101-0001";
const secondRunId = "run-20990101-0002";

await writeContinuationWorkspace();

const server = spawn(
  process.execPath,
  ["server.mjs", "--workspace", workspace, "--port", String(port)],
  {
    cwd: studioDir,
    stdio: ["ignore", "pipe", "pipe"],
    env: { ...process.env, ASTERIA_STUDIO_CHAT_BACKEND: "local" },
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
  const firstDetail = await fetchJson(`/api/runs/${firstRunId}`);
  const secondDetail = await fetchJson(`/api/runs/${secondRunId}`);
  assert(firstDetail.run?.run_id === firstRunId, "first run detail should load");
  assert(secondDetail.run?.run_id === secondRunId, "second run detail should load");
  assert(
    secondDetail.runtime_progress?.plan?.transcript_kind === "plan",
    "continuation run should expose plan runtime_progress",
  );
  assert(
    /续作|补充测试/.test(String(secondDetail.run?.goal || "")),
    "second run goal should reflect continuation wording",
  );

  const sessionCreate = await postJson("/api/studio/sessions", {});
  const sessionId = sessionCreate.session?.session_id;
  assert(sessionId, "Studio session should be created for S8 continuation smoke");

  await postJson(`/api/studio/sessions/${encodeURIComponent(sessionId)}/messages`, {
    mode: "ask",
    permission: "balanced",
    message: "当前 session 的下一步是什么？",
  });

  const { events } = await fetchEventsUntil(sessionId, (items) =>
    items.some((event) => event.type === "final_answer" && event.phase === "chat"),
  );
  const finalAnswer = events.find(
    (event) => event.type === "final_answer" && event.phase === "chat",
  );
  const answerText = String(finalAnswer?.content_delta || "");
  assert(answerText.trim().length > 0, "continuation ask should return a final answer");
  assert(
    !/Temporary local fallback/i.test(answerText),
    "ask should not fall back to generic wrapper",
  );

  console.log("Studio S8 resume continuation smoke passed");
} finally {
  server.kill("SIGTERM");
  await new Promise((resolve) => setTimeout(resolve, 200));
  await fs.rm(workspace, { recursive: true, force: true });
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

async function writeContinuationWorkspace() {
  const asteria = path.join(workspace, ".asteria");
  const firstRunDir = path.join(asteria, "runs", firstRunId);
  const secondRunDir = path.join(asteria, "runs", secondRunId);
  await fs.mkdir(path.join(asteria, "memory"), { recursive: true });
  await fs.mkdir(firstRunDir, { recursive: true });
  await fs.mkdir(secondRunDir, { recursive: true });

  await writeJson(path.join(asteria, "project.json"), {
    schema_version: "0.1.0",
    name: "s8-resume-smoke",
    workspace_type: "software",
    languages: ["python"],
    frameworks: [],
    commands: {},
  });
  await writeJson(path.join(asteria, "current_session.json"), {
    schema_version: "0.1.0",
    session_id: secondRunId,
    reason: "second_goal_selected",
    updated_at: "2099-01-01T00:10:00Z",
  });
  await fs.writeFile(
    path.join(asteria, "memory", "active_goal.md"),
    "# Active goal memory\n\nPrevious goal completed. Continuation focuses on tests and docs.\n",
    "utf8",
  );

  for (const [runId, runDir, goal, step] of [
    [firstRunId, firstRunDir, "第一个目标：本地 CLI 工具", "Plan completed for first goal."],
    [secondRunId, secondRunDir, "续作：补充测试与文档", "Continue with tests and documentation."],
  ]) {
    await writeJson(path.join(runDir, "run.json"), {
      run_id: runId,
      goal,
      status: runId === firstRunId ? "completed" : "running",
      current_phase: runId === firstRunId ? "DONE" : "PLAN",
      summary: goal,
    });
    await writeJson(path.join(runDir, "run_loop_summary.json"), {
      workflow_state: runId === firstRunId ? "ready_for_review" : "planning",
      recommended_next_command: runId === firstRunId ? "review" : "goal",
      runtime_progress: {
        schema_version: "0.1.0",
        workflow_state: runId === firstRunId ? "ready_for_review" : "planning",
        path: "Plan/Todo -> Tool Use -> Verify -> Next step",
        active_stage: "plan",
        current_step: step,
        next_command:
          runId === firstRunId ? "asteria review --latest" : 'asteria goal "续作：补充测试与文档"',
        plan: {
          transcript_kind: "plan",
          title: "制定计划",
          summary: goal,
        },
        todo: {
          current: { id: "task-0001", content: goal, status: "pending" },
          summary: "Continuation planning in progress.",
          counts: { total: 1, completed: 0 },
        },
      },
    });
    await writeJson(path.join(runDir, "final_report_summary.json"), {
      workflow_state: runId === firstRunId ? "ready_for_review" : "planning",
      recommended_next_command: runId === firstRunId ? "review" : "goal",
      runtime_progress: {
        schema_version: "0.1.0",
        workflow_state: runId === firstRunId ? "ready_for_review" : "planning",
        path: "Plan/Todo -> Tool Use -> Verify -> Next step",
        active_stage: "plan",
        current_step: step,
        next_command:
          runId === firstRunId ? "asteria review --latest" : 'asteria goal "续作：补充测试与文档"',
        plan: {
          transcript_kind: "plan",
          title: "制定计划",
          summary: goal,
        },
      },
    });
    await fs.writeFile(
      path.join(runDir, "user_progress.jsonl"),
      [
        JSON.stringify({
          schema_version: "0.1.0",
          run_id: runId,
          channel: "progress",
          event_type: "start",
          phase: "plan",
          status: "running",
          title: "制定计划",
          summary: goal,
          display_level: "main",
          transcript_kind: "plan",
          ui_intent: "work_progress",
        }),
      ].join("\n") + "\n",
      "utf8",
    );
  }
}

async function writeJson(relativePath, value) {
  await fs.mkdir(path.dirname(relativePath), { recursive: true });
  await fs.writeFile(relativePath, `${JSON.stringify(value, null, 2)}\n`, "utf8");
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
  if (!response.ok) throw new Error(`${route} returned ${response.status}`);
  return response.json();
}

async function postJson(route, body) {
  const response = await fetch(`http://127.0.0.1:${port}${route}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok)
    throw new Error(`${route} returned ${response.status}: ${await response.text()}`);
  return response.json();
}

async function fetchEventsUntil(sessionId, predicate) {
  const route = `/api/studio/sessions/${encodeURIComponent(sessionId)}/events`;
  const deadline = Date.now() + 10_000;
  let latest = { events: [] };
  while (Date.now() < deadline) {
    latest = await fetchJson(route);
    if (predicate(latest.events || [])) return latest;
    if (server.exitCode !== null)
      throw new Error(`Studio server exited early. stdout=${stdout} stderr=${stderr}`);
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(
    `Timed out waiting for continuation ask answer. events=${(latest.events || []).length} stdout=${stdout} stderr=${stderr}`,
  );
}
