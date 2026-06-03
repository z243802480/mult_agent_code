import React, { useMemo, useEffect, useRef, useState } from "react";
import { CheckCircle2, ChevronDown, ChevronRight, CircleDot, FileText, Loader2, PlayCircle, Terminal, Wrench } from "lucide-react";
import type { AnyRecord, StudioEvent, NarrativeStep as NarrativeStepType, OverviewPayload, RunDetailPayload } from "../types";
import { NarrativeStep } from "./NarrativeStep";
import { PermissionCard } from "./PermissionCard";
import { toNarrativeEvents, buildRunNarrative } from "../narrative";

const EXAMPLE_PROMPTS = [
  "Plan a 3-day Qingdao trip",
  "Add a --version test to this project",
  "Analyze the latest failure log and identify the root cause",
  "Turn these notes into a one-page PRD",
];

const PHASE_LABELS: Record<string, string> = {
  thinking: "Thinking",
  plan: "Planning",
  tool: "Using tools",
  result: "Preparing result",
  verification: "Verifying",
  repair: "Repairing",
  error: "Error",
};

function formatEventTime(value: unknown): string {
  const date = new Date(String(value ?? ""));
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString();
}

function splitIntoTurns(steps: NarrativeStepType[]): NarrativeStepType[][] {
  const turns: NarrativeStepType[][] = [];
  let current: NarrativeStepType[] | null = null;
  for (const step of steps) {
    if (step.kind === "goal") {
      if (current) turns.push(current);
      current = [step];
    } else if (current) {
      current.push(step);
    }
  }
  if (current) turns.push(current);
  return turns;
}

function middleSummary(steps: NarrativeStepType[]): string {
  const commandCount = steps.reduce(
    (count, step) => count + step.events.filter((event) => Array.isArray(event.command) && event.command.length > 0).length,
    0
  );
  const fileCount = extractFileChanges(steps).length;
  const hasVerification = steps.some((step) =>
    step.kind === "verification" || step.events.some((event) => event.phase === "review")
  );
  const hasRepair = steps.some((step) => step.kind === "repair");
  const hasError = steps.some((step) => step.kind === "error" || step.status === "failed" || step.status === "blocked");
  const hasPlan = steps.some((step) => step.kind === "plan");
  const parts: string[] = [];
  if (commandCount) parts.push(`Ran ${commandCount} command${commandCount === 1 ? "" : "s"}`);
  if (fileCount) parts.push(`Updated ${fileCount} file${fileCount === 1 ? "" : "s"}`);
  if (hasVerification) parts.push("Verified");
  if (hasRepair) parts.push("Repaired");
  if (hasError) parts.push("Needs attention");
  if (!parts.length && hasPlan) parts.push("Planned");
  if (!parts.length) parts.push(`${steps.length} process update${steps.length === 1 ? "" : "s"}`);
  return parts.slice(0, 3).join(" / ");
}

function hasFinalAnswerForPhase(steps: NarrativeStepType[], phase?: string): boolean {
  return steps.some((step) =>
    step.kind === "final"
    && step.events.some((event) =>
      event.type === "final_answer" && (!phase || event.phase === phase)
    )
  );
}

function isModelThinkingStep(step: NarrativeStepType, phase?: string): boolean {
  return step.kind === "thinking"
    && step.events.some((event) =>
      event.type.startsWith("model_") && (!phase || event.phase === phase)
    );
}

function extractFileChanges(steps: NarrativeStepType[]): AnyRecord[] {
  const seen = new Set<string>();
  const result: AnyRecord[] = [];
  for (const s of steps.filter((s) => s.kind === "result")) {
    for (const ev of s.events) {
      for (const fc of (ev.file_changes ?? []) as AnyRecord[]) {
        const key = String(fc.path ?? fc.file ?? JSON.stringify(fc));
        if (!seen.has(key)) { seen.add(key); result.push(fc); }
      }
    }
  }
  return result;
}

function asRecord(value: unknown): AnyRecord {
  return value && typeof value === "object" && !Array.isArray(value) ? value as AnyRecord : {};
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function firstText(...items: string[]): string {
  return items.find((item) => item.trim()) ?? "";
}

function toneFor(value: string): string {
  if (/ready|completed|succeeded|pass|healthy|none/i.test(value)) return "good";
  if (/blocked|failed|missing|error|needs/i.test(value)) return "bad";
  return "warn";
}

function runtimeProgress(runDetail: RunDetailPayload | null): AnyRecord {
  const direct = asRecord(runDetail?.runtime_progress);
  if (Object.keys(direct).length) return direct;
  const finalSummary = asRecord(runDetail?.final_report_summary);
  const finalProgress = asRecord(finalSummary.runtime_progress);
  if (Object.keys(finalProgress).length) return finalProgress;
  const loopSummary = asRecord(runDetail?.run_loop_summary);
  return asRecord(loopSummary.runtime_progress);
}

function formatUsage(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return "0";
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}k`;
  return String(Math.round(value));
}

function percent(value: number): string {
  if (!Number.isFinite(value)) return "0%";
  return `${Math.round(Math.max(0, Math.min(1, value)) * 100)}%`;
}

function contextWindowSummary(runDetail: RunDetailPayload | null): {
  ratio: number;
  used: number;
  capacity: number;
  status: string;
  sections: { id: string; label: string; value: number; ratio: number }[];
} | null {
  const cost = asRecord(runDetail?.cost_report);
  const rawUsed = Number(cost.latest_context_estimated_tokens ?? cost.max_context_estimated_tokens ?? 0);
  const rawCapacity = Number(cost.context_window_tokens ?? 0);
  const rawRatio = Number(cost.context_window_ratio ?? (rawCapacity > 0 ? rawUsed / rawCapacity : 0));
  const rawSections = asRecord(cost.latest_context_sections ?? cost.max_context_sections);
  const sectionEntries = Object.entries(rawSections)
    .map(([id, value]) => ({ id, label: contextSectionLabel(id), value: Number(value ?? 0) }))
    .filter((item) => Number.isFinite(item.value) && item.value > 0)
    .sort((a, b) => b.value - a.value);
  const total = sectionEntries.reduce((sum, item) => sum + item.value, 0);
  const used = rawUsed || total;
  const ratio = Number.isFinite(rawRatio) ? rawRatio : 0;
  const capacity = rawCapacity || (used > 0 && ratio > 0 ? Math.round(used / ratio) : 0);
  const sections = sectionEntries.map((item) => ({
    ...item,
    ratio: total > 0 ? item.value / total : 0,
  }));
  if (!used && !capacity && !sections.length) return null;
  return {
    ratio: Number.isFinite(ratio) ? ratio : 0,
    used: Number.isFinite(used) ? used : 0,
    capacity: Number.isFinite(capacity) ? capacity : 0,
    status: String(cost.context_pressure_status ?? cost.status ?? ""),
    sections,
  };
}

function contextSectionLabel(value: string): string {
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

function eventStatus(value: unknown): StudioEvent["status"] {
  const text = String(value ?? "").toLowerCase();
  if (text === "queued" || text === "running" || text === "waiting_user" || text === "completed" || text === "failed" || text === "blocked") return text;
  if (/fail|error/.test(text)) return "failed";
  if (/block/.test(text)) return "blocked";
  if (/wait|ask|decision|permission/.test(text)) return "waiting_user";
  if (/run|progress|active/.test(text)) return "running";
  return "completed";
}

function runtimeProgressEvent(
  runId: string,
  index: number,
  title: string,
  summary: string,
  phase: StudioEvent["phase"],
  status: StudioEvent["status"],
  data: AnyRecord,
  startedAt: string
): StudioEvent | null {
  const text = firstText(summary, title);
  if (!text) return null;
  return {
    event_id: `runtime-progress-${runId || "latest"}-${index}`,
    session_id: "runtime-session",
    type: phase === "review" ? "tool_observation" : "assistant_delta",
    status,
    title,
    summary: text,
    content_delta: text,
    data,
    evidence_refs: asArray(data.evidence_refs).map(String),
    source: "runtime_progress",
    runtime_channel: "progress",
    runtime_event_type: String(data.kind ?? "summary"),
    run_id: runId,
    phase,
    display_level: "main",
    created_at: startedAt,
  };
}

function synthesizedRuntimeProgressEvents(runDetail: RunDetailPayload | null, startedAt: string): StudioEvent[] {
  const progress = runtimeProgress(runDetail);
  const runId = String(runDetail?.run_id ?? "");
  const todo = asRecord(progress.todo);
  const currentTodo = asRecord(todo.current);
  const toolUse = asRecord(progress.tool_use);
  const verification = asRecord(progress.verification);
  const loop = asRecord(progress.loop);
  const workerSummary = asRecord(progress.worker_summary);
  const exitReason = firstText(String(loop.exit_reason ?? ""), String(progress.exit_reason ?? ""));
  return [
    runtimeProgressEvent(
      runId,
      1,
      "Plan/Todo",
      firstText(String(todo.summary ?? ""), String(currentTodo.content ?? ""), String(progress.current_step ?? "")),
      "plan",
      eventStatus(currentTodo.status ?? todo.status ?? progress.workflow_state),
      { kind: "todo", ...todo },
      startedAt
    ),
    runtimeProgressEvent(
      runId,
      2,
      "Tool Use",
      firstText(String(toolUse.summary ?? ""), String(progress.current_step ?? "")),
      "execute",
      eventStatus(toolUse.status ?? progress.workflow_state),
      { kind: "tool_use", ...toolUse },
      startedAt
    ),
    runtimeProgressEvent(
      runId,
      3,
      "Verify",
      firstText(String(verification.summary ?? ""), String(verification.status ?? "")),
      "review",
      eventStatus(verification.status ?? progress.workflow_state),
      { kind: "verification", ...verification },
      startedAt
    ),
    runtimeProgressEvent(
      runId,
      4,
      "Worker progress",
      firstText(String(workerSummary.summary ?? ""), String(workerSummary.status ?? "")),
      "execute",
      eventStatus(workerSummary.status ?? progress.workflow_state),
      { kind: "worker_summary", ...workerSummary },
      startedAt
    ),
    runtimeProgressEvent(
      runId,
      5,
      "Repair/Ask/Stop",
      firstText(String(progress.current_blocker ?? ""), exitReason, String(progress.next_step ?? ""), String(progress.next_command ?? "")),
      exitReason || progress.current_blocker ? "next" : "result",
      eventStatus(progress.current_blocker ? "blocked" : exitReason || progress.workflow_state),
      { kind: "loop_exit", exit_reason: exitReason, next_command: progress.next_command, blocker: progress.current_blocker },
      startedAt
    ),
  ].filter(Boolean) as StudioEvent[];
}

function textOrFallback(value: unknown, fallback: string): string {
  const text = String(value ?? "").trim();
  return text || fallback;
}

function goalTitle(runDetail: RunDetailPayload | null): string {
  const goal = asRecord(runDetail?.goal_spec);
  const run = asRecord(runDetail?.run);
  return textOrFallback(goal.normalized_goal ?? goal.original_goal ?? run.goal ?? run.summary, "No goal selected yet");
}

function actionLabel(value: string): string {
  const normalized = value.trim().toLowerCase().replace(/^asteria\s+/, "");
  if (normalized.startsWith("review")) return "Review";
  if (normalized.startsWith("accept")) return "Accept";
  if (normalized.startsWith("resume") || normalized.startsWith("continue") || normalized.startsWith("run")) return "Continue";
  if (normalized.startsWith("decide")) return "Decide";
  if (normalized.startsWith("debug") || normalized.startsWith("repair")) return "Debug";
  return "Continue";
}

function latestActiveEvent(events: StudioEvent[]): StudioEvent | null {
  return [...events]
    .reverse()
    .find((event) =>
      (!event.display_level || event.display_level === "main")
      && (event.status === "running" || event.status === "waiting_user" || event.type === "final_answer" || event.type === "error")
    ) ?? null;
}

function DecisionCard({
  runId,
  decision,
  onResolveDecision,
}: {
  runId: string;
  decision: AnyRecord;
  onResolveDecision: (runId: string, decisionId: string, optionId: string) => Promise<void>;
}) {
  const [busyOption, setBusyOption] = useState<string | null>(null);
  const decisionId = String(decision.decision_id ?? "");
  const recommended = String(decision.recommended_option_id ?? "");
  const options = asArray(decision.options) as AnyRecord[];
  const impact = asRecord(decision.impact);

  async function choose(optionId: string) {
    setBusyOption(optionId);
    try {
      await onResolveDecision(runId, decisionId, optionId);
    } finally {
      setBusyOption(null);
    }
  }

  if (!decisionId || !options.length) return null;
  return (
    <div className="decisionCard">
      <div className="decisionHeader">
        <CircleDot size={15} />
        <strong>{textOrFallback(decision.question, "Decision needed")}</strong>
      </div>
      <div className="decisionMeta">
        {recommended && <span>Recommended: {recommended}</span>}
        {Object.keys(impact).length > 0 && (
          <span>
            Risk {textOrFallback(impact.risk, "medium")} / Budget {textOrFallback(impact.budget, "medium")}
          </span>
        )}
      </div>
      <div className="decisionOptions">
        {options.map((option) => {
          const optionId = String(option.option_id ?? "");
          if (!optionId) return null;
          const label = textOrFallback(option.label ?? option.title, optionId);
          const description = String(option.description ?? option.tradeoff ?? "").trim();
          return (
            <button
              key={optionId}
              className={optionId === recommended ? "recommended" : ""}
              disabled={Boolean(busyOption)}
              onClick={() => void choose(optionId)}
            >
              <span>{label}</span>
              {description && <small>{description}</small>}
              {busyOption === optionId && <Loader2 size={13} className="spinning" />}
            </button>
          );
        })}
      </div>
    </div>
  );
}


function RuntimeSnapshot({
  overview,
  runDetail,
  events,
  onRuntimeAction,
  onResolveDecision,
  onPermit,
}: {
  overview: OverviewPayload | null;
  runDetail: RunDetailPayload | null;
  events: StudioEvent[];
  onRuntimeAction: (nextAction: string) => Promise<void>;
  onResolveDecision: (runId: string, decisionId: string, optionId: string) => Promise<void>;
  onPermit: (jobId: string, action: "allow" | "deny") => Promise<void>;
}) {
  void overview;
  const progress = runtimeProgress(runDetail);
  if (!Object.keys(progress).length && !runDetail?.ok) return null;
  const activeEvent = latestActiveEvent(events);
  const loop = asRecord(progress.loop);
  const recovery = asRecord(loop.recovery);
  const budget = asRecord(loop.budget);
  const loopContext = asRecord(loop.context_pressure);
  const decisions = (runDetail?.decision_requests ?? []) as AnyRecord[];
  const mainAction = asRecord(runDetail?.main_action);
  const runId = String(runDetail?.run_id ?? "");
  const nextActionValue = firstText(String(mainAction.next_command ?? ""), String(progress.next_command ?? ""));
  const pendingPermission = activeEvent?.type === "permission_request" && activeEvent.status === "waiting_user" && activeEvent.job_id
    ? activeEvent
    : null;
  const nextLabel = nextActionValue ? firstText(String(mainAction.label ?? ""), actionLabel(nextActionValue)) : "";
  const nextStep = decisions.length
    ? `${decisions.length} decision${decisions.length === 1 ? "" : "s"} need your input.`
    : nextActionValue ? `Ready for ${nextLabel}.` : textOrFallback(loop.exit_reason ? `Stopped: ${loop.exit_reason}` : "", "No action needed right now");
  if (!decisions.length && !pendingPermission && !nextActionValue && !loop.exit_reason) return null;

  return (
    <section className="runtimeSnapshot" aria-label="Next action">
      <div className="runtimeSnapshotHeader">
        <div>
          <span className="eyebrow">Next action</span>
          <h2>{nextStep}</h2>
        </div>
        <span className={`runtimeStatus ${decisions.length || pendingPermission ? "waiting_user" : nextActionValue ? "running" : "completed"}`}>
          {decisions.length || pendingPermission ? "needs input" : nextActionValue ? "ready" : "stopped"}
        </span>
      </div>
      <div className="runtimeNextAction">
        {nextActionValue || decisions.length ? <PlayCircle size={13} /> : <CheckCircle2 size={13} />}
        <span>{nextStep}</span>
        {decisions.length ? (
          <button className="runtimeActionButton" onClick={() => void onRuntimeAction("decide --list-pending")}>
            Decide
          </button>
        ) : nextActionValue ? (
          <button className="runtimeActionButton" onClick={() => void onRuntimeAction(nextActionValue)}>
            {nextLabel}
          </button>
        ) : (
          <button className="runtimeActionButton done" disabled>
            Done
          </button>
        )}
      </div>
      <RuntimeLoopSignals
        loop={loop}
        recovery={recovery}
        budget={budget}
        contextPressure={loopContext}
      />
      {runId && decisions.slice(0, 3).map((decision) => (
        <DecisionCard
          key={String(decision.decision_id ?? JSON.stringify(decision))}
          runId={runId}
          decision={decision}
          onResolveDecision={onResolveDecision}
        />
      ))}
      {pendingPermission && (
        <PermissionCard
          event={pendingPermission}
          onAllow={() => onPermit(pendingPermission.job_id!, "allow")}
          onDeny={() => onPermit(pendingPermission.job_id!, "deny")}
        />
      )}
    </section>
  );
}

function RuntimeLoopSignals({
  loop,
  recovery,
  budget,
  contextPressure,
}: {
  loop: AnyRecord;
  recovery: AnyRecord;
  budget: AnyRecord;
  contextPressure: AnyRecord;
}) {
  const items = [
    loopSignal(
      "Loop",
      firstText(
        String(loop.exit_reason ?? ""),
        String(loop.latest_decision ? asRecord(loop.latest_decision).action ?? "" : ""),
        "running"
      ),
      toneFor(String(loop.exit_reason ?? "ready"))
    ),
    loopSignal(
      "Recovery",
      recovery.required === true
        ? recovery.satisfied === true
          ? "covered"
          : "needs decision"
        : recovery.required === false
          ? "not needed"
          : "",
      recovery.required === true && recovery.satisfied !== true ? "bad" : "good",
      String(recovery.reason ?? "")
    ),
    loopSignal(
      "Budget",
      firstText(String(budget.status ?? ""), String(budget.highest_label ?? "")),
      toneFor(String(budget.status ?? "ready"))
    ),
    loopSignal(
      "Context",
      firstText(String(contextPressure.status ?? ""), percent(Number(contextPressure.context_window_ratio ?? 0))),
      toneFor(String(contextPressure.status ?? "ready"))
    ),
  ].filter((item) => item.value.trim());

  if (!items.length) return null;
  return (
    <div className="runtimeLoopSignals" aria-label="Loop state">
      {items.map((item) => (
        <span key={item.label} className={`loopSignal ${item.tone}`} title={item.title || undefined}>
          <small>{item.label}</small>
          <strong>{item.value}</strong>
        </span>
      ))}
    </div>
  );
}

function loopSignal(label: string, value: string, tone: string, title = "") {
  return { label, value, tone, title };
}

function ContextWindowPopover({ runDetail }: { runDetail: RunDetailPayload | null }) {
  const summary = contextWindowSummary(runDetail);
  const [open, setOpen] = useState(false);
  if (!summary) return null;
  const freeRatio = Math.max(0, 1 - summary.ratio);
  const health = summary.ratio >= 0.9 ? "bad" : summary.ratio >= 0.75 ? "warn" : "good";

  return (
    <div className={`contextWindowDock ${open ? "open" : ""}`}>
      <button className="contextWindowTrigger" onClick={() => setOpen((value) => !value)}>
        <CircleDot size={10} />
        <span>Context window</span>
        <strong>{percent(summary.ratio)}</strong>
        {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
      </button>
      {open && (
        <div className="contextWindowPanel">
          <div className="contextWindowHeader">
            <span className={`contextHealth ${health}`}>{summary.status || health}</span>
            <strong>{formatUsage(summary.used)} / {summary.capacity ? formatUsage(summary.capacity) : "unknown"}</strong>
          </div>
          <div className="contextUsageBar">
            <span style={{ width: percent(summary.ratio) }} />
          </div>
          <div className="contextBreakdown compact">
            <div className="contextBreakdownRow free">
              <span>Free space</span>
              <strong>{summary.capacity ? formatUsage(Math.max(0, summary.capacity - summary.used)) : "unknown"}</strong>
              <em>{percent(freeRatio)}</em>
            </div>
            <p>Detailed breakdown is available in diagnostics.</p>
          </div>
        </div>
      )}
    </div>
  );
}

function EmptyState({ onPrompt }: { onPrompt: (text: string) => void }) {
  return (
    <section className="emptyThread">
      <div className="emptyPanel">
        <CircleDot size={25} />
        <h2>What would you like to do?</h2>
        <p>Ask a question, draft a plan, or describe a goal. Asteria will answer naturally and ask before taking sensitive actions.</p>
        <div className="examplePrompts">
          {EXAMPLE_PROMPTS.map((ex) => (
            <button key={ex} onClick={() => onPrompt(ex)}>{ex}</button>
          ))}
        </div>
      </div>
    </section>
  );
}

function runtimeSessionEvents(runDetail: RunDetailPayload | null): StudioEvent[] {
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
        content_delta: String(event.content_delta ?? event.summary ?? ""),
        command: Array.isArray(event.command) ? event.command.map(String) : undefined,
        data: asRecord(event.data),
        artifact_refs: asArray(event.artifact_refs).map(String),
        evidence_refs: asArray(event.evidence_refs).map(String),
        runtime_channel: String(event.channel ?? "progress"),
        runtime_event_type: String(event.event_type ?? "message"),
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
      title: "Runtime goal",
      summary: goalText,
      content_delta: goalText,
      run_id: runId,
      phase: "understand",
      display_level: "main",
      created_at: startedAt,
    },
  ];

  events.push(...(userProgress.length ? userProgress : synthesizedRuntimeProgressEvents(runDetail, startedAt)));

  const finalSummary = asRecord(runDetail.final_report_summary);
  const progress = runtimeProgress(runDetail);
  const finalText = firstText(
    String(progress.result_summary ?? ""),
    String(progress.summary ?? ""),
    String(finalSummary.summary ?? ""),
    String(run.summary ?? ""),
    String(progress.workflow_state ?? finalSummary.workflow_state ?? "")
  );
  if (finalText) {
    events.push({
      event_id: `runtime-final-${runId || "latest"}`,
      session_id: "runtime-session",
      type: "final_answer",
      status: String(run.status ?? "").toLowerCase() === "blocked" ? "blocked" : "completed",
      title: "Runtime result",
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

function userProgressType(event: AnyRecord): StudioEvent["type"] {
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

function userProgressTitle(event: AnyRecord): string {
  const title = String(event.title ?? "").trim();
  if (title) return title;
  const channel = String(event.channel ?? "");
  const phase = String(event.phase ?? "");
  if (channel === "execution_chain") return "Agent loop";
  if (channel === "tool") return "Tool Use";
  if (phase === "review") return "Verify";
  if (phase === "plan") return "Plan/Todo";
  if (phase === "next") return "Repair/Ask/Stop";
  return "Runtime progress";
}

function userProgressSummary(event: AnyRecord): string {
  return firstText(String(event.summary ?? ""), String(event.content_delta ?? ""), userProgressTitle(event));
}

function PendingTurn({ message, mode, startedAt }: { message: string; mode: string; startedAt: number }) {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    const tick = () => setElapsed(Math.max(0, Math.floor((Date.now() - startedAt) / 1000)));
    tick();
    const timer = window.setInterval(tick, 1000);
    return () => window.clearInterval(timer);
  }, [startedAt]);

  const phase = mode === "auto"
    ? "Routing intent"
    : mode === "chat"
    ? "Thinking"
    : "Starting run";

  return (
    <div className="conversationTurn pendingTurn">
      <div className="turnUser">
        <div className="turnUserBubble optimistic">
          <p>{message}</p>
          <span className="turnUserTime">sending</span>
        </div>
      </div>
      <div className="turnWaiting">
        <Loader2 size={14} className="spinning" />
        <span className="waitingDots" aria-hidden="true"><i /> <i /> <i /></span>
        <strong>{phase}</strong>
        <small>{elapsed}s</small>
      </div>
    </div>
  );
}

function LiveStream({ steps, onPermit }: { steps: NarrativeStepType[]; onPermit: (jobId: string, action: "allow" | "deny") => Promise<void>; }) {
  const activeStep = steps.at(-1);
  const phaseLabel = activeStep ? (PHASE_LABELS[activeStep.kind] ?? activeStep.label) : "Processing";
  const isWaiting = activeStep?.status === "waiting_user";
  const modelText = steps
    .filter((s) => s.kind === "thinking" || s.kind === "plan" || s.kind === "verification")
    .map((s) => {
      const event = s.events[0];
      if (event?.type?.startsWith("model_") && event.phase !== "chat") {
        return event.status === "running"
          ? "Model is drafting structured output. The readable plan will appear when validation finishes."
          : "Model output captured; preparing a readable result.";
      }
      return event?.content_delta || s.summary || "";
    })
    .filter(Boolean)
    .join("\n\n");
  const toolSteps = steps.filter((s) => s.kind === "tool" || s.kind === "repair");
  const fileChanges = extractFileChanges(steps);
  const toolOutputs = toolSteps
    .flatMap((s) => s.events.map((e) => ({ id: s.id, text: e.content_delta, cmd: e.command })))
    .filter((o) => o.text);
  const permEvent = steps
    .flatMap((s) => s.events)
    .find((e) => e.type === "permission_request" && e.status === "waiting_user" && e.job_id);

  return (
    <div className="liveStream">
      <div className="livePhaseRow">
        {isWaiting ? <span className="livePhaseDot waiting" /> : <Loader2 size={13} className="spinning liveSpinner" />}
        <span className="livePhaseLabel">{phaseLabel}</span>
        {activeStep?.title && activeStep.title !== phaseLabel && <span className="livePhaseTitle">{activeStep.title}</span>}
      </div>

      {toolSteps.length > 0 && (
        <div className="liveToolRow">
          {toolSteps.map((s) => {
            const cmd = s.events[0]?.command;
            const cmdStr = Array.isArray(cmd) ? cmd.slice(0, 4).join(" ") : "";
            const label = s.title || (cmdStr ? cmdStr.slice(0, 48) : s.label);
            return (
              <span key={s.id} className={`liveToolChip ${s.status}`} title={cmdStr || undefined}>
                <Terminal size={10} />
                {label}
              </span>
            );
          })}
        </div>
      )}

      {toolOutputs.length > 0 && (
        <div className="liveToolOutputs">
          {toolOutputs.map((o, i) => <pre key={i} className="liveToolOutput">{o.text}</pre>)}
        </div>
      )}

      {fileChanges.length > 0 && (
        <div className="liveFileRow">
          {fileChanges.slice(0, 10).map((fc, i) => {
            const name = String(fc.path ?? fc.file ?? "file").split(/[/\\]/).at(-1);
            const adds = fc.additions != null ? `+${fc.additions}` : "";
            const dels = fc.deletions != null ? `-${fc.deletions}` : "";
            return (
              <span key={i} className="liveFileChip">
                <FileText size={10} />
                {name}
                {(adds || dels) && <span className="liveFileDelta">{[adds, dels].filter(Boolean).join(" ")}</span>}
              </span>
            );
          })}
          {fileChanges.length > 10 && <span className="liveFileChip muted">+{fileChanges.length - 10} more</span>}
        </div>
      )}

      {modelText && <pre className="liveModelText">{modelText}</pre>}
      {permEvent && (
        <PermissionCard
          event={permEvent}
          onAllow={() => onPermit(permEvent.job_id!, "allow")}
          onDeny={() => onPermit(permEvent.job_id!, "deny")}
        />
      )}
    </div>
  );
}


function useSmoothText(text: string): string {
  const [visible, setVisible] = useState(text);
  useEffect(() => {
    let cancelled = false;
    setVisible((current) => (text.startsWith(current) ? current : ""));
    const timer = window.setInterval(() => {
      if (cancelled) return;
      setVisible((current) => {
        if (current.length >= text.length) {
          window.clearInterval(timer);
          return text;
        }
        return text.slice(0, Math.min(text.length, current.length + 28));
      });
    }, 28);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [text]);
  return visible;
}

function ChatStreamPreview({ step }: { step: NarrativeStepType }) {
  const event = step.events.at(-1) || step.events[0];
  const text = step.events.map((item) => item.content_delta || "").join("");
  const smoothText = useSmoothText(text);
  const modelId = event?.model_name
    ? `${event.model_provider || "model"}/${event.model_name}`
    : event?.model_provider || "model";
  return (
    <div className="chatStreamPreview">
      <div className="chatStreamHeader">
        <Loader2 size={13} className="spinning" />
        <strong>Thinking</strong>
        {modelId && <span>{modelId}</span>}
      </div>
      {smoothText ? <pre>{smoothText}</pre> : <p>Waiting for the first tokens...</p>}
    </div>
  );
}

type ProcessExpandSignal = { mode: "expand" | "collapse"; id: number } | null;

function TurnMiddle({ steps, selected, onSelect, onPermit, expandSignal }: {
  steps: NarrativeStepType[];
  selected: StudioEvent | null;
  onSelect: (e: StudioEvent) => void;
  onPermit: (jobId: string, action: "allow" | "deny") => Promise<void>;
  expandSignal: ProcessExpandSignal;
}) {
  const hasPendingPermission = steps.some((s) => s.events.some((e) => e.type === "permission_request" && e.status === "waiting_user"));
  const representative = middleRepresentativeEvent(steps);
  const selectedInMiddle = Boolean(selected && steps.some((step) => step.events.some((event) => event.event_id === selected.event_id)));
  const [open, setOpen] = useState(hasPendingPermission);
  useEffect(() => {
    if (!expandSignal) return;
    setOpen(expandSignal.mode === "expand");
  }, [expandSignal?.id, expandSignal?.mode]);
  if (steps.length === 0) return null;
  return (
    <div className="turnMiddle">
      <button
        className={`turnMiddleBadge ${open ? "open" : ""} ${selectedInMiddle ? "selected" : ""}`}
        onClick={() => {
          setOpen((o) => !o);
          if (representative) onSelect(representative);
        }}
      >
        {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
        <Wrench size={11} />
        <span>{middleSummary(steps)}</span>
      </button>
      {open && (
        <div className="turnMiddleSteps">
          {steps.map((step) => {
            const permStep = step.events.find((e) => e.type === "permission_request" && e.status === "waiting_user" && e.job_id);
            if (permStep) {
              return (
                <PermissionCard
                  key={permStep.event_id}
                  event={permStep}
                  onAllow={() => onPermit(permStep.job_id!, "allow")}
                  onDeny={() => onPermit(permStep.job_id!, "deny")}
                />
              );
            }
            return <NarrativeStep key={step.id} step={step} selected={selected} onSelect={onSelect} />;
          })}
        </div>
      )}
    </div>
  );
}

function middleRepresentativeEvent(steps: NarrativeStepType[]): StudioEvent | null {
  const events = steps.flatMap((step) => step.events);
  return events.find((event) => event.type === "permission_request" && event.status === "waiting_user")
    ?? events.find((event) => event.status === "failed" || event.status === "blocked")
    ?? events.find((event) => event.status === "running")
    ?? events[0]
    ?? null;
}

function TurnFinal({ step, middleSteps }: { step: NarrativeStepType; middleSteps: NarrativeStepType[]; }) {
  const event = step.events[0];
  const text = event?.content_delta || step.summary || step.title || "No content";
  const isError = step.kind === "error" || step.status === "failed";
  const visibleText = stripContextNoise(text);
  const sections = finalSections(visibleText, isError, middleSteps);

  return (
    <div className={`turnFinal ${isError ? "failed" : ""}`}>
      <div className="turnFinalHeader">
        <span className="turnFinalAvatar">A</span>
        <span className="turnFinalLabel">Asteria</span>
      </div>
      <div className="turnFinalText">
        {sections.map((section, index) => (
          <section key={`${section.title}-${index}`} className={index === 0 ? "primaryFinalSection" : ""}>
            {section.title && <h3>{section.title}</h3>}
            {section.lines.map((line, lineIndex) => renderFinalLine(line, lineIndex))}
          </section>
        ))}
      </div>
    </div>
  );
}

function stripContextNoise(text: string): string {
  const backendNoise = /\n(?:Context refs:|Current session:|Next actions:|Model route:|Route rationale:|Evidence refs:|Artifact refs:|Run id:|Latest run:)/i;
  return String(text || "")
    .split(backendNoise)[0]
    .replace(/\n?_Answered with model route:[\s\S]*$/i, "")
    .replace(/\n?_Local fallback answer:[\s\S]*$/i, "")
    .replace(/^Latest run:\s*`?run-[^\n]+\n?/gim, "")
    .replace(/^.*(?:Inspector|Evidence Explorer).*$/gim, "")
    .trim();
}

type FinalSection = { title: string; lines: string[] };

function finalSections(text: string, isError: boolean, middleSteps: NarrativeStepType[]): FinalSection[] {
  const sections = splitFinalSections(text);
  const byTitle = new Map(
    sections
      .filter((section) => section.title)
      .map((section) => [canonicalFinalTitle(section.title), section.lines.filter((line) => line.trim())])
  );
  const rawLines = sections.flatMap((section) => section.lines).filter((line) => line.trim());
  const verificationLines = byTitle.get("Verification") ?? inferredVerificationLines(middleSteps);
  const risksLines = byTitle.get("Risks / Next step") ?? byTitle.get("Next step") ?? inferredRiskLines(middleSteps, isError);
  return [
    {
      title: isError ? "Issue" : "Result",
      lines: byTitle.get("Result") ?? byTitle.get("Issue") ?? (rawLines.length ? rawLines : [isError ? "The run needs attention." : "Done."]),
    },
    {
      title: "Verification",
      lines: verificationLines.length ? verificationLines : ["No verification summary was recorded for this turn."],
    },
    {
      title: "Risks / Next step",
      lines: risksLines.length ? risksLines : ["No immediate next action is required."],
    },
  ];
}

function canonicalFinalTitle(value: string): string {
  const text = value.trim().toLowerCase();
  if (/issue|error|problem|blocked|风险|问题/.test(text)) return "Issue";
  if (/verify|validation|review|检查|验证/.test(text)) return "Verification";
  if (/risk|next|action|tradeoff|下一步|风险/.test(text)) return "Risks / Next step";
  if (/result|summary|outcome|done|结果|总结/.test(text)) return "Result";
  return value.trim();
}

function inferredVerificationLines(middleSteps: NarrativeStepType[]): string[] {
  const verification = middleSteps
    .filter((step) => step.kind === "verification" || step.events.some((event) => event.phase === "review"))
    .map((step) => firstText(step.summary, step.title))
    .filter(Boolean);
  return [...new Set(verification)].slice(0, 3);
}

function inferredRiskLines(middleSteps: NarrativeStepType[], isError: boolean): string[] {
  const failed = middleSteps
    .filter((step) => step.status === "failed" || step.status === "blocked" || step.kind === "error" || step.kind === "repair")
    .map((step) => firstText(step.summary, step.title))
    .filter(Boolean);
  if (failed.length) return [...new Set(failed)].slice(0, 3);
  return isError ? ["Review the issue detail and choose Debug, Replan, Ask, or Stop."] : [];
}

function splitFinalSections(text: string): FinalSection[] {
  const sections: { title: string; lines: string[] }[] = [];
  let current: { title: string; lines: string[] } = { title: "", lines: [] };
  for (const raw of String(text || "").split(/\r?\n/)) {
    const heading = raw.match(/^##\s+(.+?)\s*$/);
    if (heading) {
      if (current.title || current.lines.some(Boolean)) sections.push(current);
      current = { title: heading[1].trim(), lines: [] };
      continue;
    }
    current.lines.push(raw);
  }
  if (current.title || current.lines.some(Boolean)) sections.push(current);
  return sections.length ? sections : [{ title: "", lines: [text] }];
}

function renderFinalLine(line: string, index: number) {
  if (!line.trim()) return null;
  const bullet = line.match(/^\s*-\s+(.+)$/);
  if (bullet) return <p key={index} className="finalBullet">{bullet[1]}</p>;
  if (/^\s{2,}\S/.test(line)) return <p key={index} className="finalDetail">{line.trim()}</p>;
  return <p key={index}>{line}</p>;
}

function ConversationTurn({ steps, selected, onSelect, onPermit, isLast, isRunning, expandSignal }: {
  steps: NarrativeStepType[];
  selected: StudioEvent | null;
  onSelect: (e: StudioEvent) => void;
  onPermit: (jobId: string, action: "allow" | "deny") => Promise<void>;
  isLast: boolean;
  isRunning: boolean;
  expandSignal: ProcessExpandSignal;
}) {
  const goalStep = steps[0];
  const restSteps = steps.slice(1);
  const responseIndex = (() => {
    for (let index = restSteps.length - 1; index >= 0; index -= 1) {
      if (restSteps[index].kind === "final" || restSteps[index].kind === "error") return index;
    }
    return -1;
  })();
  const responseStep = responseIndex >= 0 ? restSteps[responseIndex] : null;
  const rawMiddleSteps = responseIndex >= 0 ? restSteps.filter((_, index) => index !== responseIndex) : restSteps;
  const responsePhase = responseStep?.events[0]?.phase;
  const hideCompletedModelStream = responseStep ? hasFinalAnswerForPhase([responseStep], responsePhase) : false;
  const middleSteps = hideCompletedModelStream
    ? rawMiddleSteps.filter((step) => !isModelThinkingStep(step, responsePhase))
    : rawMiddleSteps;
  const goalEvent = goalStep.events[0];
  const userText = goalEvent?.content_delta || goalStep.summary || goalStep.title || "";
  const time = goalEvent ? formatEventTime(goalEvent.created_at) : "";
  const turnRunning = isLast && isRunning && !responseStep;

  return (
    <div className="conversationTurn">
      <div className="turnUser">
        <div className="turnUserBubble">
          <p>{userText}</p>
          <span className="turnUserTime">{time}</span>
        </div>
      </div>
      {turnRunning ? (
        middleSteps.length === 0 ? (
          <div className="turnRunning"><Loader2 size={14} className="spinning" /><span>Starting...</span></div>
        ) : middleSteps.length === 1 && isModelThinkingStep(middleSteps[0], "chat") ? (
          <ChatStreamPreview step={middleSteps[0]} />
        ) : (
          <LiveStream steps={middleSteps} onPermit={onPermit} />
        )
      ) : (
        middleSteps.length > 0 && <TurnMiddle steps={middleSteps} selected={selected} onSelect={onSelect} onPermit={onPermit} expandSignal={expandSignal} />
      )}
      {responseStep && <TurnFinal step={responseStep} middleSteps={middleSteps} />}
    </div>
  );
}

export function Thread({ events, selected, isRunning, onSelect, onPrompt, onPermit, onRuntimeAction, onResolveDecision, pendingTurn, overview, runDetail }: {
  events: StudioEvent[];
  selected: StudioEvent | null;
  isRunning: boolean;
  onSelect: (event: StudioEvent) => void;
  onPrompt: (text: string) => void;
  onPermit: (jobId: string, action: "allow" | "deny") => Promise<void>;
  onRuntimeAction: (nextAction: string) => Promise<void>;
  onResolveDecision: (runId: string, decisionId: string, optionId: string) => Promise<void>;
  pendingTurn?: { message: string; mode: string; startedAt: number } | null;
  overview?: OverviewPayload | null;
  runDetail?: RunDetailPayload | null;
}) {
  const threadRef = useRef<HTMLElement>(null);
  const [expandSignal, setExpandSignal] = useState<ProcessExpandSignal>(null);
  const mainEvents = useMemo(() => events.filter((e) => !e.display_level || e.display_level === "main"), [events]);
  const shouldShowPending = Boolean(pendingTurn) && !mainEvents.some((event) =>
    event.type === "user_message" && event.content_delta === pendingTurn?.message
  );
  const runtimeEvents = useMemo(() => runtimeSessionEvents(runDetail ?? null), [runDetail]);
  const selectedRunId = String(runDetail?.run_id ?? "");
  const hasSelectedRunEvents = Boolean(selectedRunId) && mainEvents.some((event) => String(event.run_id ?? "") === selectedRunId);
  const sessionEvents = hasSelectedRunEvents || !runtimeEvents.length ? mainEvents : runtimeEvents;
  const narrativeEvents = useMemo(() => toNarrativeEvents(sessionEvents), [sessionEvents]);
  const narrative = useMemo(() => buildRunNarrative(narrativeEvents), [narrativeEvents]);
  const turns = useMemo(() => splitIntoTurns(narrative.steps), [narrative.steps]);
  const hasProcessBlocks = turns.some((turn) => turn.length > 2 || (turn.length > 1 && turn.at(-1)?.kind !== "final" && turn.at(-1)?.kind !== "error"));

  useEffect(() => {
    const el = threadRef.current;
    if (!el) return;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 220;
    if (nearBottom || isRunning) requestAnimationFrame(() => { el.scrollTop = el.scrollHeight; });
  }, [mainEvents.length, isRunning]);

  if (!turns.length && !shouldShowPending) {
    return (
      <section className="thread" ref={threadRef}>
        <RuntimeSnapshot overview={overview ?? null} runDetail={runDetail ?? null} events={events} onRuntimeAction={onRuntimeAction} onResolveDecision={onResolveDecision} onPermit={onPermit} />
        <EmptyState onPrompt={onPrompt} />
        <ContextWindowPopover runDetail={runDetail ?? null} />
      </section>
    );
  }

  return (
    <section className="thread" ref={threadRef}>
      <RuntimeSnapshot overview={overview ?? null} runDetail={runDetail ?? null} events={events} onRuntimeAction={onRuntimeAction} onResolveDecision={onResolveDecision} onPermit={onPermit} />
      {hasProcessBlocks && (
        <div className="threadProcessControls" aria-label="Process display controls">
          <button type="button" onClick={() => setExpandSignal({ mode: "expand", id: Date.now() })}>Expand process</button>
          <button type="button" onClick={() => setExpandSignal({ mode: "collapse", id: Date.now() })}>Collapse process</button>
        </div>
      )}
      {turns.map((turnSteps, i) => (
        <ConversationTurn
          key={turnSteps[0].id}
          steps={turnSteps}
          selected={selected}
          onSelect={onSelect}
          onPermit={onPermit}
          isLast={i === turns.length - 1}
          isRunning={isRunning}
          expandSignal={expandSignal}
        />
      ))}
      {shouldShowPending && pendingTurn && <PendingTurn {...pendingTurn} />}
      <ContextWindowPopover runDetail={runDetail ?? null} />
    </section>
  );
}
