import React, { useState } from "react";
import {
  CheckCircle2,
  ChevronRight,
  CircleDot,
  Clock3,
  FileText,
  GitBranch,
  ListChecks,
  Paperclip,
  Plug,
  RefreshCw,
  RotateCcw,
  ShieldAlert,
  Sparkles,
  Terminal,
  Users,
  XCircle,
} from "lucide-react";
import type { NarrativeStep as NarrativeStepType, StudioEvent } from "../types";
import { Status } from "./Shared";
import { EventCard } from "./EventCard";
import { ClampedOutput } from "./ClampedOutput";
import { capabilityInfo } from "../capability";

function formatEventTime(value: unknown): string {
  const date = new Date(String(value ?? ""));
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString();
}

// What an expert delegation actually did, read off the runtime's own cards (B4). `concurrent` is a
// FACT the runtime stamps on every card of a fan-out batch — never inferred from card ordering, so a
// serial delegation (no batch) simply shows no parallel chip.
function subagentFacts(events: StudioEvent[]): {
  concurrent: boolean;
  batchSize: number;
  changedFiles: string[];
  tier: string;
} {
  let concurrent = false;
  let batchSize = 0;
  let tier = "";
  const changedFiles = new Set<string>();
  for (const event of events) {
    const data = (event.data ?? {}) as Record<string, unknown>;
    if (data.concurrent === true) concurrent = true;
    if (typeof data.batch_size === "number") batchSize = data.batch_size;
    if (typeof data.model_tier === "string" && data.model_tier) tier = data.model_tier;
    for (const file of Array.isArray(data.changed_files) ? data.changed_files : []) {
      changedFiles.add(String(file));
    }
  }
  return { concurrent, batchSize, changedFiles: [...changedFiles], tier };
}

function stepIcon(kind: NarrativeStepType["kind"]) {
  if (kind === "goal") return <CircleDot size={14} />;
  if (kind === "thinking") return <Clock3 size={14} />;
  if (kind === "plan") return <GitBranch size={14} />;
  if (kind === "turn") return <RefreshCw size={14} />;
  if (kind === "tool") return <Terminal size={14} />;
  if (kind === "observation") return <ListChecks size={14} />;
  if (kind === "context") return <Paperclip size={14} />;
  if (kind === "result") return <FileText size={14} />;
  if (kind === "repair") return <RefreshCw size={14} />;
  if (kind === "verification") return <ShieldAlert size={14} />;
  if (kind === "guardrail") return <ShieldAlert size={14} />;
  if (kind === "final") return <CheckCircle2 size={14} />;
  if (kind === "subagent") return <Users size={14} />;
  return <XCircle size={14} />;
}

export function NarrativeStep({
  step,
  selected,
  onSelect,
}: {
  step: NarrativeStepType;
  selected: StudioEvent | null;
  onSelect: (event: StudioEvent) => void;
}) {
  const [open, setOpen] = useState(
    step.defaultOpen && step.kind !== "tool" && step.kind !== "repair",
  );
  const primary = step.events[0];
  const time = primary ? formatEventTime(primary.created_at) : "";
  const cap = capabilityInfo(primary);
  const sub = subagentFacts(step.events);

  // Goal step stays as a compact user-message bubble.
  if (step.kind === "goal") {
    const userText = primary?.content_delta || step.summary || step.title;
    return (
      <article className="narrativeStep goal completed">
        <div className="goalBubble">
          <p>{userText}</p>
          <span className="goalMeta">{time}</span>
        </div>
      </article>
    );
  }

  // Held promotion: a prominent, plain-language card — the agent applied changes in an isolated copy
  // and is waiting for your approval before merging. Copy is composed from the event data; the raw
  // runtime summary (which carries CLI/maintainer text) is intentionally not shown here.
  if (step.kind === "hold") {
    const data = (primary?.data ?? {}) as Record<string, unknown>;
    const promotable = Array.isArray(data.promotable_files)
      ? data.promotable_files.map(String)
      : [];
    const risky = Array.isArray(data.risky_files) ? data.risky_files.map(String) : [];
    const count = promotable.length;
    return (
      <article className="narrativeStep hold waiting_user">
        <div className="holdCard">
          <div className="holdHead">
            <ShieldAlert size={15} />
            <strong>已扣留，等待你查看</strong>
            {time && <span className="holdTime">{time}</span>}
          </div>
          <p className="holdBody">
            {count > 0
              ? `已在隔离副本中扣留 ${count} 处改动，等待你批准。`
              : "已扣留此改动，等待你批准。"}
            {risky.length > 0 && <> 已标记为敏感：{risky.join("、")}。</>}
          </p>
        </div>
      </article>
    );
  }

  // Pending decision: the loop paused and needs the user's call before it can safely continue (e.g.
  // "approve this run_command?"). A prominent, in-context card — NOT a dead tool card — so a
  // legitimately-paused run reads as "waiting for you", not "stuck". The actionable buttons live in
  // the bottom next-action bar (RuntimeSnapshot DecisionCard), which carries the decision's options.
  if (step.kind === "decision") {
    const data = (primary?.data ?? {}) as Record<string, unknown>;
    const reason = String(data.reason ?? "").trim();
    return (
      <article className="narrativeStep decision waiting_user">
        <div className="decisionInlineCard">
          <div className="decisionInlineHead">
            <CircleDot size={15} />
            <strong>需要你的决定</strong>
            {time && <span className="decisionInlineTime">{time}</span>}
          </div>
          <p className="decisionInlineBody">
            智能体已暂停，等待你的决定后再继续。
            {reason ? ` 原因：${reason}。` : ""}
            请在下方的操作栏选择如何继续。
          </p>
        </div>
      </article>
    );
  }

  // Warm resume: a compact, plain-language line — the agent re-applied prior decisions and continued
  // the same session. Counts come from the decision payload; no CLI/maintainer text is shown.
  if (step.kind === "resume") {
    const data = (primary?.data ?? {}) as Record<string, unknown>;
    const decision = (data.decision ?? {}) as Record<string, unknown>;
    const applied = typeof decision.applied_decisions === "number" ? decision.applied_decisions : 0;
    const created = typeof decision.created_tasks === "number" ? decision.created_tasks : 0;
    return (
      <article className="narrativeStep resume completed">
        <div className="resumeLine">
          <RotateCcw size={14} />
          <span className="resumeText">
            {applied > 0 ? `已继续 — 复用了 ${applied} 条此前的决定` : "已继续该会话"}
            {created > 0 && `，并排入 ${created} 个后续任务`}。
          </span>
          {time && <span className="resumeTime">{time}</span>}
        </div>
      </article>
    );
  }

  return (
    <article className={`narrativeStep ${step.kind} ${step.status}`}>
      <button className="stepChrome" onClick={() => setOpen((o) => !o)}>
        <span className="stepIcon">
          {cap ? (
            cap.type === "mcp" ? (
              <Plug size={14} />
            ) : (
              <Sparkles size={14} />
            )
          ) : (
            stepIcon(step.kind)
          )}
        </span>
        <span className="stepLabels">
          <strong>{step.label}</strong>
          <small>{cap ? cap.title : step.title}</small>
        </span>
        {cap && (
          <span className="stepCapabilityChips">
            {cap.denied && <span className="capabilityChip denied">已拦截</span>}
            {!cap.denied && cap.retries > 0 && (
              <span className="capabilityChip">重试 {cap.retries} 次</span>
            )}
            {!cap.denied && cap.artifacts > 0 && (
              <span className="capabilityChip">{cap.artifacts} 个文件</span>
            )}
          </span>
        )}
        {step.kind === "subagent" && (
          <span className="stepCapabilityChips">
            {sub.concurrent && (
              <span className="capabilityChip parallel">
                {sub.batchSize > 0 ? `并行 · ${sub.batchSize} 位专家` : "并行"}
              </span>
            )}
            {sub.tier && <span className="capabilityChip">{sub.tier} 档</span>}
            {sub.changedFiles.length > 0 && (
              <span className="capabilityChip">{sub.changedFiles.length} 个文件</span>
            )}
          </span>
        )}
        <span className="stepInlineFacts">
          <span>{step.events.length} 条更新</span>
          <span>{time}</span>
        </span>
        <Status status={step.status} />
        <ChevronRight size={14} className={`chevron ${open ? "open" : ""}`} />
      </button>
      <div className={`stepExpandedWrap ${open ? "open" : ""}`}>
        <div className="stepExpanded">
          {/* Always show the detail line for an error step so clicking it reveals WHAT/WHERE went
              wrong (otherwise a "遇到问题" card expands to nothing). Other kinds keep the de-dup that
              hides a summary identical to the title. */}
          {step.summary && (step.kind === "error" || step.summary !== step.title) && (
            <p className="stepSummaryText">{step.summary}</p>
          )}
          {/* Real verification commands + outcomes (ADR-0021): `✓/✗ $ <command>` lines carried on the
              verification event's content_delta, shown as the actual checks that ran — not just a count. */}
          {step.kind === "verification" && primary?.content_delta && (
            <ClampedOutput
              text={primary.content_delta}
              className="stepVerificationDetail"
              maxLines={10}
            />
          )}
          <div className="stepEvents">
            {step.events.map((event) => (
              <EventCard
                event={event}
                compact
                selected={selected?.event_id === event.event_id}
                key={event.event_id}
                onSelect={() => onSelect(event)}
              />
            ))}
          </div>
        </div>
      </div>
    </article>
  );
}
