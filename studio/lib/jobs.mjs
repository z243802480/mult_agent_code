// Studio live-job registry — the shared in-memory map of active/terminal jobs, extracted verbatim
// from server.mjs. Chat jobs, runtime jobs, the /jobs + /stop routes, and the workspace-switch guard
// all read/write this one registry (see docs/zh/notes/server-mjs-split-plan.md Layer 1b), so it must
// live below them as an injected facility. Pure state — no workspace capture, no fs.
export function createJobRegistry() {
  const liveJobs = new Map();

  // Keep liveJobs bounded. Terminal (completed/failed/cancelled) jobs are retained briefly so the
  // jobs/stop routes still reflect a just-finished run, then pruned after a grace window; a hard cap is
  // a backstop. Running jobs are never pruned. Prevents a long-lived server from growing the map
  // unbounded and keeps the workspace-switch guard (which scans liveJobs) honest.
  function pruneLiveJobs(maxAgeMs = 10 * 60 * 1000, keepLatest = 50) {
    const now = Date.now();
    for (const [id, job] of liveJobs) {
      const terminal =
        job.status === "completed" || job.status === "failed" || job.status === "cancelled";
      if (terminal && now - (job.started_at_ms || 0) > maxAgeMs) liveJobs.delete(id);
    }
    if (liveJobs.size > keepLatest) {
      const terminalIds = [...liveJobs.entries()]
        .filter(([, job]) => job.status !== "running")
        .map(([id]) => id);
      for (const id of terminalIds.slice(0, liveJobs.size - keepLatest)) liveJobs.delete(id);
    }
  }

  return { liveJobs, pruneLiveJobs };
}
