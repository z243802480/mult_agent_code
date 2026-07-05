import type { AnyRecord, RunDetailPayload, StudioEvent } from "../../types";
import { asArray, asRecord, firstText, textOrFallback } from "./threadUtils";
import { INTERNAL_TITLE_PROJECTION } from "../../titleProjection";

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
  if (normalized.includes("message") || normalized.includes("conversation")) return "Messages";
  if (normalized.includes("tool") || normalized.includes("shell")) return "Tool output";
  if (normalized.includes("skill")) return "Skills";
  if (normalized.includes("system")) return "System";
  if (normalized.includes("prompt") || normalized.includes("instruction")) return "Project rules";
  if (normalized.includes("memory") || normalized.includes("durable")) return "Memory";
  if (normalized.includes("file") || normalized.includes("context")) return "Files";
  return value.replace(/[_-]+/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

export function eventStatus(value: unknown): StudioEvent["status"] {
  const text = String(value ?? "").toLowerCase();
  if (text === "queued" || text === "running" || text === "waiting_user" || text === "completed" || text === "failed" || text === "blocked") return text;
  if (/fail|error/.test(text)) return "failed";
  if (/block/.test(text)) return "blocked";
  if (/wait|ask|decision|permission/.test(text)) return "waiting_user";
  if (/run|progress|active/.test(text)) return "running";
  return "completed";
}

export function goalTitle(runDetail: RunDetailPayload | null): string {
  const goal = asRecord(runDetail?.goal_spec);
  const run = asRecord(runDetail?.run);
  return textOrFallback(goal.normalized_goal ?? goal.original_goal ?? run.goal ?? run.summary, "No goal selected yet");
}

export function actionLabel(value: string): string {
  const normalized = value.trim().toLowerCase().replace(/^asteria\s+/, "");
  if (normalized.startsWith("model-check")) return "Check connection";
  if (normalized.startsWith("review")) return "Review";
  if (normalized.startsWith("accept")) return "Accept";
  if (normalized.startsWith("resume") || normalized.startsWith("continue") || normalized.startsWith("run")) return "Continue";
  if (normalized.startsWith("decide")) return "Decide";
  if (normalized.startsWith("debug") || normalized.startsWith("repair")) return "Debug";
  return "Continue";
}

/**
 * Honest completion qualifier for the thread conclusion. `/run` reports a lifecycle status of
 * "completed" but does NOT inline-run review, so review_status is typically "unknown" and small
 * changes record no verification. Rather than let "completed" read as "verified", surface a plain
 * "done but not yet verified" line so the user knows to run Review. Pure projection of data already
 * in runDetail (final_report_summary) — no runtime change.
 */
/**
 * Latest executable-verification verdict recorded by the /run loop, read from the `verification`
 * progress events in runDetail.user_progress (same source the thread renders). Returns "pass"/"fail"
 * for a real graded verdict, "unrun" when a verification event says nothing executable ran, and null
 * when no verification event exists at all. Pure projection — no runtime change.
 */
export function latestCorrectnessVerdict(
  runDetail: RunDetailPayload | null,
): "pass" | "fail" | "unrun" | null {
  const events = (runDetail?.user_progress ?? []) as AnyRecord[];
  for (let index = events.length - 1; index >= 0; index -= 1) {
    if (String(events[index].transcript_kind ?? "") !== "verification") continue;
    const correctness = asRecord(asRecord(events[index].data).correctness);
    if (!Object.keys(correctness).length) return "unrun";
    const status = String(correctness.status ?? "").toLowerCase();
    if (status === "pass") return "pass";
    if (status === "fail" || status === "partial") return "fail";
    return "unrun";
  }
  return null;
}

export function runVerificationHint(runDetail: RunDetailPayload | null): string {
  const finalSummary = asRecord(runDetail?.final_report_summary);
  if (!Object.keys(finalSummary).length) return "";
  const run = asRecord(runDetail?.run);
  const runStatus = String(run.status ?? finalSummary.run_status ?? "").toLowerCase();
  if (runStatus && /fail|block|error|running|paused/.test(runStatus)) return "";
  // The /run loop now emits a real executable-verification verdict (run_tests/run_command exit
  // codes) as a `verification` progress event. When it passed, the work IS verified — don't nag the
  // user to run Review. When it explicitly failed, say so. Only fall through to the review-status
  // heuristic when no executable verdict was recorded (nothing runnable ran).
  const verdict = latestCorrectnessVerdict(runDetail);
  if (verdict === "pass") return "";
  if (verdict === "fail") {
    return "Verification did not pass — the recorded tests/checks failed. Review before accepting.";
  }
  const reviewStatus = String(finalSummary.review_status ?? "").toLowerCase();
  const completion = String(finalSummary.completion ?? finalSummary.completion_state ?? "").toLowerCase();
  if (reviewStatus === "pass" || /verified|accepted/.test(completion)) return "";
  if (reviewStatus === "unknown" || reviewStatus === "" || /needs_review|unverified|implemented/.test(completion)) {
    return "Changes are done but not yet verified. Run Review to check them.";
  }
  return "";
}

export function latestActiveEvent(events: StudioEvent[]): StudioEvent | null {
  return [...events]
    .reverse()
    .find((event) =>
      (!event.display_level || event.display_level === "main")
      && (event.status === "running" || event.status === "waiting_user" || event.type === "final_answer" || event.type === "error")
    ) ?? null;
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
      title: "Goal",
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
  plan: "Planning",
  todo_update: "Planning",
  tool_use: "Working",
  tool_result: "Result",
  file_change: "File Change",
  verification: "Checking the work",
  permission_request: "Next step",
  decision_request: "Next step",
  ask: "Next step",
  subagent_summary: "Working in the background",
  final: "Result",
  stop: "Result",
};

// Internal/legacy title literals → human action titles live in the shared title-projection module
// (single source, also used by buildRunNarrative for NarrativeStep titles).

export function userProgressTitle(event: AnyRecord): string {
  const title = String(event.title ?? "").trim();
  const transcriptKind = String(event.transcript_kind ?? "");
  const phase = String(event.phase ?? "").trim();
  // Review-phase steps read as "Checking the work" regardless of kind.
  if (phase === "review") return "Checking the work";
  if (title) {
    // Project known internal/legacy literals; unknown titles pass through.
    return INTERNAL_TITLE_PROJECTION[title] ?? title;
  }
  return TRANSCRIPT_KIND_TITLES[transcriptKind] ?? "Progress";
}

export function userProgressSummary(event: AnyRecord): string {
  const title = userProgressTitle(event);
  const summary = firstText(String(event.summary ?? ""), String(event.content_delta ?? ""), title);
  return summary;
}

