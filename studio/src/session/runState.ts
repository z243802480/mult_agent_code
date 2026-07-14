/**
 * Authoritative run state.
 *
 * The event log says what was WRITTEN, not whether the process is still ALIVE. Deriving "running"
 * from events alone (the old `isSessionLive` on its own) means a job that dies without flushing a
 * terminal event — the server restarted, the Python subtree was killed from outside, the machine
 * slept — leaves the UI spinning "运行中" forever, and Stop then answers "no running job". That is
 * the stuck-spinner bug.
 *
 * Mainstream coding agents (Claude Code, Cursor, Codex) treat the job/process registry as the
 * source of truth and report an interrupted run honestly rather than pretending it is still going.
 * We do the same: the server's /jobs registry decides.
 *
 * Two things keep this honest instead of merely different:
 *
 * 1. Unknown ≠ dead. If the /jobs probe fails (server unreachable, offline dev), `jobsRunning` is
 *    null and we FALL BACK to the event signal. We never claim a run died just because we could
 *    not ask.
 * 2. Debounce the completion race. A normally-finishing job flips to status!=running slightly
 *    BEFORE its final_answer event lands on disk, so a single "events live but 0 running jobs"
 *    sample is not evidence of death. Only a discrepancy that survives `STALE_CHECKS_BEFORE_DEAD`
 *    consecutive probes counts.
 */

export type RunState = "idle" | "running" | "interrupted";

/** Consecutive "events say live, registry says nothing is running" probes before we call it dead. */
export const STALE_CHECKS_BEFORE_DEAD = 2;

export function deriveRunState(input: {
  /** Event-log signal (isSessionLive) — a hint, not the authority. */
  eventsLive: boolean;
  /** Running jobs per the server registry; null when the registry could not be reached. */
  jobsRunning: number | null;
  /** How many consecutive probes have seen eventsLive && jobsRunning === 0. */
  staleChecks: number;
}): RunState {
  const { eventsLive, jobsRunning, staleChecks } = input;
  if (!eventsLive) return "idle";
  if (jobsRunning === null) return "running"; // unknown registry: trust the events, never fabricate death
  if (jobsRunning > 0) return "running";
  return staleChecks >= STALE_CHECKS_BEFORE_DEAD ? "interrupted" : "running";
}
