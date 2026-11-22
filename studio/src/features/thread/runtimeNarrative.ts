import type { AnyRecord, RunDetailPayload, StudioEvent } from "../../types";
import { asArray, asRecord, firstText, textOrFallback } from "./threadUtils";
import { INTERNAL_TITLE_PROJECTION, projectSummary } from "../../titleProjection";

export function runtimeProgress(runDetail: RunDetailPayload | null): AnyRecord {
  const direct = asRecord(runDetail?.runtime_progress);
  if (Object.keys(direct).length) return direct;
  const finalSummary = asRecord(runDetail?.final_report_summary);
  const finalProgress = asRecord(finalSummary.runtime_progress);
  if (Object.keys(finalProgress).length) return finalProgress;
  const loopSummary = asRecord(runDetail?.run_loop_summary);
  return asRecord(loopSummary.runtime_progress);
}

export function contextSectionLabel(value: string): string {
  const normalized = value.toLowerCase();
  if (normalized.includes("message") || normalized.includes("conversation")) return "消息";
  if (normalized.includes("tool") || normalized.includes("shell")) return "工具输出";
  if (normalized.includes("skill")) return "技能";
  if (normalized.includes("system")) return "系统";
  if (normalized.includes("prompt") || normalized.includes("instruction")) return "项目规则";
  if (normalized.includes("memory") || normalized.includes("durable")) return "记忆";
  if (normalized.includes("file") || normalized.includes("context")) return "文件";
  return value.replace(/[_-]+/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

export function eventStatus(value: unknown): StudioEvent["status"] {
  const text = String(value ?? "").toLowerCase();
  if (
    text === "queued" ||
    text === "running" ||
    text === "waiting_user" ||
    text === "completed" ||
    text === "failed" ||
    text === "blocked"
  )
    return text;
  if (/fail|error/.test(text)) return "failed";
  if (/block/.test(text)) return "blocked";
  if (/wait|ask|decision|permission/.test(text)) return "waiting_user";
  if (/run|progress|active/.test(text)) return "running";
  return "completed";
}

export function goalTitle(runDetail: RunDetailPayload | null): string {
  const goal = asRecord(runDetail?.goal_spec);
  const run = asRecord(runDetail?.run);
  return textOrFallback(
    goal.normalized_goal ?? goal.original_goal ?? run.goal ?? run.summary,
    "还没有选择目标",
  );
}

export function actionLabel(value: string): string {
  const normalized = value
    .trim()
    .toLowerCase()
    .replace(/^asteria\s+/, "");
  if (normalized.startsWith("model-check")) return "检查连接";
  if (normalized.startsWith("review")) return "查看";
  if (normalized.startsWith("accept")) return "接受";
  if (
    normalized.startsWith("resume") ||
    normalized.startsWith("continue") ||
    normalized.startsWith("run")
  )
    return "继续";
  if (normalized.startsWith("decide")) return "决定";
  if (normalized.startsWith("debug") || normalized.startsWith("repair")) return "调试";
  return "继续";
}

/**
 * Honest completion qualifier for the thread conclusion. `/run` reports a lifecycle status of
 * "completed" but does NOT inline-run review, so review_status is typically "unknown" and small
 * changes record no verification. Rather than let "completed" read as "verified", surface a plain
 * "done but not yet verified" line so the user knows to run Review. Pure projection of data already
 * in runDetail (final_report_summary) — no runtime change.
 */
/**
 * Latest executable-verification verdict recorded by the /run loop, read from its graded
 * `verification` progress events in runDetail.user_progress (same source the thread renders).
 * Returns "pass"/"fail" for a real graded verdict, "unrun" when the loop ran but nothing
 * executable proved correctness, and null when the loop emitted no graded verdict at all.
 *
 * Discriminator: only the /run loop's own verdict carries `telemetry.correctness_status`. Generic
 * review/validation steps reuse transcript_kind="verification" (e.g. "Validation conclusion") but
 * never set it — and one of them is typically emitted AFTER the verdict. We must skip those, else a
 * later generic step shadows the real verdict and a passing run is nagged as unverified. Pure
 * projection — no runtime change.
 */
export function latestCorrectnessVerdict(
  runDetail: RunDetailPayload | null,
): "pass" | "fail" | "unrun" | null {
  const events = (runDetail?.user_progress ?? []) as AnyRecord[];
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const event = events[index];
    if (String(event.transcript_kind ?? "") !== "verification") continue;
    const status = String(asRecord(event.telemetry).correctness_status ?? "").toLowerCase();
    if (!status) continue; // generic review-phase step, not the graded verdict — keep scanning
    if (status === "pass") return "pass";
    if (status === "fail" || status === "partial") return "fail";
    return "unrun";
  }
  return null;
}

/**
 * Turn-scoped correctness verdict: same discriminator as {@link latestCorrectnessVerdict}, but read
 * only from THIS turn's own step events instead of the run-global progress log. This is the honesty
 * gate behind the green "验证通过" badge — the run-level verdict alone is dishonest when the latest
 * turn did no verification of its own (e.g. a resumed/replayed turn whose stated goal differs from
 * the work that was actually verified): it would inherit an earlier turn's pass and claim the new,
 * unverified request "passed". Requiring the verdict to live in this turn keeps "verified" bound to
 * work this turn actually produced. Returns null when this turn recorded no graded verdict.
 */
export function turnCorrectnessVerdict(
  steps: { events: StudioEvent[] }[],
): "pass" | "fail" | "unrun" | null {
  const events = steps.flatMap((step) => step.events);
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const event = events[index];
    if (String(event.transcript_kind ?? "") !== "verification") continue;
    const status = String(asRecord(event.telemetry).correctness_status ?? "").toLowerCase();
    if (!status) continue; // generic review step, not the graded verdict — keep scanning
    if (status === "pass") return "pass";
    if (status === "fail" || status === "partial") return "fail";
    return "unrun";
  }
  return null;
}

// Whether to show the green "验证通过" badge on a turn. The signal is this turn's OWN verified verdict
// (turnCorrectnessVerdict reads only this turn's steps, so it can never inherit another turn's pass) —
// the same discriminator the "not yet verified" nag (runVerificationHint) already uses, so the badge
// and the nag are symmetric: a turn that verified green shows the badge and no nag; a turn that did no
// verification of its own shows neither. This is per-turn by design, so a senior user reviewing a
// multi-turn run sees which turns actually verified, not only the latest.
//
// It intentionally does NOT also require the run-GLOBAL verdict. That extra gate was redundant for
// honesty (the turn-scoped verdict already prevents inheritance) and produced a false negative on a
// follow-up turn that genuinely verified but whose run-detail linkage lagged: the nag was suppressed
// (turn-scoped pass) yet the badge stayed hidden (run-global not aligned), leaving a verified turn with
// NEITHER signal — the exact "completed ≠ verified" gap the badge exists to close (live is_even/is_odd
// test, 2026-07-15). The last turn is still suppressed while it is actively streaming.
export function turnVerifiedBadge(params: {
  isLast: boolean;
  isRunning: boolean;
  hasResponse: boolean;
  turnVerdict: "pass" | "fail" | "unrun" | null;
}): boolean {
  const { isLast, isRunning, hasResponse, turnVerdict } = params;
  if (!hasResponse) return false;
  if (isLast && isRunning) return false;
  return turnVerdict === "pass";
}

export function runVerificationHint(
  runDetail: RunDetailPayload | null,
  steps: { events: StudioEvent[] }[] = [],
): string {
  const candidateSummary = asRecord(runDetail?.final_report_summary);
  if (!runDetail?.ok) return "";
  const finalSummary =
    candidateSummary.run_id && candidateSummary.run_id !== runDetail.run_id ? {} : candidateSummary;
  const run = asRecord(runDetail?.run);
  const runStatus = String(run.status ?? finalSummary.run_status ?? "").toLowerCase();
  if (/running|paused/.test(runStatus)) return "";
  // Current native review takes precedence over an earlier delivery summary. Bind it to
  // this session, and never substitute the executable verdict for a requirement judgment.
  const report = asRecord(runDetail.eval_report);
  const ownReport = report.run_id === runDetail.run_id ? report : {};
  const stored = asRecord(finalSummary.review);
  const ownStored = stored.run_id === runDetail.run_id ? stored : {};
  const review = Object.keys(ownReport).length ? asRecord(ownReport.overall) : ownStored;
  const goal = Object.keys(ownReport).length ? asRecord(ownReport.goal_eval) : ownStored;
  const reviewStatus = String(review.status ?? finalSummary.review_status ?? "").toLowerCase();
  const freshness = asRecord(runDetail.review_freshness);
  if (freshness.status && freshness.status !== "current") {
    const history = reviewStatus === "pass" ? "历史评审通过" : "历史评审结论已保留";
    return `${history}，当前${freshness.status === "changed" ? "输入已变化，评审已过期" : "评审新鲜性无法核实"}。请重新评审当前输入；执行检查结果不代替当前评审。`;
  }
  const verdict = turnCorrectnessVerdict(steps);
  if (["pass", "partial", "fail"].includes(reviewStatus)) {
    const fraction = (value: unknown): value is number =>
      typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 1;
    const score = fraction(review.score) ? `评分 ${review.score.toFixed(2)}` : "评分未评定";
    const coverage = fraction(goal.requirement_coverage)
      ? `模型评估覆盖率 ${Math.round(goal.requirement_coverage * 100)}%（非运行时独立核实）`
      : "原要求覆盖率未评定；执行检查结果不代表全面覆盖";
    return (
      [
        reviewStatus === "pass" ? "评审通过" : "评审未通过",
        score,
        coverage,
        String(review.reason ?? "").trim(),
        verdict === "fail" ? "本轮执行检查未通过，请核对检查范围" : "",
      ]
        .filter(Boolean)
        .join("。") + "。"
    );
  }
  if (verdict === "fail") {
    return "执行检查未通过——记录的测试/检查失败了。接受前请先查看。";
  }
  if (!Object.keys(finalSummary).length && !Object.keys(ownReport).length) return "";
  return verdict === "pass"
    ? "执行检查已通过，尚未评审原始要求的覆盖情况。"
    : "尚未评审原始要求；执行检查结果也需核对。";
}

export function reviewNeedsRefresh(runDetail: RunDetailPayload | null): boolean {
  return Boolean(
    asRecord(runDetail?.eval_report).overall &&
    asRecord(runDetail?.review_freshness).status &&
    asRecord(runDetail?.review_freshness).status !== "current",
  );
}

export function latestActiveEvent(events: StudioEvent[]): StudioEvent | null {
  return (
    [...events]
      .reverse()
      .find(
        (event) =>
          (!event.display_level || event.display_level === "main") &&
          (event.status === "running" ||
            event.status === "waiting_user" ||
            event.type === "final_answer" ||
            event.type === "error"),
      ) ?? null
  );
}

export function runtimeSessionEvents(runDetail: RunDetailPayload | null): StudioEvent[] {
  if (!runDetail?.ok) return [];
  const runId = String(runDetail.run_id ?? "");
  const run = asRecord(runDetail.run);
  const startedAt = String(run.started_at ?? new Date().toISOString());
  const goalText = goalTitle(runDetail);
  const userProgress = ((runDetail.user_progress ?? []) as AnyRecord[])
    .map((event, index) => {
      if (event.display_level && event.display_level !== "main") return null;
      if (!event.transcript_kind) return null;
      return {
        event_id: String(event.event_id ?? `runtime-user-progress-${runId}-${index}`),
        session_id: String(event.session_id ?? "runtime-session"),
        type: String(userProgressType(event)) as StudioEvent["type"],
        status: eventStatus(event.status),
        title: userProgressTitle(event),
        summary: userProgressSummary(event),
        // Preserve the runtime's real content_delta (e.g. the CV-C authored recap) when present;
        // fall back to the summary projection only when there is no distinct conversational text.
        content_delta: String(event.content_delta ?? "") || userProgressSummary(event),
        command: Array.isArray(event.command) ? event.command.map(String) : undefined,
        data: asRecord(event.data),
        actions: asArray(event.actions) as StudioEvent["actions"],
        artifact_refs: asArray(event.artifact_refs).map(String),
        evidence_refs: asArray(event.evidence_refs).map(String),
        runtime_channel: String(event.channel ?? "progress"),
        runtime_event_type: String(event.event_type ?? "message"),
        transcript_kind: event.transcript_kind ? String(event.transcript_kind) : undefined,
        ui_intent: event.ui_intent ? String(event.ui_intent) : undefined,
        job_id: event.job_id ? String(event.job_id) : undefined,
        source: "runtime_user_progress",
        run_id: runId,
        phase: String(event.phase ?? "execute"),
        display_level: "main",
        created_at: String(event.created_at ?? startedAt),
      } satisfies StudioEvent;
    })
    .filter(Boolean) as StudioEvent[];
  if (!userProgress.length) return [];

  const events: StudioEvent[] = [
    {
      event_id: `runtime-goal-${runId || "latest"}`,
      session_id: "runtime-session",
      type: "user_message",
      status: "completed",
      title: "目标",
      summary: goalText,
      content_delta: goalText,
      run_id: runId,
      phase: "understand",
      display_level: "main",
      created_at: startedAt,
    },
  ];

  events.push(...userProgress);
  return events;
}

export function userProgressType(event: AnyRecord): StudioEvent["type"] {
  const transcriptKind = String(event.transcript_kind ?? "");
  if (transcriptKind === "final" || transcriptKind === "stop") return "final_answer";
  if (transcriptKind === "tool_use") return "tool_start";
  if (transcriptKind === "tool_result") return "tool_end";
  if (transcriptKind === "file_change") return "file_changed";
  if (transcriptKind === "verification") return "tool_observation";
  if (transcriptKind === "permission_request") return "permission_request";
  if (transcriptKind === "decision_request" || transcriptKind === "ask") return "assistant_delta";
  return "assistant_delta";
}

// Human-readable action titles projected from the runtime's transcript_kind.
// We project both the transcript_kind fallback AND any internal/legacy title
// literals the runtime may emit, so the main thread never shows process jargon
// like "Tool Use"/"Tool Result"/"Verify"/"Background work".
const TRANSCRIPT_KIND_TITLES: Record<string, string> = {
  plan: "规划中",
  todo_update: "规划中",
  tool_use: "执行中",
  tool_result: "结果",
  file_change: "文件改动",
  verification: "核对结果",
  permission_request: "下一步",
  decision_request: "下一步",
  ask: "下一步",
  subagent_summary: "后台执行中",
  final: "结果",
  stop: "结果",
};

// Internal/legacy title literals → human action titles live in the shared title-projection module
// (single source, also used by buildRunNarrative for NarrativeStep titles).

export function userProgressTitle(event: AnyRecord): string {
  const title = String(event.title ?? "").trim();
  const transcriptKind = String(event.transcript_kind ?? "");
  const phase = String(event.phase ?? "").trim();
  // Review-phase steps read as "Checking the work" regardless of kind.
  if (phase === "review") return "核对结果";
  if (title) {
    // Project known internal/legacy literals; unknown titles pass through.
    return INTERNAL_TITLE_PROJECTION[title] ?? title;
  }
  return TRANSCRIPT_KIND_TITLES[transcriptKind] ?? "进度";
}

export function userProgressSummary(event: AnyRecord): string {
  const title = userProgressTitle(event);
  const summary = firstText(String(event.summary ?? ""), String(event.content_delta ?? ""), title);
  return projectSummary(summary);
}
