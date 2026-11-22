// Check the runtime-owned content binding. This grants no action permissions and
// proves neither full workspace coverage nor the correctness of a model judgment.
import { promises as fs } from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { isSafeId, isSafeWorkspacePath } from "./workspace-paths.mjs";

const maxFiles = 10020,
  maxBytes = 138412032;
const scope = "bound_inputs_only_not_full_workspace_or_semantic_coverage";
const digest = (body) => crypto.createHash("sha256").update(body).digest("hex");
const readJson = async (file) => JSON.parse(await fs.readFile(file, "utf8"));

function artifactRelative(value, sourceRoot) {
  const normalized = String(value).replaceAll("\\", "/");
  if (!normalized.startsWith("/") && !/^[A-Za-z]:\//.test(normalized)) return normalized;
  const prefix = String(sourceRoot).replaceAll("\\", "/").replace(/\/$/, "") + "/";
  const insensitive = /^[A-Za-z]:\//.test(prefix) || prefix.startsWith("//");
  if (
    !(insensitive
      ? normalized.toLowerCase().startsWith(prefix.toLowerCase())
      : normalized.startsWith(prefix))
  )
    throw new Error("Artifact outside source root");
  return normalized.slice(prefix.length);
}

function protectedByPolicy(relative, patterns) {
  for (const original of patterns) {
    const pattern = String(original).replaceAll("\\", "/");
    // Unsupported character classes fail closed rather than read a possibly protected file.
    if (pattern.includes("[")) throw new Error("Unsupported protection pattern");
    if (
      pattern.endsWith("/") &&
      (relative === pattern.slice(0, -1) || relative.startsWith(pattern))
    )
      return true;
    const expression = pattern
      .split("")
      .map((char) =>
        char === "*" ? ".*" : char === "?" ? "." : char.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"),
      )
      .join("");
    if (new RegExp(`^${expression}$`).test(relative)) return true;
  }
  return false;
}

export async function reviewFreshness(workspace, runDir, runId, report) {
  const base = {
    status: "unbound",
    reason: "Review has no verifiable input binding; review current inputs before accepting.",
    changed_inputs: [],
    scope,
  };
  const binding = report?.artifact_eval?.review_binding;
  if (!binding || typeof binding !== "object") return base;
  try {
    const evidenceId = binding.artifact_evidence_id;
    if (
      binding.schema_version !== "0.1.0" ||
      binding.scope !== "bound_goal_tasks_artifacts_guidance_and_observed_dependencies" ||
      binding.run_id !== runId ||
      report.run_id !== runId ||
      report.artifact_eval?.current_artifacts_evidence?.complete !== true ||
      evidenceId !== report.artifact_eval?.current_artifacts_evidence?.evidence_id ||
      !isSafeId(evidenceId) ||
      !evidenceId.startsWith("review-artifacts-") ||
      binding.complete !== true ||
      !Array.isArray(binding.problems) ||
      binding.problems.length ||
      !Array.isArray(binding.files) ||
      binding.files.length > maxFiles
    )
      throw new Error("Invalid binding");
    const snapshotPath = path.join(runDir, `${evidenceId}.json`);
    if ((await fs.lstat(snapshotPath)).isSymbolicLink()) throw new Error("Linked snapshot");
    const snapshot = await readJson(snapshotPath);
    if (
      snapshot.run_id !== runId ||
      snapshot.evidence_id !== evidenceId ||
      snapshot.complete !== true ||
      !Array.isArray(snapshot.files)
    )
      throw new Error("Invalid snapshot");
    const required = new Set([
      "run/goal_spec.json",
      "run/task_plan.json",
      "workspace/AGENTS.md",
      ...snapshot.files.map(
        (row) => `workspace/${artifactRelative(row.path, snapshot.workspace_root)}`,
      ),
    ]);
    const seen = new Set(),
      changed = [];
    const mustExist = new Set([
      "run/goal_spec.json",
      "run/task_plan.json",
      ...snapshot.files.map(
        (row) => `workspace/${artifactRelative(row.path, snapshot.workspace_root)}`,
      ),
    ]);
    let total = 0,
      policy = {};
    try {
      policy = await readJson(path.join(workspace, ".asteria/policies.json"));
    } catch (error) {
      if (error.code !== "ENOENT") throw error;
    }
    const protectedPaths = policy.protected_paths ?? [];
    if (!Array.isArray(protectedPaths)) throw new Error("Invalid protection policy");
    for (const row of binding.files) {
      if (
        typeof row.path !== "string" ||
        row.path.includes("\\") ||
        row.path.includes(":") ||
        path.isAbsolute(row.path) ||
        row.path.split("/").includes("..") ||
        !Number.isSafeInteger(row.bytes) ||
        row.bytes < 0 ||
        typeof row.exists !== "boolean"
      )
        throw new Error("Invalid input");
      const key = `${row.root}/${row.path}`;
      if (mustExist.has(key) && !row.exists) throw new Error("Required reviewed input is absent");
      if (seen.has(key)) throw new Error("Repeated input");
      seen.add(key);
      total += row.bytes;
      if (total > maxBytes) throw new Error("Input limit");
      let root;
      if (row.root === "run" && ["goal_spec.json", "task_plan.json"].includes(row.path))
        root = runDir;
      else if (
        row.root === "workspace" &&
        isSafeWorkspacePath(row.path) &&
        !row.path
          .split("/")
          .some(
            (part) => [".asteria", ".git", "secrets"].includes(part) || part.startsWith(".env"),
          ) &&
        !protectedByPolicy(row.path, protectedPaths)
      )
        root = workspace;
      else throw new Error("Protected input");
      let file = root;
      let missing = false;
      for (const part of row.path.split("/")) {
        file = path.join(file, part);
        try {
          if ((await fs.lstat(file)).isSymbolicLink()) throw new Error("Linked input");
        } catch (error) {
          if (error.code === "ENOENT") {
            missing = true;
            break;
          }
          throw error;
        }
      }
      if (missing) {
        if (row.exists !== false || row.bytes !== 0 || row.sha256 !== null) changed.push(key);
        continue;
      }
      const stat = await fs.stat(file);
      if (!stat.isFile() || !row.exists || stat.size !== row.bytes) {
        changed.push(key);
        continue;
      }
      const body = await fs.readFile(file);
      if (body.length !== row.bytes || digest(body) !== row.sha256) changed.push(key);
    }
    if ([...required].some((key) => !seen.has(key))) throw new Error("Missing bound input");
    return {
      ...base,
      status: changed.length ? "changed" : "current",
      changed_inputs: changed,
      reason: changed.length
        ? "Bound Review inputs changed; review the current inputs again."
        : "Bound Review input contents match; this is not a semantic coverage certification.",
    };
  } catch {
    return {
      ...base,
      status: "unavailable",
      reason:
        "Review input binding cannot be verified safely; review current inputs before accepting.",
    };
  }
}
