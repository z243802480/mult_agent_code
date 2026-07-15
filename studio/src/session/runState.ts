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

export type RunState = "idle" | "running" | "waiting" | "interrupted";

/** Consecutive "events say live, registry says nothing is running" probes before we call it dead. */
export const STALE_CHECKS_BEFORE_DEAD = 2;

export function deriveRunState(input: {
  /** Event-log signal (isSessionLive) — a hint, not the authority. */
  eventsLive: boolean;
  /** Running jobs per the server registry; null when the registry could not be reached. */
  jobsRunning: number | null;
  /** How many consecutive probes have seen eventsLive && jobsRunning === 0. */
  staleChecks: number;
  /**
   * The registry holds a job for this session and none are running — the run SETTLED (finished
   * cleanly) rather than vanished. During the normal completion race a job flips terminal a beat
   * before its final_answer event flushes to disk; in that window eventsLive is still true and
   * jobsRunning is 0, which the debounced check would eventually mislabel "interrupted". A settled
   * run is finishing, not dead, so we report "running" (it flips to idle the moment the final event
   * lands) and NEVER "interrupted". Only a jobless registry (server restarted / pruned) is a genuine
   * lost-track candidate. Absent (older server) → undefined, and the debounced check stands unchanged.
   */
  settled?: boolean;
  /**
   * The loop is parked on a pending permission/decision gate, waiting for the user's input (e.g. the
   * initial goal-start approval, or a shell command that needs a one-off approval). This is a
   * DELIBERATE pause, not a dead process — so it must be reported as "waiting", never "interrupted"
   * (which is warn-toned and reads as a crash) and never "running" (there is no work in flight). It is
   * authoritative over the jobs registry: a parked-for-you run may legitimately have no live subprocess
   * (the pre-run gate hasn't spawned one yet), and that absence is not evidence of death here.
   */
  waitingForUser?: boolean;
}): RunState {
  const { eventsLive, jobsRunning, staleChecks, waitingForUser = false, settled = false } = input;
  if (!eventsLive) return "idle";
  if (waitingForUser) return "waiting";
  if (jobsRunning === null) return "running"; // unknown registry: trust the events, never fabricate death
  if (jobsRunning > 0) return "running";
  // jobsRunning === 0: the run either settled cleanly (job terminal in the registry, final event a
  // beat behind) or lost track (no job record at all). Only the latter can be an interruption.
  if (settled) return "running"; // finishing — flips to idle when the final event lands, never "已中断"
  return staleChecks >= STALE_CHECKS_BEFORE_DEAD ? "interrupted" : "running";
}
