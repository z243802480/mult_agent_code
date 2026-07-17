// The settings endpoint is a PATCH, not a whole-object write: each panel saves only the field it
// owns. Until G8-a it accepted exactly one field (permissionMode) and 400'd on everything else, so
// widening it is the kind of change that quietly breaks the caller it used to serve. This pins both
// halves: the old single-field request still works, and neither field clobbers the other.
import { spawn } from "node:child_process";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const studioDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = path.resolve(studioDir, "..");
const port = Number(process.env.ASTERIA_STUDIO_SETTINGS_PORT || 18821);
const python = process.env.ASTERIA_PYTHON || "python";

const workspace = await fs.mkdtemp(path.join(os.tmpdir(), "asteria-settings-"));

const server = spawn(
  process.execPath,
  ["server.mjs", "--workspace", workspace, "--runtime-root", repoRoot, "--port", String(port),
   "--python", python],
  {
    cwd: studioDir,
    stdio: ["ignore", "pipe", "pipe"],
    env: {
      ...process.env,
      ASTERIA_HOME: path.join(os.tmpdir(), `asteria-settings-home-${Date.now()}`),
    },
  },
);

try {
  await waitForHealth();

  const initial = await get();
  expect(initial.settings.modelStrategy === "auto", `fresh workspace must default to auto strategy,
    got ${initial.settings.modelStrategy}`);

  // The pre-G8-a request shape, byte for byte. This is the regression that matters.
  const tierOnly = await post({ permissionMode: "auto" });
  expect(tierOnly.ok, `single-field permissionMode save must still work: ${JSON.stringify(tierOnly)}`);
  expect(tierOnly.settings.permissionMode === "auto", "permissionMode did not save");
  expect(tierOnly.settings.modelStrategy === "auto", "strategy must be untouched by a tier save");

  const strategyOnly = await post({ modelStrategy: "economy" });
  expect(strategyOnly.ok, `single-field modelStrategy save failed: ${JSON.stringify(strategyOnly)}`);
  expect(strategyOnly.settings.modelStrategy === "economy", "modelStrategy did not save");
  // The point of patch semantics: the model panel must not silently reset the permission tier.
  expect(strategyOnly.settings.permissionMode === "auto", "tier must be untouched by a strategy save");

  const both = await post({ permissionMode: "ask_everything", modelStrategy: "quality" });
  expect(both.ok && both.settings.permissionMode === "ask_everything", "combined save lost the tier");
  expect(both.settings.modelStrategy === "quality", "combined save lost the strategy");

  // Rejected at the door, never coerced — a silently-corrected save would show a value nobody picked.
  const badStrategy = await post({ modelStrategy: "gpt-9" });
  expect(badStrategy.ok === false, "an unknown strategy must be rejected, not coerced");
  const badTier = await post({ permissionMode: "yolo" });
  expect(badTier.ok === false, "an unknown tier must be rejected, not coerced");
  const empty = await post({});
  expect(empty.ok === false, "a request with no writable setting must be rejected");

  // A rejected save must leave the stored values alone.
  const after = await get();
  expect(
    after.settings.permissionMode === "ask_everything" && after.settings.modelStrategy === "quality",
    `rejected saves mutated state: ${JSON.stringify(after.settings)}`,
  );

  // What the run path will actually read (lib/run-flags.mjs reads this file, not the payload).
  const persisted = JSON.parse(
    await fs.readFile(path.join(workspace, ".asteria", "studio", "settings.json"), "utf8"),
  );
  expect(
    persisted.modelStrategy === "quality" && persisted.permissionMode === "ask_everything",
    `settings.json disagrees with the payload: ${JSON.stringify(persisted)}`,
  );

  console.log(JSON.stringify({ ok: true, summary: "settings patch smoke passed", persisted }, null, 2));
} finally {
  server.kill("SIGTERM");
  await fs.rm(workspace, { recursive: true, force: true });
}

function expect(condition, message) {
  if (!condition) throw new Error(message);
}

function get() {
  return fetchJson(`http://127.0.0.1:${port}/api/studio/settings`);
}

function post(body) {
  return fetchJson(`http://127.0.0.1:${port}/api/studio/settings`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

async function fetchJson(url, init) {
  const response = await fetch(url, init);
  return response.json();
}

async function waitForHealth() {
  const deadline = Date.now() + 15_000;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`http://127.0.0.1:${port}/api/health`);
      const health = await response.json();
      if (health.ok) return;
    } catch {
      // server still booting
    }
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  throw new Error("studio server did not become healthy");
}
