// Cross-run guard: at most one workspace-mutating run at a time.
//
// Every Studio session shares ONE workspace — `workspace` is a module-level singleton (server.mjs)
// that only openWorkspace rewrites, and while createSession stamps it onto session.workspace nobody
// reads that copy back; the run itself uses the global. So "two sessions pointed at the same path"
// is not a risk case, it is the only case.
//
// Nothing downstream reconciles two runs. On the DEFAULT serial path the model's write_file lands
// straight on source_root through PathGuard(context.root) (tools/file_tools.py:55) — no candidate
// workspace is even created; that only happens for concurrent writing experts. And the one lock
// that claims to stop "a concurrent run" from interleaving writes, _PROMOTION_APPLY_LOCK
// (candidate_execution_gateway.py:17), is a threading.RLock — process-local, while the second run
// is a different OS process (probe, changelog 1.2.109: warm worker + cold spawn, or two cold
// spawns). The merge gate only arbitrates within one run's own batch.
//
// Hence the guard sits HERE, before a run starts, rather than on any write path: this is the only
// place that sees all of them, and it covers both the serial and the candidate branch for free.

/**
 * Modes known NOT to touch the user's files. Everything else counts as a writer.
 *
 * Inverted deliberately. Listing the WRITERS would leave a mode added later unguarded until someone
 * remembered to add it, and that failure is silent file loss. Listing the READERS leaves a new mode
 * guarded until someone proves it safe, and that failure is a visible, annoying refusal. Pick the
 * failure you can see.
 *
 * Each entry was traced to its command rather than grepped:
 *   chat   — chat_command.py:234 only reads the tool registry's .names() for the prompt envelope;
 *            no tool-execution loop. CLI help: "no state-changing project work".
 *   review — review_command.py:178 the same. `--rerun` re-executes the run's verification commands
 *            (arbitrary shell), but it defaults off and Studio never passes it (server.mjs:609).
 *            Move review out of this set if Studio ever starts passing --rerun.
 *   plan   — plan_command.py:250 the same; cli.py prints "read-only analysis; no execution started".
 *   decide — Studio always passes --list-pending (server.mjs), which returns before any write
 *            (decide_command.py:101-107).
 */
export const READ_ONLY_MODES = new Set(["chat", "review", "plan", "decide"]);

/** Whether a run in `mode` can change files in the shared workspace. Unknown modes: assume yes. */
export function mutatesWorkspace(mode) {
  return !READ_ONLY_MODES.has(String(mode || "").toLowerCase());
}

/**
 * The running writer that must finish before a `mode` run may start, or null if the way is clear.
 *
 * `jobs` is liveJobs.values(). Call it BEFORE registering the new job, or it finds itself. Read-only
 * modes neither block nor are blocked — asking a question while a run is in flight has always
 * worked and this guard must not take that away.
 */
export function blockingJob(jobs, mode) {
  if (!mutatesWorkspace(mode)) return null;
  for (const job of jobs || []) {
    if (job?.status === "running" && mutatesWorkspace(job.mode)) return job;
  }
  return null;
}

/**
 * Modes that re-enter existing work instead of carrying the message the user just typed.
 *
 * Listed rather than inferred: every other mode either runs the goal (run/plan) or answers it
 * (chat). These three replay something older, so a message routed here is never executed.
 */
const GOAL_DROPPING_MODES = new Set(["resume", "accept", "review"]);

/**
 * Whether the user must be told that their message was not the thing that just started.
 *
 * The sibling of blockingJob(): there the turn does not start and we say so. Here a turn DOES
 * start — someone else's. The router picks resume/accept/review when every executor path is
 * blocked, drops the typed goal, and the older work's output lands in the thread looking like the
 * answer to what was just asked. That is how "add an export subcommand" came back as "我已在
 * taskman.py 中添加了 export 子命令…验证已通过（4/4 checks passed）" with nothing written anywhere
 * (Round 2 dogfood R2-12) — the router even explained itself, at display_level "inspector".
 *
 * Only for routes the user did not pick: choosing 继续/resume yourself is not a surprise.
 */
export function droppedGoalNotice(mode, requestedMode) {
  if (!GOAL_DROPPING_MODES.has(String(mode || "").toLowerCase())) return null;
  if (String(requestedMode || "auto").toLowerCase() !== "auto") return null;
  return {
    title: "这条目标没有单独开始",
    summary:
      "这个工作区还有一个在跑的任务，所以你刚发的这条没有单独起一个新任务——下面的进展和结论属于那个任务，不是你刚发的这条。等它跑完（或先把它停掉）再发一次，就会单独执行。",
  };
}

/** Longest blocker goal echoed back; past this it stops identifying a task and starts being a wall. */
const GOAL_ECHO_LIMIT = 60;

/**
 * What the user reads when their turn does not start. Identifies the run holding the workspace and
 * says what to do about it — "another run is in progress" with no way forward is just a wall.
 *
 * Deliberately not phrased as a breakage: nothing broke. The turn did not start ON PURPOSE, because
 * starting it would have let two processes write the same files with nothing reconciling them. The
 * one thing this must never imply is that the user's files were touched — they were not.
 */
/**
 * The thread event for a refused turn. Built here so the two enforcement points word it identically.
 *
 * There are two on purpose, and they are not two sources of truth — both ask the same blockingJob()
 * over the same liveJobs. startRuntimeJob is the AUTHORITATIVE gate (it covers every caller, including
 * any added later). submitUserGoal checks earlier only so it can bail before announcing "Starting"
 * (chat-routes.mjs:220 fires optimistically, ahead of both the permission gate and the run) — a thread
 * reading "正在开始" and then "本轮没有开始" contradicts itself.
 *
 * Rides the existing "your turn did not start" channel (type:"error"), which the thread already
 * renders; from the user's side nothing ran, which is exactly what that channel means. The words,
 * not the type, carry the distinction that this was deliberate and left their files alone.
 */
export function blockedEvent(blocker) {
  const notice = blockedNotice(blocker);
  return {
    type: "error",
    status: "failed",
    title: notice.title,
    summary: notice.summary,
    content_delta: notice.body,
    display_level: "main",
    data: { blocked_by_job: blocker?.job_id, blocked_by_session: blocker?.session_id },
  };
}

export function blockedNotice(blocker) {
  const goal = String(blocker?.goal || "").trim();
  const what = goal
    ? `另一个会话正在这个工作区里跑：${goal.length > GOAL_ECHO_LIMIT ? `${goal.slice(0, GOAL_ECHO_LIMIT)}…` : goal}`
    : "另一个会话正在这个工作区里跑";
  return {
    title: "本轮没有开始",
    summary: "另一个会话正在这个工作区里跑；两个任务同时改同一批文件会互相覆盖。",
    body: [
      `${what}。`,
      "",
      "两个任务同时改同一批文件会互相覆盖，所以这一轮没有开始——**你的文件没有被动过**。",
      "等它跑完再发一次，或者先去把它停掉。",
    ].join("\n"),
  };
}
