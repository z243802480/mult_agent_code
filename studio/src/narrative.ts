import type { StudioEvent, NarrativeStep, RunNarrative } from "./types";
import { capabilityInfo } from "./capability";
import { projectTitle, projectSummary } from "./titleProjection";

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
      activeModel = { ...event, type: "model_delta", summary: event.summary || "等待模型响应..." };
      result.push(activeModel);
      continue;
    }
    if (event.type === "model_delta") {
      if (
        activeModel &&
        activeModel.phase === event.phase &&
        activeModel.model_provider === event.model_provider
      ) {
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
      if (
        activeModel &&
        activeModel.phase === event.phase &&
        activeModel.model_provider === event.model_provider
      ) {
        activeModel.status = "completed";
        activeModel.summary = event.summary || activeModel.summary;
        activeModel.telemetry = event.telemetry;
      }
      activeModel = null;
      continue;
    }
    if (event.type === "model_error") {
      activeModel = null;
      result.push(event);
      continue;
    }
    if (
      event.type === "agent_turn" ||
      event.type === "tool_start" ||
      event.type === "tool_delta" ||
      event.type === "tool_end" ||
      event.type === "tool_observation"
    ) {
      activeModel = null;
      result.push(event);
      continue;
    }
    activeModel = null;
    result.push(event);
  }
  return result;
}

// A REAL tool card is backed by an actual tool_call/tool_output/error event — it carries a tool
// identity (tool_call_id) or a concrete command. The loop also reuses the tool_use/tool_result
// transcript kinds (and the execute phase) for its own bookkeeping — iteration markers ("执行迭代 N"),
// task-progress rollups ("任务执行进展"), "worker action requested", "candidate workspace created" —
// which are plain `message` events with no tool identity. Those are turn/phase narration, not tools,
// so they must NOT render as prominent, empty tool cards (ADR-0021). Detected by stable structural
// markers (runtime_event_type / tool_call_id / command), never by matching their localized text.
function isRealToolEvent(event: StudioEvent): boolean {
  const rt = String(event.runtime_event_type ?? "");
  if (rt === "tool_call" || rt === "tool_output" || rt === "error") return true;
  if (event.tool_call_id) return true;
  return (event.command?.length ?? 0) > 0;
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
    (transcriptKind === "decision_request" && Boolean(data.promotion_id)) ||
    (event.runtime_channel === "progress" &&
      event.runtime_event_type === "decision" &&
      (Boolean(data.promotable_files) || Boolean(data.promotion_id)))
  ) {
    return "hold";
  }
  // The model's own conversational message for a step (ADR-0021): "我先创建 clamp.py …". This is the
  // model speaking to the user — surfaced as prose, never a harness label. Must precede the phase/
  // model fallbacks so it isn't misread as a tool or thinking step.
  if (transcriptKind === "assistant_message") return "narration";
  if (transcriptKind === "plan" || transcriptKind === "todo_update") return "plan";
  // tool_use/tool_result classify as a tool card only when backed by a real tool event; otherwise
  // they are loop bookkeeping (iteration/progress markers) and fold in as a quiet turn step.
  if (transcriptKind === "tool_use" || transcriptKind === "tool_result")
    return isRealToolEvent(event) ? "tool" : "turn";
  if (transcriptKind === "verification") return "verification";
  if (transcriptKind === "repair") return "repair";
  // Evidence/diagnostic RECORDS are quiet process rows, never the closing answer (ADR-0021). Mapping
  // them to "observation" keeps them foldable in the process detail instead of leaking into the
  // ThinkingBlock or (worse) being picked up as the final reply.
  if (transcriptKind === "diagnostic") return "observation";
  // The final-report event is a diagnostic artifact pointer, not the conversational closing
  // reply (ADR-0012). Keep it in the process stream so the conclusion message — which now
  // carries the agent's authored recap (CV-C) — is the step rendered as the final answer.
  if (event.runtime_event_type === "final_report") return "result";
  if (transcriptKind === "final" || transcriptKind === "stop") return "final";
  if (transcriptKind === "file_change") return "result";
  // A PENDING permission/decision ask (waiting for the user) is a prominent action card. An
  // already-recorded decision ("已记录能力决策"/"已选择权限模式") is quiet bookkeeping the loop keeps
  // per tool call — it must fold into the detail, not sit as a prominent card between the real tools.
  if (
    transcriptKind === "permission_request" ||
    transcriptKind === "decision_request" ||
    transcriptKind === "ask"
  ) {
    // Only a PENDING job-based ask (waiting_user + job_id) is the actionable PermissionCard
    // (allow/deny). A COMPLETED permission/capability decision ALSO carries a job_id but is just a
    // recorded bookkeeping row ("已选择权限模式", "已记录能力决策") — it must fall through to
    // observation (machinery, dropped from the thread), not render as a dead "tool" card wedged
    // between the real tools. A waiting_user decision WITHOUT a job_id is the loop pausing for your
    // call — a prominent in-context "需要你的决定" card, resolved via the bottom next-action bar.
    if (event.job_id && event.status === "waiting_user") return "tool";
    if (event.status === "waiting_user") return "decision";
    return "observation";
  }
  if (transcriptKind === "subagent_summary") return "subagent";
  if (event.type === "user_message") return "goal";
  if (
    event.type === "agent_turn" ||
    event.runtime_event_type === "turn_start" ||
    event.runtime_event_type === "turn_end"
  )
    return "turn";
  if (event.type === "intent_route") return "thinking";
  if (event.type === "permission_request") return "tool";
  if (event.type === "tool_start" || event.type === "tool_delta" || event.type === "tool_end")
    return "tool";
  if (event.type === "tool_observation" || event.runtime_event_type === "tool_observation")
    return "observation";
  if (event.type === "model_error" || event.type === "error") return "error";
  if (event.type === "final_answer") return "final";
  if (event.phase === "plan") return "plan";
  if (event.phase === "review") return "verification";
  if (event.phase === "execute" || event.phase === "resume") {
    if (event.status === "failed") return "repair";
    // Only real tool events become prominent tool cards; other execute-phase progress (worker/turn/
    // promotion bookkeeping) folds in as a quiet turn step instead of an empty tool card.
    return isRealToolEvent(event) ? "tool" : "turn";
  }
  if (
    event.type === "model_start" ||
    event.type === "model_delta" ||
    event.type === "model_end" ||
    event.type === "reasoning_delta"
  )
    return "thinking";
  if (event.type === "file_changed") return "result";
  return "thinking";
}

function narrativeLabel(kind: NarrativeStep["kind"], event: StudioEvent): string {
  if (kind === "narration") return "Asteria";
  if (kind === "observation") return "观察";
  if (kind === "turn") return "Agent 步骤";
  if (kind === "goal") return "用户消息";
  if (kind === "thinking" && event.phase === "plan" && event.model_provider) return "结构化生成";
  if (kind === "thinking") return "思考";
  if (kind === "plan") return "计划";
  if (kind === "tool") {
    const cap = capabilityInfo(event);
    if (cap) return cap.label;
    return event.command?.length ? "工具调用" : "操作";
  }
  if (kind === "result")
    return event.runtime_event_type === "final_report" ? "最终报告" : "文件改动";
  if (kind === "repair") return "修复";
  if (kind === "verification") return "验证";
  if (kind === "final") return "最终答复";
  if (kind === "subagent") return "子 agent";
  if (kind === "hold") return "已保留待你查看";
  if (kind === "resume") return "已恢复";
  if (kind === "decision") return "需要你的决定";
  // A genuine error gets an explicit, non-cryptic label AND its detail (summary/error) is always shown
  // (see NarrativeStep) so the user can see WHAT and WHERE. The bare fallback below must stay neutral
  // ("步骤"), not "问题" — otherwise every unmapped-kind bookkeeping row screams "problem" for nothing.
  if (kind === "error") return "遇到问题";
  return "步骤";
}

function shouldGroup(step: NarrativeStep, event: StudioEvent): boolean {
  const first = step.events[0];
  if (
    step.kind === "goal" ||
    step.kind === "final" ||
    step.kind === "error" ||
    step.kind === "hold" ||
    step.kind === "resume" ||
    step.kind === "decision"
  )
    return false;
  if (step.kind === "thinking")
    return first.phase === event.phase && first.model_provider === event.model_provider;
  if (step.kind === "turn")
    return !!first.tool_call_id && first.tool_call_id === event.tool_call_id;
  if (step.kind === "tool") {
    // Same tool call → same card. A single file op emits a tool_use THEN a tool_result user_progress
    // event that share one tool_call_id (e.g. toolcall-0002) but different EN/CN summaries ("读取 X" /
    // "Read file: X") — without this they render as two duplicate same-title cards ("重复打开"). These
    // user_progress events do NOT carry an event.type starting with "tool_", so the legacy type-based
    // check below never merged them; keying on the shared tool_call_id does.
    if (first.tool_call_id && first.tool_call_id === event.tool_call_id) return true;
    // Same shell command → same card (run_command/run_tests carry a real command string). Guard on
    // non-empty: file/read/patch tools have an empty command, and "" === "" must NOT collapse two
    // different tools into one card. For those, group by the stable action title instead (ADR-0021:
    // a tool's call+result share one target-carrying title like "写入 square.py").
    const cmd = first.command?.join(" ") ?? "";
    if (cmd && cmd === (event.command?.join(" ") ?? "")) return true;
    return (
      first.type.startsWith("tool_") &&
      event.type.startsWith("tool_") &&
      first.title === event.title
    );
  }
  if (step.kind === "observation")
    return !!first.tool_call_id && first.tool_call_id === event.tool_call_id;
  if (step.kind === "subagent") {
    // One delegation = one card: merge a spawn_subagent's dispatch + returned-summary events by
    // their shared child_task_id. Two DIFFERENT experts (distinct child_task_id) must stay separate
    // cards, otherwise the phase-fallback below would collapse them and lose the first expert.
    const firstChild = String(((first.data ?? {}) as Record<string, unknown>).child_task_id ?? "");
    const eventChild = String(((event.data ?? {}) as Record<string, unknown>).child_task_id ?? "");
    return !!firstChild && firstChild === eventChild;
  }
  return first.phase === event.phase;
}

function mergeStatus(
  current: StudioEvent["status"],
  next: StudioEvent["status"],
): StudioEvent["status"] {
  if (next === "failed" || current === "failed") return "failed";
  if (next === "waiting_user" || current === "waiting_user") return "waiting_user";
  if (next === "running" || current === "running") return "running";
  if (next === "queued" || current === "queued") return "queued";
  return "completed";
}

function countRefs(events: StudioEvent[], key: "evidence_refs" | "artifact_refs"): number {
  return events.reduce((n, e) => n + (e[key]?.length ?? 0), 0);
}

// The main conversation shows only the user's real input and the agent-loop's real output. The loop
// also emits internal scaffolding to drive ITSELF — routing hints, ceremony rows, control-flow
// notices. Those are machinery, not something the agent said to the user, so they never belong in the
// thread (they remain in the Inspector, which reads raw events). Filtered by STABLE STRUCTURAL MARKERS
// (phase / transcript_kind / status), never by matching localized title text.
function isInternalLoopScaffolding(event: StudioEvent): boolean {
  // "next step" routing hints (e.g. "Review recent failures / Run /debug or repair workflow").
  if (String(event.phase ?? "") === "next") return true;
  // Goal-accept ceremony ("理解目标" — "Runtime accepted the user goal and started a planning run").
  // Pure ritual: the user's own message already IS the goal. Marker: the plan run's understand phase.
  if (String(event.phase ?? "") === "understand") return true;
  const transcriptKind = String(event.transcript_kind ?? "");
  // Context-mount bookkeeping ("上下文关联" — what the loop attached for the task). Machinery, not
  // conversation; the raw mount stays in context_mounts.jsonl / the Inspector.
  if (transcriptKind === "context_status") return true;
  // Loop control-flow NOTICES ("自动重规划已创建修复任务", "已创建修复任务"): the runtime telling
  // ITSELF it spun up a repair task. The actual repair surfaces as its tool calls + narration; this
  // notice is bookkeeping. A GENUINE failure (status="failed") is kept and shown as a real problem.
  if (transcriptKind === "repair" && event.status !== "failed") return true;
  const eventType = String(event.runtime_event_type ?? "");
  if (eventType === "final_report" && !String(event.content_delta ?? "").trim()) return true;
  return false;
}

// Step kinds that are pure loop bookkeeping — the agent driving itself, never something it said to the
// user: turn/iteration markers ("执行迭代 N", "Agent 步骤"), context association, and recorded-decision
// observations ("已选择权限模式", "已记录能力决策", "观察"). They are dropped from the main thread
// entirely (both the live and the completed views) and remain only in the Inspector's raw evidence.
const MACHINERY_KINDS = new Set<NarrativeStep["kind"]>(["turn", "context", "observation"]);

export function buildRunNarrative(events: StudioEvent[]): RunNarrative {
  const steps: NarrativeStep[] = [];
  for (const event of events) {
    if (isInternalLoopScaffolding(event)) continue;
    const kind = narrativeKind(event);
    if (MACHINERY_KINDS.has(kind)) continue;
    const label = narrativeLabel(kind, event);
    const previous = steps.at(-1);
    if (previous && previous.kind === kind && shouldGroup(previous, event)) {
      previous.events.push(event);
      previous.summary = projectSummary(event.summary) || previous.summary;
      previous.status = mergeStatus(previous.status, event.status);
      previous.title = projectTitle(event.title) || previous.title;
      continue;
    }
    steps.push({
      id: `${kind}-${steps.length}-${event.event_id}`,
      kind,
      label,
      title: projectTitle(event.title),
      summary: projectSummary(event.summary || event.content_delta || event.title),
      status: event.status,
      events: [event],
      defaultOpen: kind === "final",
    });
  }
  // Only the last actively-running step expands automatically
  const lastActive = [...steps]
    .reverse()
    .find((s) => s.status === "running" || s.status === "waiting_user");
  if (lastActive) lastActive.defaultOpen = true;
  // If run has ended without a final step, open only the last failed/error step
  const hasFinal = steps.some((s) => s.kind === "final");
  const hasRunning = !!lastActive;
  if (!hasFinal && !hasRunning) {
    const lastFailed = [...steps]
      .reverse()
      .find((s) => s.status === "failed" || s.kind === "error");
    if (lastFailed) lastFailed.defaultOpen = true;
  }

  const finalEvent = [...events]
    .reverse()
    .find((e) => e.type === "final_answer" || e.type === "error");
  const goalEvent = events.find((e) => e.type === "user_message");
  const status = finalEvent?.type === "error" ? "failed" : finalEvent ? "completed" : "running";
  if (status !== "running") {
    for (const step of steps) {
      if (step.status === "running" || step.status === "queued") step.status = "completed";
      step.events = step.events.map((e) =>
        e.status === "running" || e.status === "queued" ? { ...e, status: "completed" } : e,
      );
    }
  }
  return {
    steps,
    report: {
      status,
      headline:
        status === "running"
          ? "Agent 正在处理任务。"
          : status === "failed"
            ? "运行遇到了问题。"
            : "运行已完成并产出了最终结果。",
      goal: (goalEvent?.summary ?? "") as string,
      modelEvents: events.filter(
        (e) =>
          e.type.startsWith("model_") ||
          e.type === "assistant_delta" ||
          e.type === "reasoning_delta",
      ).length,
      toolEvents: events.filter(
        (e) =>
          e.type.startsWith("tool_") ||
          e.type === "agent_turn" ||
          e.runtime_channel === "execution_chain" ||
          (e.command?.length ?? 0) > 0,
      ).length,
      evidenceRefs: countRefs(events, "evidence_refs"),
      artifactRefs: countRefs(events, "artifact_refs"),
      finalText: (finalEvent?.content_delta ?? finalEvent?.summary ?? "") as string,
    },
  };
}

// Internal event/telemetry payload markers. A JSON object carrying any of these quoted keys is a
// serialized runtime payload (role contract, provider route strategy, model_* telemetry) that a weak
// provider sometimes echoes verbatim into its streamed completion — it is NOT natural-language
// reasoning. These keys never appear as JSON keys in a real assistant answer, so matching on the
// quoted-key form (`"agent_role_contract":`) keeps the filter from touching prose that merely mentions
// braces. The raw payload stays fully available in the Inspector (event.data / event.telemetry); only
// the user-facing reasoning view is cleaned.
const PAYLOAD_KEY = new RegExp(
  '"(?:' +
    [
      "agent_role_contract",
      "provider_route_strategy",
      "model_provider",
      "model_route",
      "model_tier",
      "runtime_profile_id",
      "model_profile_id",
      "deadline_profile",
      "provider_call_seconds",
      "stream_idle_timeout_seconds",
      "call_chain",
      "execution_chain",
      "transcript_kind",
      "display_level",
      "ui_intent",
      "role_purpose",
      "deadline_remaining_ms",
    ].join("|") +
    ')"\\s*:',
);

// Index just past the '}' that closes the JSON object opened at `open`, honoring string literals so
// braces inside quoted values do not miscount. Returns -1 when the object is never closed (a stream
// truncated mid-payload) — the caller drops from the marker to end-of-text in that case.
function matchBrace(text: string, open: number): number {
  let depth = 0;
  let inString = false;
  for (let i = open; i < text.length; i += 1) {
    const ch = text[i];
    if (inString) {
      if (ch === "\\") {
        i += 1;
        continue;
      }
      if (ch === '"') inString = false;
      continue;
    }
    if (ch === '"') {
      inString = true;
      continue;
    }
    if (ch === "{") depth += 1;
    else if (ch === "}") {
      depth -= 1;
      if (depth === 0) return i + 1;
    }
  }
  return -1;
}

// Remove serialized runtime-payload JSON objects that a provider echoed into the reasoning stream,
// keeping the surrounding natural-language text. Scans for each '{' and, when the balanced object (or
// the truncated tail) contains a payload marker key, excises that span. Conservative by construction:
// non-payload JSON and plain prose pass through untouched.
function stripSerializedPayloads(text: string): string {
  let result = "";
  let i = 0;
  while (i < text.length) {
    if (text[i] === "{") {
      const end = matchBrace(text, i);
      const segment = end === -1 ? text.slice(i) : text.slice(i, end);
      if (PAYLOAD_KEY.test(segment)) {
        i = end === -1 ? text.length : end;
        continue;
      }
    }
    result += text[i];
    i += 1;
  }
  return result;
}

// Single source of reasoning cleanup (I5): strip stray <think>/<thinking> markers a provider may
// leave in the stream, keeping the inner text, and drop serialized runtime-payload JSON (role
// contract / provider route strategy / telemetry) that a weak provider sometimes echoes verbatim
// instead of natural reasoning. Applied on EVERY render path (live tail + finalized, chat + run) so
// neither raw tags nor raw event JSON leak into the main thread. Intentionally conservative — it only
// removes the tags themselves and clearly-serialized payload objects, never guessing at prose.
export function cleanReasoning(text: string): string {
  const withoutTags = String(text || "").replace(/<\/?think(?:ing)?>/gi, "");
  return stripSerializedPayloads(withoutTags).trim();
}

// Harness-authored placeholder lines the model_start/model_end events carry when the real reasoning
// stream is kept in the Inspector. They are machine status text ("Asteria is preparing the next
// step."), NOT the model thinking — so they must never surface as the model's live/streamed prose on
// the main thread. Shared by the completed-turn ThinkingBlock and the live LiveStream (ADR-0021).
export const THINKING_PLACEHOLDERS = new Set([
  "Asteria is preparing the next step.",
  "Asteria is preparing the next step",
  "Asteria finished drafting this step.",
  "Asteria finished drafting this step",
  "Asteria is drafting a response.",
  "Asteria is drafting a response",
  "Draft complete",
  "Drafting",
  "Thinking",
]);

// A tool step's stable action signature: the command it ran (preferred — a real shell/tool command
// string), else its projected title, paired with its terminal status. Two tool steps with the same
// signature ran the SAME command to the SAME outcome.
function toolActionSignature(step: NarrativeStep): string {
  let command = "";
  for (const event of step.events) {
    const joined = (event.command ?? []).join(" ").trim();
    if (joined) {
      command = joined;
      break;
    }
  }
  return `${command || step.title || step.label || ""}|${step.status ?? ""}`;
}

// Collapse STRICTLY consecutive tool cards that are identical (same command AND same status) into one.
// These are display duplicates: the loop re-ran the exact same command to the exact same outcome with
// only bookkeeping (a non-rendered "tool result" rollup) between them, so the second card teaches the
// user nothing. Conservative by design — a different command, or the same command with a DIFFERENT
// status (e.g. a test that failed then passed), keeps both cards so a real retry story is never hidden.
export function dedupeAdjacentToolSteps(steps: NarrativeStep[]): NarrativeStep[] {
  const out: NarrativeStep[] = [];
  let lastSignature = "";
  for (const step of steps) {
    const signature = toolActionSignature(step);
    if (out.length && signature === lastSignature) continue;
    out.push(step);
    lastSignature = signature;
  }
  return out;
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
  const lastFinal = [...events]
    .reverse()
    .find((e) => e.type === "final_answer" || e.type === "error");
  const cutoff = lastFinal ? eventTime(lastFinal) : null;
  const liveEvents = cutoff ? events.filter((e) => eventTime(e) > cutoff) : events;
  if (!liveEvents.length) return false;
  const isActive = (e: StudioEvent) =>
    e.status === "running" || e.status === "queued" || e.status === "waiting_user";
  const isTerminal = (e: StudioEvent) =>
    e.status === "completed" ||
    e.status === "failed" ||
    e.type === "tool_end" ||
    e.type === "final_answer" ||
    e.type === "error";
  let lastTerminalTime = -Infinity;
  for (const event of liveEvents) {
    if (isTerminal(event)) lastTerminalTime = Math.max(lastTerminalTime, eventTime(event));
  }
  return liveEvents.some((event) => isActive(event) && eventTime(event) > lastTerminalTime);
}
