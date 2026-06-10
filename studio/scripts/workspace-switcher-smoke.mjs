import { spawn } from "node:child_process";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const studioDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = path.resolve(studioDir, "..");
const port = Number(process.env.ASTERIA_STUDIO_WS_PORT || 18801);
const python = process.env.ASTERIA_PYTHON || "python";

const workspaceA = await fs.mkdtemp(path.join(os.tmpdir(), "asteria-ws-a-"));
const workspaceB = await fs.mkdtemp(path.join(os.tmpdir(), "asteria-ws-b-"));
let initTarget = null;
await fs.writeFile(path.join(workspaceA, "marker-a.txt"), "A", "utf8");
await fs.writeFile(path.join(workspaceB, "marker-b.txt"), "B", "utf8");

const server = spawn(process.execPath, [
  "server.mjs",
  "--workspace",
  workspaceA,
  "--runtime-root",
  repoRoot,
  "--port",
  String(port),
  "--python",
  python,
], {
  cwd: studioDir,
  stdio: ["ignore", "pipe", "pipe"],
  env: { ...process.env, ASTERIA_HOME: path.join(os.tmpdir(), `asteria-ws-home-${Date.now()}`) },
});

try {
  await waitForHealth();
  const initial = await fetchJson("http://127.0.0.1:" + port + "/api/studio/settings");
  if (!await samePath(initial.settings.workspace, workspaceA)) {
    throw new Error(`expected initial workspace A, got ${initial.settings.workspace}`);
  }

  const opened = await fetchJson("http://127.0.0.1:" + port + "/api/studio/workspace/open", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ path: workspaceB }),
  });
  if (!opened.ok || !await samePath(opened.workspace, workspaceB)) {
    throw new Error(`workspace open failed: ${JSON.stringify(opened)}`);
  }

  const after = await fetchJson("http://127.0.0.1:" + port + "/api/studio/settings");
  if (!await samePath(after.settings.workspace, workspaceB)) {
    throw new Error(`settings workspace did not switch: ${after.settings.workspace}`);
  }

  const registry = await fetchJson("http://127.0.0.1:" + port + "/api/studio/workspaces");
  const recentRoots = (registry.recent_workspaces ?? []).map((item) => item.workspace_root);
  if (!await includesPath(recentRoots, workspaceB)) {
    throw new Error(`recent workspaces missing B: ${JSON.stringify(recentRoots)}`);
  }

  initTarget = await fs.mkdtemp(path.join(os.tmpdir(), "asteria-ws-init-"));
  const initialized = await fetchJson("http://127.0.0.1:" + port + "/api/studio/workspace/open", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ path: initTarget }),
  });
  if (!initialized.ok || !initialized.initialized) {
    throw new Error(`expected init on first open: ${JSON.stringify(initialized)}`);
  }
  await fs.access(path.join(initTarget, ".asteria", "project.json"));

  const profile = await fetchJson(`http://127.0.0.1:${port}/api/studio/workspace/profile?path=${encodeURIComponent(workspaceB)}`);
  if (!profile.initialized) throw new Error(`profile missing initialized flag: ${JSON.stringify(profile)}`);

  console.log(JSON.stringify({
    ok: true,
    summary: "workspace switcher smoke passed",
    workspaceA: path.resolve(workspaceA),
    workspaceB: path.resolve(workspaceB),
    initTarget: path.resolve(initTarget),
  }, null, 2));
} finally {
  server.kill("SIGTERM");
  await fs.rm(workspaceA, { recursive: true, force: true });
  await fs.rm(workspaceB, { recursive: true, force: true });
  if (initTarget) await fs.rm(initTarget, { recursive: true, force: true });
}

async function samePath(left, right) {
  const [resolvedLeft, resolvedRight] = await Promise.all([fs.realpath(left), fs.realpath(right)]);
  return resolvedLeft.toLowerCase() === resolvedRight.toLowerCase();
}

async function includesPath(candidates, expected) {
  for (const candidate of candidates) {
    if (await samePath(candidate, expected)) return true;
  }
  return false;
}

async function waitForHealth() {
  const deadline = Date.now() + 15_000;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`http://127.0.0.1:${port}/api/health`);
      const health = await response.json();
      if (health.ok) return;
    } catch {}
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error("Studio server did not become healthy");
}

async function fetchJson(url, init) {
  const response = await fetch(url, init);
  const text = await response.text();
  let payload;
  try {
    payload = JSON.parse(text);
  } catch {
    throw new Error(`${url} returned non-JSON: ${text}`);
  }
  if (!response.ok) {
    throw new Error(`${url} returned ${response.status}: ${text}`);
  }
  return payload;
}
