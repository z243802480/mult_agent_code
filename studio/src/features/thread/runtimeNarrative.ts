import type { AnyRecord, RunDetailPayload, StudioEvent } from "../../types";
import { asArray, asRecord, firstText, textOrFallback } from "./threadUtils";

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

export function userProgressTitle(event: AnyRecord): string {
  const title = String(event.title ?? "").trim();
  const transcriptKind = String(event.transcript_kind ?? "");
  if (title) return title;
  if (transcriptKind === "plan" || transcriptKind === "todo_update") return "Plan/Todo";
  if (transcriptKind === "tool_use") return "Tool Use";
  if (transcriptKind === "tool_result") return "Tool Result";
  if (transcriptKind === "file_change") return "File Change";
  if (transcriptKind === "verification") return "Verify";
  if (transcriptKind === "permission_request" || transcriptKind === "decision_request" || transcriptKind === "ask") return "Next step";
  if (transcriptKind === "subagent_summary") return "Background work";
  if (transcriptKind === "final" || transcriptKind === "stop") return "Result";
  return "Progress";
}

export function userProgressSummary(event: AnyRecord): string {
  const title = userProgressTitle(event);
  const summary = firstText(String(event.summary ?? ""), String(event.content_delta ?? ""), title);
  return summary;
}

