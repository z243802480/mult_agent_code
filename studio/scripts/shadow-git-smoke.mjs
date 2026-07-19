// F9 (dogfood 2026-07-19): non-git workspaces must still get a working Changes pane via the
// shadow repository (.asteria/studio-shadow.git). This smoke boots the real server on a temp
// workspace that was NEVER `git init`-ed and drives the same HTTP API the pane uses:
//   1. /git/status → available with mode:"shadow" (lazy baseline on first open, clean)
//   2. mutate the workspace (modify one file, create another)
//   3. /git/status → both changes listed
//   4. /git/diff → real diff content for the modified AND the created (untracked) file
//   5. /git/discard → created file removed, modified file restored to baseline content
//   6. the user's workspace still has NO .git (we never init repos in the user's tree)
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const studioDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = path.resolve(studioDir, "..");
const port = Number(process.env.ASTERIA_STUDIO_SHADOW_GIT_PORT || 18807);
const python = process.env.ASTERIA_PYTHON || "python";

const workspace = await fs.mkdtemp(path.join(os.tmpdir(), "asteria-shadow-git-smoke-"));
await fs.writeFile(path.join(workspace, "hello.txt"), "v1\n", "utf8");

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

try {
  await waitForHealth();

  // 1. First open: lazy baseline, clean, shadow mode.
  const first = await fetchJson(`http://127.0.0.1:${port}/api/studio/git/status`);
  if (!first.available) throw new Error(`shadow status unavailable: ${JSON.stringify(first)}`);
  if (first.mode !== "shadow") throw new Error(`expected mode shadow, got: ${first.mode}`);
  if ((first.changes ?? []).length !== 0)
    throw new Error(`expected clean baseline, got: ${JSON.stringify(first.changes)}`);

  // 2. Mutate after the baseline.
  await fs.writeFile(path.join(workspace, "hello.txt"), "v2\n", "utf8");
  await fs.writeFile(path.join(workspace, "created.txt"), "new file\n", "utf8");

  // 3. Both changes listed.
  const status = await fetchJson(`http://127.0.0.1:${port}/api/studio/git/status`);
  const paths = (status.changes ?? []).map((change) => change.path).sort();
  if (JSON.stringify(paths) !== JSON.stringify(["created.txt", "hello.txt"]))
    throw new Error(`expected both changes, got: ${JSON.stringify(status.changes)}`);

  // 4. Diffs render content — including the untracked (agent-created) file.
  const modifiedDiff = await fetchJson(
    `http://127.0.0.1:${port}/api/studio/git/diff?path=hello.txt`,
  );
  if (!modifiedDiff.ok || !String(modifiedDiff.diff ?? "").includes("+v2"))
    throw new Error(`modified diff missing +v2: ${JSON.stringify(modifiedDiff)}`);
  const createdDiff = await fetchJson(
    `http://127.0.0.1:${port}/api/studio/git/diff?path=created.txt`,
  );
  if (!createdDiff.ok || !String(createdDiff.diff ?? "").includes("+new file"))
    throw new Error(`created-file diff missing content: ${JSON.stringify(createdDiff)}`);

  // 5. Revert both: created file removed from disk, modified file restored to baseline v1.
  const removed = await postJson(`http://127.0.0.1:${port}/api/studio/git/discard`, {
    path: "created.txt",
  });
  if (!removed.ok || removed.action !== "removed")
    throw new Error(`expected created file removal: ${JSON.stringify(removed)}`);
  if (existsSync(path.join(workspace, "created.txt")))
    throw new Error("created.txt still exists after discard");
  const discarded = await postJson(`http://127.0.0.1:${port}/api/studio/git/discard`, {
    path: "hello.txt",
  });
  if (!discarded.ok || discarded.action !== "discarded")
    throw new Error(`expected modified file discard: ${JSON.stringify(discarded)}`);
  // Byte-exact compare ON PURPOSE: the shadow repo pins core.autocrlf=false so a revert restores
  // the baseline bytes exactly — an eol rewrite here would leave a phantom "modified" entry in the
  // Changes pane after every revert (live-caught on Windows, 2026-07-19).
  const restored = await fs.readFile(path.join(workspace, "hello.txt"), "utf8");
  if (restored !== "v1\n")
    throw new Error(`expected baseline v1 restored byte-exact, got: ${JSON.stringify(restored)}`);

  // 6. The user's workspace gained no .git.
  if (existsSync(path.join(workspace, ".git")))
    throw new Error("a .git appeared in the user's workspace — shadow must never init there");

  console.log("shadow-git-smoke: PASS");
} finally {
  server.kill();
  await fs.rm(workspace, { recursive: true, force: true }).catch(() => {});
}

async function waitForHealth() {
  const deadline = Date.now() + 30_000;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`http://127.0.0.1:${port}/api/health`);
      const health = await response.json();
      if (health.ok) return;
    } catch {
      // server still booting
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error("server did not become healthy in 30s");
}

async function fetchJson(url) {
  const response = await fetch(url);
  return response.json();
}

async function postJson(url, body) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  return response.json();
}
