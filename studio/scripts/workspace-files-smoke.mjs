import { spawn } from "node:child_process";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

// Proves listWorkspaceFiles walks a GENERAL workspace root (not hardcoded Asteria repo roots) and
// skips noise (node_modules / dot-dirs like .git and .asteria) — the file pool for the Inspector
// browser and composer @-mentions.

const studioDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = path.resolve(studioDir, "..");
const port = Number(process.env.ASTERIA_STUDIO_FILES_PORT || 18811);
const base = `http://127.0.0.1:${port}`;

const workspace = await fs.mkdtemp(path.join(os.tmpdir(), "asteria-files-smoke-"));
// Real project files at various depths.
await fs.writeFile(path.join(workspace, "snake-game.html"), "<html></html>", "utf8");
await fs.mkdir(path.join(workspace, "src"), { recursive: true });
await fs.writeFile(path.join(workspace, "src", "app.py"), "print('hi')\n", "utf8");
// Noise that must NOT appear.
await fs.mkdir(path.join(workspace, "node_modules", "pkg"), { recursive: true });
await fs.writeFile(
  path.join(workspace, "node_modules", "pkg", "index.js"),
  "module.exports={}",
  "utf8",
);
await fs.mkdir(path.join(workspace, ".git"), { recursive: true });
await fs.writeFile(path.join(workspace, ".git", "config"), "[core]\n", "utf8");
await fs.mkdir(path.join(workspace, ".asteria", "runs"), { recursive: true });
await fs.writeFile(path.join(workspace, ".asteria", "runs", "goal_spec.json"), "{}", "utf8");

const server = spawn(
  process.execPath,
  ["server.mjs", "--workspace", workspace, "--runtime-root", repoRoot, "--port", String(port)],
  { cwd: studioDir, stdio: ["ignore", "pipe", "pipe"] },
);

function assert(cond, message) {
  if (!cond) throw new Error(message);
}

try {
  await waitForHealth();
  const res = await fetchJson(`${base}/api/studio/files`);
  const paths = (res.files ?? []).map((f) => f.path);
  assert(res.ok, `files not ok: ${JSON.stringify(res).slice(0, 200)}`);
  assert(
    paths.includes("snake-game.html"),
    `expected snake-game.html at root, got: ${JSON.stringify(paths)}`,
  );
  assert(paths.includes("src/app.py"), `expected src/app.py, got: ${JSON.stringify(paths)}`);
  assert(
    !paths.some((p) => p.startsWith("node_modules/")),
    `node_modules leaked: ${JSON.stringify(paths)}`,
  );
  assert(!paths.some((p) => p.startsWith(".git/")), `.git leaked: ${JSON.stringify(paths)}`);
  assert(
    !paths.some((p) => p.startsWith(".asteria/")),
    `.asteria leaked: ${JSON.stringify(paths)}`,
  );
  console.log("Studio workspace files smoke passed (general walk, noise excluded)");
} finally {
  server.kill("SIGTERM");
  await fs.rm(workspace, { recursive: true, force: true });
}

async function waitForHealth() {
  const deadline = Date.now() + 15_000;
  while (Date.now() < deadline) {
    try {
      const r = await fetch(`${base}/api/health`);
      if ((await r.json()).ok) return;
    } catch {}
    await new Promise((r) => setTimeout(r, 250));
  }
  throw new Error("Studio server did not become healthy");
}

async function fetchJson(url) {
  const r = await fetch(url);
  const text = await r.text();
  if (!r.ok) throw new Error(`${url} returned ${r.status}: ${text}`);
  return JSON.parse(text);
}
