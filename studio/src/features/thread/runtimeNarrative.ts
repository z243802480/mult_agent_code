import type { AnyRecord, RunDetailPayload, StudioEvent } from "../../types";
import { asArray, asRecord, firstText, stripBackendWording, textOrFallback } from "./threadUtils";

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

export function runtimeProgressEvent(
  runId: string,
  index: number,
  title: string,
  summary: string,
  phase: StudioEvent["phase"],
  status: StudioEvent["status"],
  data: AnyRecord,
  startedAt: string
): StudioEvent | null {
  const copy = userFacingRuntimeCopy(title, summary, data);
  const text = firstText(copy.summary, copy.title);
  if (!text) return null;
  return {
    event_id: `runtime-progress-${runId || "latest"}-${index}`,
    session_id: "runtime-session",
    type: phase === "review" ? "tool_observation" : "assistant_delta",
    status,
    title: copy.title,
    summary: text,
    content_delta: text,
    data,
    evidence_refs: asArray(data.evidence_refs).map(String),
    source: "runtime_progress",
    runtime_channel: "progress",
    runtime_event_type: String(data.kind ?? "summary"),
    transcript_kind: data.transcript_kind ? String(data.transcript_kind) : undefined,
    ui_intent: data.ui_intent ? String(data.ui_intent) : undefined,
    run_id: runId,
    phase,
    display_level: "main",
    created_at: startedAt,
  };
}

export function synthesizedRuntimeProgressEvents(runDetail: RunDetailPayload | null, startedAt: string): StudioEvent[] {
  const progress = runtimeProgress(runDetail);
  const runId = String(runDetail?.run_id ?? "");
  const plan = asRecord(progress.plan);
  const todo = asRecord(progress.todo);
  const currentTodo = asRecord(todo.current);
  const tool = asRecord(progress.tool);
  const toolUse = asRecord(progress.tool_use);
  const verify = asRecord(progress.verify);
  const verification = asRecord(progress.verification);
  const loop = asRecord(progress.loop);
  const workerSummary = asRecord(progress.worker_summary);
  const exitReason = firstText(String(loop.exit_reason ?? ""), String(progress.exit_reason ?? ""));
  return [
    runtimeProgressEvent(
      runId,
      1,
      "Plan/Todo",
      firstText(String(plan.summary ?? ""), String(plan.title ?? ""), String(todo.summary ?? ""), String(currentTodo.content ?? ""), String(progress.current_step ?? "")),
      "plan",
      eventStatus(plan.status ?? currentTodo.status ?? todo.status ?? progress.workflow_state),
      { kind: "plan", transcript_kind: plan.transcript_kind ?? "plan", ...plan, ...todo },
      startedAt
    ),
    runtimeProgressEvent(
      runId,
      2,
      "Tool Use",
      firstText(String(tool.summary ?? ""), String(toolUse.summary ?? ""), String(progress.current_step ?? "")),
      "execute",
      eventStatus(tool.status ?? toolUse.status ?? progress.workflow_state),
      { kind: "tool_use", transcript_kind: tool.transcript_kind ?? "tool_use", ...tool, ...toolUse },
      startedAt
    ),
    runtimeProgressEvent(
      runId,
      3,
      "Verify",
      firstText(String(verify.summary ?? ""), String(verification.summary ?? ""), String(verification.status ?? "")),
      "review",
      eventStatus(verify.status ?? verification.status ?? progress.workflow_state),
      { kind: "verification", transcript_kind: verify.transcript_kind ?? "verification", ...verify, ...verification },
      startedAt
    ),
    runtimeProgressEvent(
      runId,
      4,
      "Background work",
      firstText(String(workerSummary.summary ?? ""), String(workerSummary.status ?? "")),
      "execute",
      eventStatus(workerSummary.status ?? progress.workflow_state),
      { kind: "worker_summary", ...workerSummary },
      startedAt
    ),
    runtimeProgressEvent(
      runId,
      5,
      "Next step",
      firstText(String(progress.current_blocker ?? ""), exitReason, String(progress.next_step ?? ""), String(progress.next_command ?? "")),
      exitReason || progress.current_blocker ? "next" : "result",
      eventStatus(progress.current_blocker ? "blocked" : exitReason || progress.workflow_state),
      { kind: "loop_exit", exit_reason: exitReason, next_command: progress.next_command, blocker: progress.current_blocker },
      startedAt
    ),
  ].filter(Boolean) as StudioEvent[];
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

export function userFacingRuntimeCopy(title: string, summary: string, data: AnyRecord): { title: string; summary: string } {
  if (isProviderTransientCopy(title, summary, data)) {
    return {
      title: "Model connection interrupted",
      summary: "The model connection failed before Asteria received an executable step. No file changes were made for this step; Asteria can check the connection and retry when it recovers.",
    };
  }
  return {
    title: stripBackendWording(title),
    summary: stripBackendWording(summary),
  };
}

export function isProviderTransientCopy(title: string, summary: string, data: AnyRecord): boolean {
  const text = `${title}\n${summary}\n${JSON.stringify(data)}`.toLowerCase();
  return (
    text.includes("provider route blocked")
    || text.includes("provider_transient")
    || text.includes("provider_network")
    || text.includes("provider_timeout")
    || text.includes("provider_rate_limited")
    || text.includes("provider_server_error")
    || text.includes("model-check")
  );
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
      return {
        event_id: String(event.event_id ?? `runtime-user-progress-${runId}-${index}`),
        session_id: String(event.session_id ?? "runtime-session"),
        type: String(userProgressType(event)) as StudioEvent["type"],
        status: eventStatus(event.status),
        title: userProgressTitle(event),
        summary: userProgressSummary(event),
        content_delta: userProgressSummary(event),
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

  events.push(...(userProgress.length ? userProgress : synthesizedRuntimeProgressEvents(runDetail, startedAt)));

  const hasMainFinalInProgress = ((runDetail.user_progress ?? []) as AnyRecord[]).some(
    (event) => event.display_level !== "inspector"
      && (event.transcript_kind === "final" || event.transcript_kind === "stop")
  );
  const finalSummary = asRecord(runDetail.final_report_summary);
  const progress = runtimeProgress(runDetail);
  const progressFinal = asRecord(progress.final);
  const finalText = firstText(
    String(progressFinal.summary ?? ""),
    String(progressFinal.content_delta ?? ""),
    String(progress.result_summary ?? ""),
    String(progress.summary ?? ""),
    String(finalSummary.summary ?? ""),
    String(run.summary ?? ""),
    String(progress.workflow_state ?? finalSummary.workflow_state ?? "")
  );
  if (finalText && !hasMainFinalInProgress) {
    events.push({
      event_id: `runtime-final-${runId || "latest"}`,
      session_id: "runtime-session",
      type: "final_answer",
      status: String(run.status ?? "").toLowerCase() === "blocked" ? "blocked" : "completed",
      title: "Result",
      summary: finalText,
      content_delta: finalText,
      run_id: runId,
      phase: "result",
      display_level: "main",
      created_at: String(run.ended_at ?? new Date().toISOString()),
    });
  }
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
  const channel = String(event.channel ?? "");
  const eventType = String(event.event_type ?? "");
  const phase = String(event.phase ?? "");
  if (channel === "conclusion" && phase === "result") return "final_answer";
  if (channel === "execution_chain" && (eventType === "turn_start" || eventType === "turn_end")) return "agent_turn";
  if (channel === "execution_chain" && eventType === "tool_observation") return "tool_observation";
  if (channel === "tool") return eventType === "tool_output" ? "tool_end" : "tool_start";
  if (channel === "file") return "file_changed";
  if (channel === "model") return eventType === "error" ? "model_error" : eventType === "end" ? "model_end" : eventType === "start" ? "model_start" : "model_delta";
  return "assistant_delta";
}

export function userProgressTitle(event: AnyRecord): string {
  const title = String(event.title ?? "").trim();
  const transcriptKind = String(event.transcript_kind ?? "");
  if (title) return transcriptKind ? title : userFacingRuntimeCopy(title, String(event.summary ?? ""), asRecord(event.data)).title;
  if (transcriptKind === "plan" || transcriptKind === "todo_update") return "Plan/Todo";
  if (transcriptKind === "tool_use") return "Tool Use";
  if (transcriptKind === "tool_result") return "Tool Result";
  if (transcriptKind === "file_change") return "File Change";
  if (transcriptKind === "verification") return "Verify";
  if (transcriptKind === "permission_request" || transcriptKind === "decision_request" || transcriptKind === "ask") return "Next step";
  if (transcriptKind === "subagent_summary") return "Background work";
  if (transcriptKind === "final" || transcriptKind === "stop") return "Result";
  const channel = String(event.channel ?? "");
  const phase = String(event.phase ?? "");
  if (channel === "execution_chain") return "Agent step";
  if (channel === "tool") return "Tool Use";
  if (phase === "review") return "Verify";
  if (phase === "plan") return "Plan/Todo";
  if (phase === "next") return "Next step";
  return "Progress";
}

export function userProgressSummary(event: AnyRecord): string {
  const title = userProgressTitle(event);
  const summary = firstText(String(event.summary ?? ""), String(event.content_delta ?? ""), title);
  if (event.transcript_kind) return summary;
  return userFacingRuntimeCopy(title, summary, asRecord(event.data)).summary;
}

