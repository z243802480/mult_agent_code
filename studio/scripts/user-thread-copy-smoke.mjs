import { spawn } from "node:child_process";
import { promises as fs } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const studioDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const workspace = await fs.mkdtemp(path.join(os.tmpdir(), "asteria-studio-user-thread-copy-"));
const port = Number(process.env.ASTERIA_STUDIO_USER_THREAD_COPY_PORT || 18791);
const forbidden =
  /\bcommand\b|Inspector|Evidence Explorer|\brun-\d{8}-\d{4}\b|stdout|stderr|status\s+--json|\.asteria|model route|provider route|provider_transient|provider_network|model-check|Runtime progress|Runtime goal|Runtime result|Agent loop|Run activity|gate-status|route guidance|token|backend metadata/i;

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
  const session = await postJson("/api/studio/sessions", {});
  const sessionId = session.session.session_id;

  await postJson(`/api/studio/sessions/${encodeURIComponent(sessionId)}/messages`, {
    mode: "run",
    permission: "ask",
    message: "Update README with a short project overview.",
  });
  await postJson(`/api/studio/sessions/${encodeURIComponent(sessionId)}/messages`, {
    mode: "review",
    permission: "ask",
    message: "Review the current result before accepting it.",
  });

  const { events } = await fetchEventsUntil(
    sessionId,
    (items) => items.filter((event) => event.type === "permission_request").length >= 2,
  );

  const mainEvents = (events || []).filter(
    (event) => !event.display_level || event.display_level === "main",
  );
  assert(mainEvents.length > 0, "expected user-visible main-thread events");
  for (const event of mainEvents) {
    const visibleText = [event.title, event.summary, event.content_delta]
      .filter(Boolean)
      .join("\n");
    assert(
      !forbidden.test(visibleText),
      `main-thread copy leaked backend wording: ${JSON.stringify({ type: event.type, visibleText })}`,
    );
  }

  const permissionRequests = mainEvents.filter((event) => event.type === "permission_request");
  assert(
    permissionRequests.length >= 2,
    `expected two visible permission requests, got ${permissionRequests.length}`,
  );
  assert(
    permissionRequests.some((event) => Array.isArray(event.command) && event.command.length > 0),
    "permission events may keep command metadata for backend use",
  );
  for (const event of permissionRequests) {
    const visibleText = [event.title, event.summary, event.content_delta]
      .filter(Boolean)
      .join("\n");
    assert(
      /confirm|continue|确认|继续|取消|修改|运行|操作/i.test(visibleText),
      `permission copy should explain user action, got ${visibleText}`,
    );
    const preview = event.data?.permission_preview;
    assert(
      preview && typeof preview === "object",
      "permission request must expose a user-semantic permission_preview",
    );
    for (const key of ["action", "impact", "scope", "network", "risk", "reversible"]) {
      assert(String(preview[key] || "").trim(), `permission_preview.${key} must be present`);
    }
  }

  const permissionCardSource = await fs.readFile(
    path.join(studioDir, "src", "components", "PermissionCard.tsx"),
    "utf8",
  );
  const eventCardSource = await fs.readFile(
    path.join(studioDir, "src", "components", "EventCard.tsx"),
    "utf8",
  );
  assert(
    !/permissionCommand|event\.command|\.command\.join/.test(permissionCardSource),
    "PermissionCard must not render backend commands in the user thread",
  );
  assert(
    !/event\.command|\.command\.join/.test(eventCardSource),
    "EventCard must not render backend commands in the user thread",
  );
  assert(
    /permission_preview|Permission impact/.test(permissionCardSource),
    "PermissionCard must render semantic permission impact",
  );

  // One-shot gate: denying one job closes only that card. A second denial of the same stale job
  // must fail, rather than falsely reporting another successful cancellation.
  const firstJobId = permissionRequests[0].job_id;
  const secondJobId = permissionRequests[1].job_id;
  const permissionRoute = `/api/studio/sessions/${encodeURIComponent(sessionId)}/jobs/${encodeURIComponent(firstJobId)}/permission`;
  const denied = await patchJson(permissionRoute, { action: "deny" });
  assert(denied.ok && denied.started === false, "first permission denial was not recorded");
  const afterDenial = await fetchJson(
    `/api/studio/sessions/${encodeURIComponent(sessionId)}/events`,
  );
  assert(
    !(afterDenial.events || []).some(
      (event) => event.type === "permission_request" && event.job_id === firstJobId,
    ),
    "resolved permission card reappeared in the session replay",
  );
  assert(
    (afterDenial.events || []).some(
      (event) => event.type === "permission_request" && event.job_id === secondJobId,
    ),
    "resolving one job removed another pending permission card",
  );
  const deniedAgain = await patchJson(permissionRoute, { action: "deny" });
  assert(deniedAgain.ok === false, "stale permission denial reported success");

  console.log("Studio user-thread copy smoke passed");
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
  if (!response.ok)
    throw new Error(`${route} returned ${response.status}: ${await response.text()}`);
  return response.json();
}

async function patchJson(route, body) {
  const response = await fetch(`http://127.0.0.1:${port}${route}`, {
    method: "PATCH",
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
    `Timed out waiting for permission copy events. events=${(latest.events || []).length} stdout=${stdout} stderr=${stderr}`,
  );
}
