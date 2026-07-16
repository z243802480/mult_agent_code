/**
 * G7 rewind 文件回滚 — shadow-snapshot round trip against a real temp git repo (hermetic):
 *
 *   1. createWorkspaceSnapshot builds a commit through a TEMP index: the user's staging area and
 *      HEAD must be untouched, and .asteria/ must be excluded from the snapshot.
 *   2. workspaceSnapshotDiff previews exactly what a restore would do (changed rows + files that
 *      would be deleted).
 *   3. restoreWorkspaceSnapshot puts the worktree back byte-for-byte: edits reverted, deleted
 *      files resurrected, post-snapshot files removed — while .asteria/ and the safety snapshot
 *      (rewind-the-rewind) survive.
 */
import { spawnSync } from "node:child_process";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { createGitHelpers } from "../lib/git.mjs";

function assert(cond, message) {
  if (!cond) throw new Error(message);
}

const workspace = await fs.mkdtemp(path.join(os.tmpdir(), "asteria-snap-smoke-"));

function runCommand(command, cwd, envOverrides = {}) {
  const result = spawnSync(command[0], command.slice(1), {
    cwd,
    env: { ...process.env, ...envOverrides },
    encoding: "utf8",
    windowsHide: true,
  });
  return { code: result.status ?? 1, stdout: result.stdout ?? "", stderr: result.stderr ?? "" };
}

const git = (...args) => runCommand(["git", ...args], workspace);
const helpers = createGitHelpers({ getWorkspace: () => workspace, runCommand });

try {
  // Baseline repo: one committed file + runtime state that must stay out of snapshots.
  git("init", "-q");
  git("-c", "user.email=t@t", "-c", "user.name=t", "checkout", "-qb", "main");
  await fs.writeFile(path.join(workspace, "app.py"), "def add(a, b):\n    return a + b\n", "utf8");
  await fs.mkdir(path.join(workspace, ".asteria"), { recursive: true });
  await fs.writeFile(path.join(workspace, ".asteria", "state.json"), '{"run":1}', "utf8");
  git("add", "app.py");
  git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base");

  // Turn 1 state: app.py edited + helper.py created. User also STAGES a file — the snapshot must
  // not disturb that staging.
  await fs.writeFile(
    path.join(workspace, "app.py"),
    "def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n",
    "utf8",
  );
  await fs.writeFile(path.join(workspace, "helper.py"), "HELPER = 1\n", "utf8");
  git("add", "helper.py");
  const stagedBefore = git("diff", "--cached", "--name-only").stdout.trim();

  const snap = await helpers.createWorkspaceSnapshot("smoke turn 1");
  assert(snap.ok && /^[0-9a-f]{40}$/.test(snap.snapshot), `snapshot failed: ${snap.reason}`);
  const stagedAfter = git("diff", "--cached", "--name-only").stdout.trim();
  assert(stagedAfter === stagedBefore, "snapshot disturbed the user's staging area");
  const snapTree = git("ls-tree", "-r", "--name-only", snap.snapshot).stdout;
  assert(snapTree.includes("helper.py") && snapTree.includes("app.py"), "snapshot missing files");
  assert(!snapTree.includes(".asteria"), "snapshot must exclude .asteria runtime state");

  // Turn 2 damage: edit app.py, DELETE helper.py, add extra.py.
  await fs.writeFile(
    path.join(workspace, "app.py"),
    "def add(a, b):\n    return a * b  # bug\n",
    "utf8",
  );
  await fs.rm(path.join(workspace, "helper.py"));
  await fs.writeFile(path.join(workspace, "extra.py"), "EXTRA = 2\n", "utf8");

  const preview = await helpers.workspaceSnapshotDiff({ snapshot: snap.snapshot });
  assert(preview.ok && !preview.clean, `preview failed: ${JSON.stringify(preview)}`);
  const changedPaths = preview.changed.map((row) => row.path);
  assert(
    changedPaths.includes("app.py") && changedPaths.includes("helper.py"),
    `preview missed changes: ${changedPaths.join(",")}`,
  );
  assert(preview.to_delete.includes("extra.py"), "preview missed the post-snapshot file");

  const restored = await helpers.restoreWorkspaceSnapshot({ snapshot: snap.snapshot });
  assert(restored.ok, `restore failed: ${JSON.stringify(restored)}`);
  assert(restored.safety_snapshot, "restore must auto-snapshot the pre-rewind state");
  const appNow = await fs.readFile(path.join(workspace, "app.py"), "utf8");
  assert(appNow.includes("def sub"), "app.py was not restored to the snapshot content");
  assert(!appNow.includes("# bug"), "app.py still carries the post-snapshot edit");
  const helperBack = await fs.readFile(path.join(workspace, "helper.py"), "utf8");
  assert(helperBack.includes("HELPER = 1"), "deleted helper.py was not resurrected");
  const extraGone = await fs
    .access(path.join(workspace, "extra.py"))
    .then(() => true)
    .catch(() => false);
  assert(!extraGone, "post-snapshot extra.py must be removed by the restore");
  const asteriaIntact = await fs.readFile(path.join(workspace, ".asteria", "state.json"), "utf8");
  assert(asteriaIntact === '{"run":1}', ".asteria runtime state must never be touched");

  // The safety snapshot makes the rewind itself undoable: restoring it brings the damage back.
  const undo = await helpers.restoreWorkspaceSnapshot({ snapshot: restored.safety_snapshot });
  assert(undo.ok, `undo-restore failed: ${JSON.stringify(undo)}`);
  const appUndone = await fs.readFile(path.join(workspace, "app.py"), "utf8");
  assert(appUndone.includes("# bug"), "safety snapshot did not restore the pre-rewind state");
  const extraBack = await fs.readFile(path.join(workspace, "extra.py"), "utf8");
  assert(extraBack.includes("EXTRA = 2"), "safety snapshot lost the post-snapshot file");

  // Non-git degradation is honest.
  const bare = await fs.mkdtemp(path.join(os.tmpdir(), "asteria-snap-bare-"));
  const bareHelpers = createGitHelpers({ getWorkspace: () => bare, runCommand });
  const bareSnap = await bareHelpers.createWorkspaceSnapshot("no repo");
  assert(!bareSnap.ok && /not a git repository/.test(bareSnap.reason), "non-git must degrade");
  await fs.rm(bare, { recursive: true, force: true });

  console.log("Studio snapshot-rollback smoke passed (shadow snapshot → preview → restore → undo)");
} finally {
  await fs.rm(workspace, { recursive: true, force: true }).catch(() => {});
}
