import { promises as fs } from "node:fs";
import path from "node:path";
import crypto from "node:crypto";

export async function controlledBinding(root, runDir, runId) {
  // Presentation fixture, not evidence of a real model reviewing these inputs.
  const evidenceId = "review-artifacts-control";
  const rows = [];
  for (const [kind, relative] of [
    ["run", "goal_spec.json"],
    ["run", "task_plan.json"],
    ["workspace", "AGENTS.md"],
  ]) {
    try {
      const body = await fs.readFile(path.join(kind === "run" ? runDir : root, relative));
      rows.push({
        root: kind,
        path: relative,
        exists: true,
        bytes: body.length,
        sha256: crypto.createHash("sha256").update(body).digest("hex"),
      });
    } catch (error) {
      if (error.code !== "ENOENT") throw error;
      rows.push({ root: kind, path: relative, exists: false, bytes: 0, sha256: null });
    }
  }
  await fs.writeFile(
    path.join(runDir, evidenceId + ".json"),
    JSON.stringify({ evidence_id: evidenceId, run_id: runId, complete: true, files: [] }),
  );
  return {
    current_artifacts_evidence: { evidence_id: evidenceId, complete: true },
    review_binding: {
      schema_version: "0.1.0",
      run_id: runId,
      artifact_evidence_id: evidenceId,
      scope: "bound_goal_tasks_artifacts_guidance_and_observed_dependencies",
      complete: true,
      files: rows,
      problems: [],
    },
  };
}
