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
  function runGit(args) {
    return runCommand(["git", ...args], getWorkspace());
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
      return { ok: true, available: false, workspace, reason: "not a git repository" };
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
      return { ok: false, error: "not a git repository" };
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
    if (!existsSync(path.join(workspace, ".git")))
      return { ok: false, error: "not a git repository" };
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
    if (!existsSync(path.join(workspace, ".git")))
      return { ok: false, error: "not a git repository" };
    // Untracked files (the COMMON case: a file the agent just CREATED) cannot be reverted with
    // `git checkout` — it errors "pathspec did not match". `git status -u` still lists them, so the
    // thread shows a Revert button for them. For an untracked file, "revert" means remove the
    // newly-created file from disk; tracked files revert to their last committed content.
    const tracked = await runGit(["ls-files", "--error-unmatch", "--", normalized]);
    if (tracked.code !== 0) {
      const absolute = path.join(workspace, normalized);
      try {
        if (existsSync(absolute)) await fs.rm(absolute, { force: true });
      } catch (err) {
        return { ok: false, error: redactText(String(err?.message || "failed to remove file")) };
      }
      return { ok: true, path: normalized, action: "removed" };
    }
    const result = await runGit(["checkout", "--", normalized]);
    if (result.code !== 0)
      return { ok: false, error: redactText(result.stderr || "git checkout failed") };
    return { ok: true, path: normalized, action: "discarded" };
  }

  return {
    readWorkspaceGitStatus,
    readWorkspaceGitDiff,
    stageWorkspaceGitFile,
    discardWorkspaceGitFile,
  };
}
