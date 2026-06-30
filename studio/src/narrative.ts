import type { StudioEvent, NarrativeStep, RunNarrative } from "./types";
import { capabilityInfo } from "./capability";
import { projectTitle } from "./titleProjection";

function eventTime(event: StudioEvent): number {
  const value = Date.parse(String(event.created_at ?? ""));
  if (Number.isFinite(value)) return value;
  const sequence = Number((event as unknown as Record<string, unknown>).sequence);
  if (Number.isFinite(sequence)) return sequence;
  return 0;
}

export function toNarrativeEvents(events: StudioEvent[]): StudioEvent[] {
  const result: StudioEvent[] = [];
  let activeModel: StudioEvent | null = null;
  for (const event of events) {
    if (event.type === "model_start") {
      activeModel = { ...event, type: "model_delta", summary: event.summary || "Waiting for model response..." };
      result.push(activeModel);
      continue;
    }
    if (event.type === "model_delta") {
      if (activeModel && activeModel.phase === event.phase && activeModel.model_provider === event.model_provider) {
        activeModel.content_delta = `${activeModel.content_delta ?? ""}${event.content_delta ?? ""}`;
        activeModel.summary = event.summary || activeModel.summary;
        activeModel.status = event.status;
        activeModel.created_at = event.created_at;
      } else {
        activeModel = { ...event };
        result.push(activeModel);
      }
      continue;
    }
    if (event.type === "model_end") {
      if (activeModel && activeModel.phase === event.phase && activeModel.model_provider === event.model_provider) {
        activeModel.status = "completed";
        activeModel.summary = event.summary || activeModel.summary;
        activeModel.telemetry = event.telemetry;
      }
      activeModel = null;
      continue;
    }
    if (event.type === "model_error") { activeModel = null; result.push(event); continue; }
    if (event.type === "agent_turn" || event.type === "tool_start" || event.type === "tool_delta" || event.type === "tool_end" || event.type === "tool_observation") {
      activeModel = null; result.push(event); continue;
    }
    activeModel = null;
    result.push(event);
  }
  return result;
}

function narrativeKind(event: StudioEvent): NarrativeStep["kind"] {
  const transcriptKind = String(event.transcript_kind ?? "");
  const data = (event.data ?? {}) as Record<string, unknown>;
  // Warm resume: the runtime re-applied prior decisions and continued the same session. Detect by
  // the stable decision payload (next_action="continue_run" is set only by ResumeCommand), never a
  // localized title. This must precede the hold check, which keys on the same progress/decision shape.
  const decisionData = (data.decision ?? {}) as Record<string, unknown>;
  if (decisionData.next_action === "continue_run") return "resume";
  // A held promotion ("changed sensitive files, waiting for your approval"). ADR-0012 prefers a
  // real Session Transcript event, so detect by transcript_kind=decision_request carrying a
  // promotion_id; the channel/event shape is kept only as a legacy fallback for older emits, and is
  // narrowed to a promotion signal so it does not swallow other progress/decision events (e.g. resume).
  if (
    (transcriptKind === "decision_request" && Boolean(data.promotion_id))
    || (event.runtime_channel === "progress" && event.runtime_event_type === "decision"
        && (Boolean(data.promotable_files) || Boolean(data.promotion_id)))
  ) {
    return "hold";
  }
  if (transcriptKind === "plan" || transcriptKind === "todo_update") return "plan";
  if (transcriptKind === "tool_use" || transcriptKind === "tool_result") return "tool";
  if (transcriptKind === "verification") return "verification";
  if (transcriptKind === "repair") return "repair";
  // The final-report event is a diagnostic artifact pointer, not the conversational closing
  // reply (ADR-0012). Keep it in the process stream so the conclusion message — which now
  // carries the agent's authored recap (CV-C) — is the step rendered as the final answer.
  if (event.runtime_event_type === "final_report") return "result";
  if (transcriptKind === "final" || transcriptKind === "stop") return "final";
  if (transcriptKind === "file_change") return "result";
  if (transcriptKind === "permission_request" || transcriptKind === "decision_request" || transcriptKind === "ask") return "tool";
  if (transcriptKind === "subagent_summary") return "subagent";
  if (event.type === "user_message") return "goal";
  if (event.type === "agent_turn" || event.runtime_event_type === "turn_start" || event.runtime_event_type === "turn_end") return "turn";
  if (event.type === "intent_route") return "thinking";
  if (event.type === "permission_request") return "tool";
  if (event.type === "tool_start" || event.type === "tool_delta" || event.type === "tool_end") return "tool";
  if (event.type === "tool_observation" || event.runtime_event_type === "tool_observation") return "observation";
  if (event.type === "model_error" || event.type === "error") return "error";
  if (event.type === "final_answer") return "final";
  if (event.phase === "plan") return "plan";
  if (event.phase === "review") return "verification";
  if (event.phase === "execute" || event.phase === "resume") return event.status === "failed" ? "repair" : "tool";
  if (event.type === "model_start" || event.type === "model_delta" || event.type === "model_end" || event.type === "reasoning_delta") return "thinking";
  if (event.type === "file_changed") return "result";
  return "thinking";
}

function narrativeLabel(kind: NarrativeStep["kind"], event: StudioEvent): string {
  if (kind === "observation") return "Observation";
  if (kind === "turn") return "Agent step";
  if (kind === "goal") return "User message";
  if (kind === "thinking" && event.phase === "plan" && event.model_provider) return "Structured generation";
  if (kind === "thinking") return "Thinking";
  if (kind === "plan") return "Plan";
  if (kind === "tool") {
    const cap = capabilityInfo(event);
    if (cap) return cap.label;
    return event.command?.length ? "Tool call" : "Action";
  }
  if (kind === "result") return event.runtime_event_type === "final_report" ? "Final report" : "File change";
  if (kind === "repair") return "Repair";
  if (kind === "verification") return "Verification";
  if (kind === "final") return "Final answer";
  if (kind === "subagent") return "Subagent";
  if (kind === "hold") return "Held for your review";
  if (kind === "resume") return "Resumed";
  return "Issue";
}

function shouldGroup(step: NarrativeStep, event: StudioEvent): boolean {
  const first = step.events[0];
  if (step.kind === "goal" || step.kind === "final" || step.kind === "error" || step.kind === "hold" || step.kind === "resume") return false;
  if (step.kind === "thinking") return first.phase === event.phase && first.model_provider === event.model_provider;
  if (step.kind === "turn") return !!first.tool_call_id && first.tool_call_id === event.tool_call_id;
  if (step.kind === "tool") {
    if (first.command?.join(" ") === event.command?.join(" ")) return true;
    return first.type.startsWith("tool_") && event.type.startsWith("tool_") && first.title === event.title;
  }
  if (step.kind === "observation") return !!first.tool_call_id && first.tool_call_id === event.tool_call_id;
  return first.phase === event.phase;
}

function mergeStatus(current: StudioEvent["status"], next: StudioEvent["status"]): StudioEvent["status"] {
  if (next === "failed" || current === "failed") return "failed";
  if (next === "waiting_user" || current === "waiting_user") return "waiting_user";
  if (next === "running" || current === "running") return "running";
  if (next === "queued" || current === "queued") return "queued";
  return "completed";
}

function countRefs(events: StudioEvent[], key: "evidence_refs" | "artifact_refs"): number {
  return events.reduce((n, e) => n + (e[key]?.length ?? 0), 0);
}

export function buildRunNarrative(events: StudioEvent[]): RunNarrative {
  const steps: NarrativeStep[] = [];
  for (const event of events) {
    const kind = narrativeKind(event);
    const label = narrativeLabel(kind, event);
    const previous = steps.at(-1);
    if (previous && previous.kind === kind && shouldGroup(previous, event)) {
      previous.events.push(event);
      previous.summary = event.summary || previous.summary;
      previous.status = mergeStatus(previous.status, event.status);
      previous.title = projectTitle(event.title) || previous.title;
      continue;
    }
    steps.push({
      id: `${kind}-${steps.length}-${event.event_id}`,
      kind,
      label,
      title: projectTitle(event.title),
      summary: event.summary || event.content_delta || event.title,
      status: event.status,
      events: [event],
      defaultOpen: kind === "final",
    });
  }
  // Only the last actively-running step expands automatically
  const lastActive = [...steps].reverse().find(
    (s) => s.status === "running" || s.status === "waiting_user"
  );
  if (lastActive) lastActive.defaultOpen = true;
  // If run has ended without a final step, open only the last failed/error step
  const hasFinal = steps.some((s) => s.kind === "final");
  const hasRunning = !!lastActive;
  if (!hasFinal && !hasRunning) {
    const lastFailed = [...steps].reverse().find(
      (s) => s.status === "failed" || s.kind === "error"
    );
    if (lastFailed) lastFailed.defaultOpen = true;
  }

  const finalEvent = [...events].reverse().find((e) => e.type === "final_answer" || e.type === "error");
  const goalEvent = events.find((e) => e.type === "user_message");
  const status = finalEvent?.type === "error" ? "failed" : finalEvent ? "completed" : "running";
  if (status !== "running") {
    for (const step of steps) {
      if (step.status === "running" || step.status === "queued") step.status = "completed";
      step.events = step.events.map((e) =>
        e.status === "running" || e.status === "queued" ? { ...e, status: "completed" } : e
      );
    }
  }
  return {
    steps,
    report: {
      status,
      headline:
        status === "running"
          ? "Agent is processing the task."
          : status === "failed"
          ? "The run encountered an issue."
          : "The run completed and produced a final result.",
      goal: (goalEvent?.summary ?? "") as string,
      modelEvents: events.filter(
        (e) => e.type.startsWith("model_") || e.type === "assistant_delta" || e.type === "reasoning_delta"
      ).length,
      toolEvents: events.filter((e) => e.type.startsWith("tool_") || e.type === "agent_turn" || e.runtime_channel === "execution_chain" || (e.command?.length ?? 0) > 0).length,
      evidenceRefs: countRefs(events, "evidence_refs"),
      artifactRefs: countRefs(events, "artifact_refs"),
      finalText: (finalEvent?.content_delta ?? finalEvent?.summary ?? "") as string,
    },
  };
}


export function firstText(...items: unknown[]): string {
  for (const item of items) {
    const text = String(item ?? "").trim();
    if (text) return text;
  }
  return "";
}

/**
 * Returns true only if the LATEST conversation turn is still active.
 * "Active" means: after the last final_answer/error event, there is a running/queued/waiting_user
 * event that has NOT been closed by a later terminal event.
 *
 * Why the terminal-reconciliation: the event log is append-only and never mutated in place
 * (see mergeEventLists). A tool/model fragment emitted with status "running" keeps that status
 * forever; its completion arrives as a SEPARATE later event (a tool_end, or a completed/failed
 * status). So a bare `.some(status === "running")` treats an already-finished streaming fragment
 * as live indefinitely — the classic stuck-"Running" badge. Instead we find the latest terminal
 * event and require an active signal strictly after it, so a running fragment followed by its
 * close reads as done. (Assumes the harness runs tools sequentially, which it does by default —
 * parallel writes are frozen; interleaved parallel tools could otherwise hide a still-open one.)
 */
export function isSessionLive(events: StudioEvent[]): boolean {
  const lastFinal = [...events].reverse().find(
    (e) => e.type === "final_answer" || e.type === "error"
  );
  const cutoff = lastFinal ? eventTime(lastFinal) : null;
  const liveEvents = cutoff
    ? events.filter((e) => eventTime(e) > cutoff)
    : events;
  if (!liveEvents.length) return false;
  const isActive = (e: StudioEvent) =>
    e.status === "running" || e.status === "queued" || e.status === "waiting_user";
  const isTerminal = (e: StudioEvent) =>
    e.status === "completed" || e.status === "failed"
    || e.type === "tool_end" || e.type === "final_answer" || e.type === "error";
  let lastTerminalTime = -Infinity;
  for (const event of liveEvents) {
    if (isTerminal(event)) lastTerminalTime = Math.max(lastTerminalTime, eventTime(event));
  }
  return liveEvents.some((event) => isActive(event) && eventTime(event) > lastTerminalTime);
}
