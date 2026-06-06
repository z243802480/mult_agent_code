import { spawn } from "node:child_process";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const studioDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = path.resolve(studioDir, "..");
const port = Number(process.env.ASTERIA_STUDIO_GIT_PORT || 18802);
const python = process.env.ASTERIA_PYTHON || "python";

const workspace = await fs.mkdtemp(path.join(os.tmpdir(), "asteria-git-smoke-"));
await runCommand(["git", "init"], workspace);
await fs.writeFile(path.join(workspace, "hello.txt"), "v1\n", "utf8");
await runCommand(["git", "add", "hello.txt"], workspace);
await runCommand(["git", "-c", "user.email=smoke@test", "-c", "user.name=smoke", "commit", "-m", "init"], workspace);
await fs.writeFile(path.join(workspace, "hello.txt"), "v2\n", "utf8");

const server = spawn(process.execPath, [
  "server.mjs",
  "--workspace",
  workspace,
  "--runtime-root",
  repoRoot,
  "--port",
  String(port),
  "--python",
  python,
], { cwd: studioDir, stdio: ["ignore", "pipe", "pipe"] });

try {
  await waitForHealth();
  const status = await fetchJson(`http://127.0.0.1:${port}/api/studio/git/status`);
  if (!status.available) throw new Error(`git status unavailable: ${JSON.stringify(status)}`);
  if (!status.branch) throw new Error("missing branch");
  if ((status.changes ?? []).length < 1) throw new Error("expected at least one git change");

  const target = status.changes[0].path;
  const diff = await fetchJson(`http://127.0.0.1:${port}/api/studio/git/diff?path=${encodeURIComponent(target)}`);
  if (!diff.ok || !String(diff.diff ?? "").includes("v2")) {
    throw new Error(`git diff missing expected content: ${JSON.stringify(diff)}`);
  }

  console.log(JSON.stringify({
    ok: true,
    summary: "git changes smoke passed",
    workspace,
    branch: status.branch,
    change: target,
  }, null, 2));
} finally {
  server.kill("SIGTERM");
  await fs.rm(workspace, { recursive: true, force: true });
}

function runCommand(command, cwd) {
  return new Promise((resolve, reject) => {
    const child = spawn(command[0], command.slice(1), { cwd, stdio: ["ignore", "pipe", "pipe"] });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => { stdout += chunk; });
    child.stderr.on("data", (chunk) => { stderr += chunk; });
    child.on("close", (code) => {
      if (code === 0) resolve({ stdout, stderr });
      else reject(new Error(`${command.join(" ")} failed (${code}): ${stderr || stdout}`));
    });
  });
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

async function fetchJson(url) {
  const response = await fetch(url);
  const text = await response.text();
  const payload = JSON.parse(text);
  if (!response.ok) throw new Error(`${url} returned ${response.status}: ${text}`);
  return payload;
}
