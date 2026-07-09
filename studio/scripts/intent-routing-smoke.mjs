import { spawn } from "node:child_process";
import { promises as fs } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const studioDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const workspace = await fs.mkdtemp(path.join(os.tmpdir(), "asteria-studio-intent-smoke-"));
const port = Number(process.env.ASTERIA_STUDIO_INTENT_SMOKE_PORT || 18788);
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
  await waitForHealth(port);
  const session = await postJson(`/api/studio/sessions`, {});
  const sessionId = session.session.session_id;

  await postJson(`/api/studio/sessions/${encodeURIComponent(sessionId)}/messages`, {
    mode: "auto",
    permission: "ask",
    message: "How do I learn English effectively?",
  });
  await postJson(`/api/studio/sessions/${encodeURIComponent(sessionId)}/messages`, {
    mode: "auto",
    permission: "ask",
    message: "Fix the typo in README and run tests.",
  });
  await postJson(`/api/studio/sessions/${encodeURIComponent(sessionId)}/messages`, {
    mode: "auto",
    permission: "allow",
    message: "Fix the typo in README and run tests.",
  });
  await postJson(`/api/studio/sessions/${encodeURIComponent(sessionId)}/messages`, {
    mode: "auto",
    permission: "ask",
    message: "Plan a 3-day Qingdao travel itinerary",
  });
  await postJson(`/api/studio/sessions/${encodeURIComponent(sessionId)}/messages`, {
    mode: "plan",
    permission: "ask",
    message: "Plan a 3-day Qingdao travel itinerary",
  });

  const eventsPayload = await fetchEventsUntil(sessionId, (events) => {
    const routes = events.filter((event) => event.intent_route).map((event) => event.intent_route);
    return (
      routes.length >= 5 &&
      Boolean(
        events.find(
          (event) =>
            event.phase === "execute" &&
            (event.type === "reasoning_delta" || event.type === "assistant_delta"),
        ),
      ) &&
      events.filter((event) => event.type === "final_answer" && event.phase === "chat").length >= 3
    );
  });
  const events = eventsPayload.events || [];
  const routes = events.filter((event) => event.intent_route).map((event) => event.intent_route);
  const intentAuditEvents = events.filter((event) => event.intent_audit);
  const intentAudits = intentAuditEvents.map((event) => event.intent_audit);
  assert(routes.length === 5, `expected 5 intent routes, got ${routes.length}`);
  assert(
    intentAudits.length >= 5,
    `expected at least 5 intent audit records, got ${intentAudits.length}`,
  );
  assert(
    routes[0].mode === "chat",
    `ordinary question should route to chat, got ${routes[0].mode}`,
  );
  assert(
    routes[1].mode === "plan",
    `edit-like request with ask permission should route to plan, got ${routes[1].mode}`,
  );
  assert(
    routes[2].mode === "run",
    `edit-like request with allow permission should route to run, got ${routes[2].mode}`,
  );
  assert(
    routes[3].mode === "chat",
    `content planning request should stay in chat, got ${routes[3].mode}`,
  );
  assert(
    routes[4].mode === "chat",
    `plan override for content-only request should be guarded into chat, got ${routes[4].mode}`,
  );
  const travelAudit = intentAudits.find(
    (audit) => audit.intent_kind === "travel_plan" && audit.route === "chat",
  );
  assert(
    Boolean(travelAudit),
    `expected travel_plan chat audit metadata, got ${JSON.stringify(intentAudits)}`,
  );
  assert(
    travelAudit.permission_effect === "read_only",
    `expected travel chat permission_effect=read_only, got ${travelAudit.permission_effect}`,
  );
  assert(
    travelAudit.prompt_enrichment === "outcome_oriented_answer_contract",
    `expected generic outcome-oriented prompt contract, got ${travelAudit.prompt_enrichment}`,
  );
  assert(
    travelAudit.user_visible === false,
    "intent audit metadata should be hidden from the ordinary thread",
  );
  const visibleRouteEvents = events.filter(
    (event) => event.type === "intent_route" && event.display_level !== "inspector",
  );
  assert(
    visibleRouteEvents.length === 0,
    `intent route events should stay inspector-only, got ${visibleRouteEvents.length}`,
  );

  const permissionRequests = events.filter((event) => event.type === "permission_request");
  assert(
    permissionRequests.length === 0,
    `auto ask->plan and allow->run should not emit permission requests, got ${permissionRequests.length}`,
  );

  const chatAnswers = events.filter(
    (event) => event.type === "final_answer" && event.phase === "chat",
  );
  assert(
    chatAnswers.length >= 3,
    `ordinary/content questions should produce chat answers, got ${chatAnswers.length}`,
  );

  const planStart = events.find(
    (event) =>
      event.phase === "plan" &&
      (event.type === "reasoning_delta" || event.type === "assistant_delta"),
  );
  assert(Boolean(planStart), "ask-permission edit request should start a plan job");
  const runStart = events.find(
    (event) =>
      event.phase === "execute" &&
      (event.type === "reasoning_delta" || event.type === "assistant_delta"),
  );
  assert(Boolean(runStart), "allow-permission edit request should start a run job");

  console.log("Studio intent routing smoke passed");
} finally {
  server.kill("SIGTERM");
  await new Promise((resolve) => setTimeout(resolve, 200));
  await fs.rm(workspace, { recursive: true, force: true });
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

async function waitForHealth(targetPort) {
  const deadline = Date.now() + 10_000;
  let lastError;
  while (Date.now() < deadline) {
    try {
      const health = await fetchJson("/api/health", targetPort);
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

async function fetchJson(route, targetPort = port) {
  const response = await fetch(`http://127.0.0.1:${targetPort}${route}`);
  if (!response.ok) {
    throw new Error(`${route} returned ${response.status}`);
  }
  return response.json();
}

async function fetchEventsUntil(sessionId, predicate) {
  const route = `/api/studio/sessions/${encodeURIComponent(sessionId)}/events`;
  const deadline = Date.now() + 30_000;
  let latest = { events: [] };
  while (Date.now() < deadline) {
    try {
      latest = await fetchJson(route);
    } catch (error) {
      if (server.exitCode !== null) {
        throw new Error(
          `Studio server exited early. stdout=${stdout} stderr=${stderr} fetch=${error}`,
        );
      }
      await new Promise((resolve) => setTimeout(resolve, 250));
      continue;
    }
    if (predicate(latest.events || [])) return latest;
    if (server.exitCode !== null) {
      throw new Error(`Studio server exited early. stdout=${stdout} stderr=${stderr}`);
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(
    `Timed out waiting for routed events. routes=${JSON.stringify((latest.events || []).filter((event) => event.intent_route).map((event) => event.intent_route))} finals=${(latest.events || []).filter((event) => event.type === "final_answer" && event.phase === "chat").length} latest_count=${(latest.events || []).length} stdout=${stdout} stderr=${stderr}`,
  );
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
