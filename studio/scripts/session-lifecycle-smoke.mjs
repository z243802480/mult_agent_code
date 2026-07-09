import { spawn } from "node:child_process";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

// Proves the session soft-delete lifecycle (I10): delete is reversible — a stray click on a
// long-task session marks it deleted (hidden from the list) but keeps its data recoverable via
// restore, and only an explicit ?purge=1 removes it for good.

const studioDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = path.resolve(studioDir, "..");
const port = Number(process.env.ASTERIA_STUDIO_LIFECYCLE_PORT || 18809);
const python = process.env.ASTERIA_PYTHON || "python";
const base = `http://127.0.0.1:${port}`;

const workspace = await fs.mkdtemp(path.join(os.tmpdir(), "asteria-session-smoke-"));

const server = spawn(
  process.execPath,
  [
    "server.mjs",
    "--workspace",
    workspace,
    "--runtime-root",
    repoRoot,
    "--port",
    String(port),
    "--python",
    python,
  ],
  { cwd: studioDir, stdio: ["ignore", "pipe", "pipe"] },
);

function assert(cond, message) {
  if (!cond) throw new Error(message);
}

try {
  await waitForHealth();

  // 1. Create a session.
  const created = await fetchJson(`${base}/api/studio/sessions`, "POST");
  const sid = created?.session?.session_id;
  assert(created.ok && sid, `create failed: ${JSON.stringify(created)}`);

  // 2. It appears in the list.
  const listAfterCreate = await fetchJson(`${base}/api/studio/sessions`);
  assert(
    listAfterCreate.sessions.some((s) => s.session_id === sid),
    "created session missing from list",
  );

  // --- Export / import (backup + restore-to-file) ---
  // Seed one event straight into events.jsonl (organic events need a runtime job) so export/import
  // can prove event preservation, not just session metadata.
  const eventsFile = path.join(workspace, ".asteria", "studio", "sessions", sid, "events.jsonl");
  const seeded = {
    event_id: "evt-seed-1",
    session_id: sid,
    type: "user_message",
    summary: "hello backup",
    content_delta: "hello backup",
  };
  await fs.writeFile(eventsFile, `${JSON.stringify(seeded)}\n`, "utf8");

  const bundle = await fetchJson(`${base}/api/studio/sessions/${sid}/export`);
  assert(
    bundle.asteria_session_bundle && bundle.session?.session_id === sid,
    `export missing session: ${JSON.stringify(bundle).slice(0, 200)}`,
  );
  assert(
    Array.isArray(bundle.events) &&
      bundle.events.length === 1 &&
      bundle.events[0].event_id === "evt-seed-1",
    `export missing seeded event: ${JSON.stringify(bundle.events)}`,
  );

  const imported = await fetchJson(`${base}/api/studio/sessions/import`, "POST", { bundle });
  const importedId = imported?.session?.session_id;
  assert(
    imported.ok && importedId && importedId !== sid,
    `import failed: ${JSON.stringify(imported)}`,
  );
  assert(
    imported.imported === 1 && imported.session.imported_from === sid,
    `import metadata wrong: ${JSON.stringify(imported)}`,
  );

  const importedEvents = await fetchJson(`${base}/api/studio/sessions/${importedId}/events`);
  assert(
    importedEvents.events.length === 1 && importedEvents.events[0].session_id === importedId,
    `imported events not re-stamped: ${JSON.stringify(importedEvents)}`,
  );

  // Clean up the imported session so it doesn't affect the lifecycle assertions below.
  await fetchJson(`${base}/api/studio/sessions/${importedId}?purge=1`, "DELETE");

  // 3. Soft-delete (default): reversible, not a hard delete.
  const deleted = await fetchJson(`${base}/api/studio/sessions/${sid}`, "DELETE");
  assert(
    deleted.ok && deleted.soft_deleted === true && !deleted.purged,
    `expected soft delete: ${JSON.stringify(deleted)}`,
  );

  // 4. Hidden from the main list...
  const listAfterDelete = await fetchJson(`${base}/api/studio/sessions`);
  assert(
    !listAfterDelete.sessions.some((s) => s.session_id === sid),
    "soft-deleted session still in list",
  );

  // 5. ...but its data is preserved and marked deleted_at (recoverable).
  const readDeleted = await fetchJson(`${base}/api/studio/sessions/${sid}`);
  assert(
    readDeleted.ok && readDeleted.session.deleted_at,
    `soft-deleted session data not preserved: ${JSON.stringify(readDeleted)}`,
  );

  // 6. Restore clears the marker.
  const restored = await fetchJson(`${base}/api/studio/sessions/${sid}/restore`, "POST");
  assert(
    restored.ok && restored.restored === sid && !restored.session.deleted_at,
    `restore failed: ${JSON.stringify(restored)}`,
  );

  // 7. Back in the list.
  const listAfterRestore = await fetchJson(`${base}/api/studio/sessions`);
  assert(
    listAfterRestore.sessions.some((s) => s.session_id === sid),
    "restored session missing from list",
  );

  // 8. Explicit purge is permanent.
  const purged = await fetchJson(`${base}/api/studio/sessions/${sid}?purge=1`, "DELETE");
  assert(purged.ok && purged.purged === true, `expected purge: ${JSON.stringify(purged)}`);

  // 9. Gone for good.
  const readPurged = await fetchJson(`${base}/api/studio/sessions/${sid}`);
  assert(readPurged.ok === false, `purged session should be gone: ${JSON.stringify(readPurged)}`);

  console.log("Studio session lifecycle smoke passed (soft-delete → restore → purge)");
} finally {
  server.kill("SIGTERM");
  await fs.rm(workspace, { recursive: true, force: true });
}

async function waitForHealth() {
  const deadline = Date.now() + 15_000;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`${base}/api/health`);
      const health = await response.json();
      if (health.ok) return;
    } catch {}
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error("Studio server did not become healthy");
}

async function fetchJson(url, method = "GET", body) {
  const init = { method };
  if (body !== undefined) {
    init.headers = { "content-type": "application/json" };
    init.body = JSON.stringify(body);
  }
  const response = await fetch(url, init);
  const text = await response.text();
  const payload = JSON.parse(text);
  if (!response.ok) throw new Error(`${url} returned ${response.status}: ${text}`);
  return payload;
}
