// Workspace git helpers for the Studio server, extracted verbatim from server.mjs.
//
// A factory closes over a *live* workspace getter (the server reassigns its active
// `workspace` when the user switches repos, so capturing it by value would target the
// stale repo) plus an injected `runCommand`. The protected-path guard `isSafeWorkspacePath`
// (denies .git/secrets/.env/keys) is imported from ./workspace-paths.mjs — the single source
// of truth shared with the server. Each public function reads the current workspace once via
// `getWorkspace()` so its body is otherwise byte-identical to the original.
import { existsSync, promises as fs } from "node:fs";
import path from "node:path";
import { redactText } from "./text-utils.mjs";
import { isSafeWorkspacePath } from "./workspace-paths.mjs";

export function createGitHelpers({ getWorkspace, runCommand }) {
  function runGit(args, envOverrides) {
    return runCommand(["git", ...args], getWorkspace(), envOverrides);
  }

  // ── Non-git workspaces: shadow-repository fallback (F9, dogfood 2026-07-19) ──────────────
  // The Changes pane used to be a dead end for a workspace that was never `git init`-ed ("run
  // git init first" — while the banner above simultaneously said "review the diff"). Mainstream
  // agents show the agent's changes without requiring the user's directory to be a repo, so:
  // a shadow repository whose GIT_DIR lives under `.asteria/studio-shadow.git` (runtime state)
  // with `--work-tree` pointed at the workspace. The user's directory gains NO `.git` — we do
  // not init repos in the user's tree uninvited. The comparison baseline is a shadow commit
  // taken at each fresh writing run's start (server hook), so "changes" = what the latest run
  // changed — exactly what the review pane is for. Real repos never enter this path.
  //
  // Safety: the shadow snapshot must never capture secrets — `info/exclude` carries the
  // protected-path list (AGENTS §10) plus `.asteria/` itself (the shadow repo lives there;
  // snapshotting it into itself would recurse).
  const SHADOW_EXCLUDES = [
    ".asteria/",
    ".env",
    ".env.*",
    "secrets/",
    "*.pem",
    "*.key",
    "id_rsa*",
    "id_ed25519*",
  ];
  // Commit identity pinned so shadow commits work on machines with no global git identity.
  const SHADOW_IDENTITY = {
    GIT_AUTHOR_NAME: "Asteria Studio",
    GIT_AUTHOR_EMAIL: "studio@asteria.local",
    GIT_COMMITTER_NAME: "Asteria Studio",
    GIT_COMMITTER_EMAIL: "studio@asteria.local",
  };

  function hasRealRepo() {
    return existsSync(path.join(getWorkspace(), ".git"));
  }

  function shadowGitDir() {
    return path.join(getWorkspace(), ".asteria", "studio-shadow.git");
  }

  function runShadowGit(args, envOverrides = {}) {
    const workspace = getWorkspace();
    return runCommand(
      ["git", "--git-dir", shadowGitDir(), "--work-tree", workspace, ...args],
      workspace,
      { ...SHADOW_IDENTITY, ...envOverrides },
    );
  }

  /**
   * Ensure the shadow repo exists and advance its baseline to the CURRENT workspace state.
   * Called by the server at each fresh writing run's start; also lazily on first pane open
   * (then the pane honestly shows "no changes yet" until something runs). Best-effort by
   * contract — a failure falls back to the pane's unavailable message, never blocks a run.
   */
  async function ensureShadowBaseline(label = "baseline") {
    if (hasRealRepo()) return { ok: true, skipped: "real repo" };
    const gitDir = shadowGitDir();
    if (!existsSync(gitDir)) {
      await fs.mkdir(gitDir, { recursive: true });
      const inited = await runCommand(["git", "init", "--bare", gitDir], getWorkspace());
      if (inited.code !== 0)
        return { ok: false, reason: redactText(inited.stderr || "git init failed") };
      // A bare git-dir refuses worktree operations; flip the flag since we always pass
      // --work-tree explicitly.
      await runShadowGit(["config", "core.bare", "false"]);
      // Byte-exact snapshots: autocrlf would rewrite line endings on checkout (Windows), leaving
      // phantom "modified" entries after a revert restores a file. The shadow repo is ours, not a
      // collaboration surface — no eol munging.
      await runShadowGit(["config", "core.autocrlf", "false"]);
      await fs.mkdir(path.join(gitDir, "info"), { recursive: true }).catch(() => {});
      await fs.writeFile(
        path.join(gitDir, "info", "exclude"),
        `${SHADOW_EXCLUDES.join("\n")}\n`,
        "utf8",
      );
    }
    const added = await runShadowGit(["add", "-A", "--", "."]);
    if (added.code !== 0)
      return { ok: false, reason: redactText(added.stderr || "git add failed") };
    const committed = await runShadowGit([
      "commit",
      "--allow-empty",
      "-q",
      "-m",
      `asteria shadow baseline (${label})`,
    ]);
    if (committed.code !== 0)
      return { ok: false, reason: redactText(committed.stderr || "git commit failed") };
    return { ok: true };
  }

  /** Lazily ensure the shadow repo exists WITHOUT advancing an existing baseline. */
  async function ensureShadowReady() {
    if (existsSync(shadowGitDir())) return { ok: true };
    return ensureShadowBaseline("first-open");
  }

  function gitChangeLabel(indexStatus, worktreeStatus) {
    const code = `${indexStatus}${worktreeStatus}`;
    if (code.includes("?")) return "untracked";
    if (code.includes("A")) return "added";
    if (code.includes("D")) return "deleted";
    if (code.includes("R")) return "renamed";
    if (code.includes("M")) return "modified";
    return "changed";
  }

  function parseGitPorcelain(text) {
    const changes = [];
    for (const rawLine of String(text || "").split(/\r?\n/)) {
      const line = rawLine.trimEnd();
      if (!line) continue;
      if (line.startsWith("??")) {
        const filePath = line.slice(3).trim();
        if (!isSafeWorkspacePath(filePath)) continue;
        changes.push({ path: filePath, status: "untracked", index: "?", worktree: "?" });
        continue;
      }
      const indexStatus = line[0] || " ";
      const worktreeStatus = line[1] || " ";
      let filePath = line.slice(3).trim();
      if (filePath.includes(" -> ")) filePath = filePath.split(" -> ").pop()?.trim() || filePath;
      if (!isSafeWorkspacePath(filePath)) continue;
      changes.push({
        path: filePath,
        status: gitChangeLabel(indexStatus, worktreeStatus),
        index: indexStatus,
        worktree: worktreeStatus,
      });
    }
    return changes;
  }

  async function readWorkspaceGitStatus() {
    const workspace = getWorkspace();
    if (!existsSync(path.join(workspace, ".git"))) {
      // Shadow fallback: diff against the last pre-run baseline instead of a dead end.
      const ready = await ensureShadowReady();
      if (!ready.ok) {
        return {
          ok: true,
          available: false,
          workspace,
          reason: ready.reason || "shadow init failed",
        };
      }
      const statusResult = await runShadowGit(["status", "--porcelain", "-u"]);
      if (statusResult.code !== 0) {
        return {
          ok: true,
          available: false,
          workspace,
          reason: redactText(statusResult.stderr || "git status failed"),
        };
      }
      const changes = parseGitPorcelain(statusResult.stdout);
      const summary = changes.reduce((acc, item) => {
        acc[item.status] = (acc[item.status] || 0) + 1;
        return acc;
      }, {});
      return {
        ok: true,
        available: true,
        workspace,
        mode: "shadow",
        branch: "",
        clean: changes.length === 0,
        change_count: changes.length,
        summary,
        changes,
      };
    }
    const branchResult = await runGit(["branch", "--show-current"]);
    if (branchResult.code !== 0) {
      return {
        ok: true,
        available: false,
        workspace,
        reason: redactText(branchResult.stderr || "git unavailable"),
      };
    }
    const statusResult = await runGit(["status", "--porcelain", "-u"]);
    if (statusResult.code !== 0) {
      return {
        ok: true,
        available: false,
        workspace,
        reason: redactText(statusResult.stderr || "git status failed"),
      };
    }
    const changes = parseGitPorcelain(statusResult.stdout);
    const summary = changes.reduce((acc, item) => {
      acc[item.status] = (acc[item.status] || 0) + 1;
      return acc;
    }, {});
    return {
      ok: true,
      available: true,
      workspace,
      branch: String(branchResult.stdout || "").trim() || "HEAD",
      clean: changes.length === 0,
      change_count: changes.length,
      summary,
      changes,
    };
  }

  async function readWorkspaceGitDiff(relativePath, stage = "all") {
    const workspace = getWorkspace();
    const normalized = String(relativePath || "")
      .replace(/\\/g, "/")
      .trim();
    if (!normalized) return { ok: false, error: "path is required" };
    if (!isSafeWorkspacePath(normalized)) return { ok: false, error: "path is not allowed" };
    if (!existsSync(path.join(workspace, ".git"))) {
      // Shadow fallback: worktree vs. the pre-run baseline. No staged/unstaged split — the
      // shadow index is ours, not a user staging area.
      const ready = await ensureShadowReady();
      if (!ready.ok) return { ok: false, error: ready.reason || "shadow init failed" };
      // Agent-CREATED files are untracked in the shadow — record intent-to-add so git renders
      // the full new-file diff instead of nothing.
      const tracked = await runShadowGit(["ls-files", "--error-unmatch", "--", normalized]);
      if (tracked.code !== 0) await runShadowGit(["add", "--intent-to-add", "--", normalized]);
      const result = await runShadowGit(["diff", "--no-color", "HEAD", "--", normalized]);
      if (result.code !== 0)
        return { ok: false, error: redactText(result.stderr || "git diff failed") };
      const shadowDiff = redactText(String(result.stdout || ""));
      return {
        ok: true,
        path: normalized,
        stage,
        mode: "shadow",
        diff: shadowDiff.slice(0, 120_000) || "(no diff — file may be binary or unchanged)",
        staged: "",
        unstaged: shadowDiff,
        has_staged: false,
        has_unstaged: Boolean(shadowDiff.trim()),
        truncated: shadowDiff.length > 120_000,
      };
    }
    const stagedResult = await runGit(["diff", "--cached", "--no-color", "--", normalized]);
    const unstagedResult = await runGit(["diff", "--no-color", "--", normalized]);
    const staged = redactText(String(stagedResult.stdout || ""));
    const unstaged = redactText(String(unstagedResult.stdout || ""));
    let diff = "";
    if (stage === "staged") diff = staged;
    else if (stage === "unstaged") diff = unstaged;
    else {
      diff = [
        staged ? `--- staged ---\n${staged}` : "",
        unstaged ? `--- unstaged ---\n${unstaged}` : "",
      ]
        .filter(Boolean)
        .join("\n\n");
    }
    if (!diff && stagedResult.code !== 0 && unstagedResult.code !== 0) {
      return {
        ok: false,
        error: redactText(unstagedResult.stderr || stagedResult.stderr || "git diff failed"),
      };
    }
    const clipped = diff.slice(0, 120_000);
    return {
      ok: true,
      path: normalized,
      stage,
      diff: clipped || "(no diff — file may be untracked or binary)",
      staged,
      unstaged,
      has_staged: Boolean(staged.trim()),
      has_unstaged: Boolean(unstaged.trim()),
      truncated: diff.length > 120_000,
    };
  }

  async function stageWorkspaceGitFile(body) {
    const workspace = getWorkspace();
    const normalized = String(body?.path || "")
      .replace(/\\/g, "/")
      .trim();
    if (!normalized) return { ok: false, error: "path is required" };
    if (!isSafeWorkspacePath(normalized)) return { ok: false, error: "path is not allowed" };
    if (!existsSync(path.join(workspace, ".git"))) {
      // Shadow: "keep this file" = fold it into the baseline (add + commit), so it drops out
      // of the Changes list — the closest analog of staging when there is no user repo.
      const ready = await ensureShadowReady();
      if (!ready.ok) return { ok: false, error: ready.reason || "shadow init failed" };
      const added = await runShadowGit(["add", "--", normalized]);
      if (added.code !== 0)
        return { ok: false, error: redactText(added.stderr || "git add failed") };
      const committed = await runShadowGit([
        "commit",
        "-q",
        "-m",
        `asteria shadow accept (${normalized})`,
      ]);
      if (committed.code !== 0)
        return { ok: false, error: redactText(committed.stderr || "git commit failed") };
      return { ok: true, path: normalized, action: "staged", mode: "shadow" };
    }
    const result = await runGit(["add", "--", normalized]);
    if (result.code !== 0)
      return { ok: false, error: redactText(result.stderr || "git add failed") };
    return { ok: true, path: normalized, action: "staged" };
  }

  async function discardWorkspaceGitFile(body) {
    const workspace = getWorkspace();
    const normalized = String(body?.path || "")
      .replace(/\\/g, "/")
      .trim();
    if (!normalized) return { ok: false, error: "path is required" };
    if (!isSafeWorkspacePath(normalized)) return { ok: false, error: "path is not allowed" };
    // Shadow: identical revert semantics against the pre-run baseline (checkout restores the
    // baseline content; an agent-created file is untracked there too and gets removed).
    const shadowMode = !existsSync(path.join(workspace, ".git"));
    if (shadowMode) {
      const ready = await ensureShadowReady();
      if (!ready.ok) return { ok: false, error: ready.reason || "shadow init failed" };
    }
    const run = shadowMode ? runShadowGit : runGit;
    // Shadow: a prior diff call may have recorded intent-to-add for this file, which makes
    // `ls-files --error-unmatch` succeed and would route a created file into the checkout
    // branch (which errors on ita entries). Reset the index entry to match the baseline first.
    if (shadowMode) await run(["reset", "-q", "--", normalized]);
    // Untracked files (the COMMON case: a file the agent just CREATED) cannot be reverted with
    // `git checkout` — it errors "pathspec did not match". `git status -u` still lists them, so the
    // thread shows a Revert button for them. For an untracked file, "revert" means remove the
    // newly-created file from disk; tracked files revert to their last committed content.
    const tracked = await run(["ls-files", "--error-unmatch", "--", normalized]);
    if (tracked.code !== 0) {
      const absolute = path.join(workspace, normalized);
      try {
        if (existsSync(absolute)) await fs.rm(absolute, { force: true });
      } catch (err) {
        return { ok: false, error: redactText(String(err?.message || "failed to remove file")) };
      }
      return { ok: true, path: normalized, action: "removed" };
    }
    const result = await run(["checkout", "--", normalized]);
    if (result.code !== 0)
      return { ok: false, error: redactText(result.stderr || "git checkout failed") };
    return { ok: true, path: normalized, action: "discarded" };
  }

  // ── G7 rewind 文件回滚: shadow workspace snapshots (Claude Code checkpoint / Cline shadow-git
  // model). A snapshot is a REAL commit object built through a TEMP index — the user's staging
  // area, HEAD and branches are never touched, and a ref under refs/asteria/ keeps it alive
  // without appearing as a branch. `.asteria/` (runtime state) is excluded both ways: it must not
  // be rolled back with user code. No cleanup policy by design (local disk; documented).

  const SNAPSHOT_EXCLUDES = ["--", ".", ":(exclude).asteria"];

  function validSnapshotHash(value) {
    return /^[0-9a-f]{7,40}$/i.test(String(value || "").trim());
  }

  async function createWorkspaceSnapshot(label = "turn") {
    const workspace = getWorkspace();
    if (!existsSync(path.join(workspace, ".git"))) {
      return { ok: false, reason: "not a git repository" };
    }
    const tmpIndex = path.join(
      workspace,
      ".git",
      `asteria-snap-index-${Date.now()}-${Math.random().toString(16).slice(2)}`,
    );
    const env = { GIT_INDEX_FILE: tmpIndex };
    try {
      const head = await runGit(["rev-parse", "--verify", "HEAD"]);
      const hasHead = head.code === 0;
      if (hasHead) {
        const seeded = await runGit(["read-tree", "HEAD"], env);
        if (seeded.code !== 0)
          return { ok: false, reason: redactText(seeded.stderr || "git read-tree failed") };
      }
      const added = await runGit(["add", "-A", ...SNAPSHOT_EXCLUDES], env);
      if (added.code !== 0)
        return { ok: false, reason: redactText(added.stderr || "git add failed") };
      const wrote = await runGit(["write-tree"], env);
      if (wrote.code !== 0)
        return { ok: false, reason: redactText(wrote.stderr || "git write-tree failed") };
      const tree = wrote.stdout.trim();
      const commitArgs = ["commit-tree", tree, "-m", `asteria snapshot (${label})`];
      if (hasHead) commitArgs.push("-p", head.stdout.trim());
      const committed = await runGit(commitArgs);
      if (committed.code !== 0)
        return { ok: false, reason: redactText(committed.stderr || "git commit-tree failed") };
      const snapshot = committed.stdout.trim();
      // Keep-alive ref, invisible to normal branch UX. Best-effort: the hash in the session event
      // still works for git's unreachable-object horizon even if the ref write fails.
      await runGit(["update-ref", `refs/asteria/snapshots/${snapshot.slice(0, 12)}`, snapshot]);
      return { ok: true, snapshot, tree };
    } finally {
      await fs.rm(tmpIndex, { force: true }).catch(() => {});
    }
  }

  // Files that exist in the worktree today but not in the snapshot — restoring would DELETE them.
  // Split out so the preview and the restore compute the same set.
  async function snapshotExtraFiles(snapshot) {
    const snapFiles = await runGit(["ls-tree", "-r", "--name-only", snapshot]);
    const current = await runGit(["ls-files", "--cached", "--others", "--exclude-standard"]);
    const inSnapshot = new Set(
      String(snapFiles.stdout || "")
        .split(/\r?\n/)
        .filter(Boolean),
    );
    return String(current.stdout || "")
      .split(/\r?\n/)
      .filter(Boolean)
      .filter(
        (file) =>
          !inSnapshot.has(file) && !/^\.asteria(\/|$)/i.test(file) && isSafeWorkspacePath(file),
      );
  }

  async function workspaceSnapshotDiff(body) {
    const workspace = getWorkspace();
    const snapshot = String(body?.snapshot || "").trim();
    if (!validSnapshotHash(snapshot)) return { ok: false, error: "快照标识无效。" };
    if (!existsSync(path.join(workspace, ".git")))
      return { ok: false, error: "此工作区不是 Git 仓库。" };
    const exists = await runGit(["cat-file", "-e", `${snapshot}^{commit}`]);
    if (exists.code !== 0) return { ok: false, error: "快照不存在（可能已被 git gc 回收）。" };
    const numstat = await runGit(["diff", "--numstat", snapshot, ...SNAPSHOT_EXCLUDES]);
    if (numstat.code !== 0)
      return { ok: false, error: redactText(numstat.stderr || "git diff 失败。") };
    const changed = String(numstat.stdout || "")
      .split(/\r?\n/)
      .filter(Boolean)
      .map((line) => {
        const [additions, deletions, ...rest] = line.split("\t");
        return {
          path: rest.join("\t"),
          additions: Number(additions) || 0,
          deletions: Number(deletions) || 0,
        };
      })
      .filter((row) => row.path && isSafeWorkspacePath(row.path));
    const toDelete = await snapshotExtraFiles(snapshot);
    return {
      ok: true,
      snapshot,
      changed,
      to_delete: toDelete,
      clean: changed.length === 0 && toDelete.length === 0,
    };
  }

  async function restoreWorkspaceSnapshot(body) {
    const workspace = getWorkspace();
    const snapshot = String(body?.snapshot || "").trim();
    if (!validSnapshotHash(snapshot)) return { ok: false, error: "快照标识无效。" };
    if (!existsSync(path.join(workspace, ".git")))
      return { ok: false, error: "此工作区不是 Git 仓库——文件无法回滚。" };
    const exists = await runGit(["cat-file", "-e", `${snapshot}^{commit}`]);
    if (exists.code !== 0) return { ok: false, error: "快照不存在（可能已被 git gc 回收）。" };
    // The rewind itself must be undoable: shadow-snapshot the CURRENT state first.
    const safety = await createWorkspaceSnapshot("pre-rewind safety");
    const restored = await runGit([
      "restore",
      "--source",
      snapshot,
      "--worktree",
      ...SNAPSHOT_EXCLUDES,
    ]);
    if (restored.code !== 0)
      return { ok: false, error: redactText(restored.stderr || "git restore 失败。") };
    // Delete files created after the snapshot (restore only rewrites paths the snapshot HAS).
    const extras = await snapshotExtraFiles(snapshot);
    for (const file of extras) {
      await fs.rm(path.join(workspace, file), { force: true }).catch(() => {});
    }
    return {
      ok: true,
      snapshot,
      deleted: extras.length,
      safety_snapshot: safety.ok ? safety.snapshot : null,
    };
  }

  return {
    readWorkspaceGitStatus,
    readWorkspaceGitDiff,
    stageWorkspaceGitFile,
    discardWorkspaceGitFile,
    createWorkspaceSnapshot,
    workspaceSnapshotDiff,
    restoreWorkspaceSnapshot,
    ensureShadowBaseline,
  };
}
