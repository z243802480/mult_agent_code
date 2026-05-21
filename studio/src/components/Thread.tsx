import React, { useMemo, useEffect, useRef, useState } from "react";
import {
  ChevronDown, ChevronRight, CircleDot,
  FileText, Loader2, Terminal, Wrench,
} from "lucide-react";
import type { AnyRecord, StudioEvent, NarrativeStep as NarrativeStepType } from "../types";
import { NarrativeStep } from "./NarrativeStep";
import { PermissionCard } from "./PermissionCard";
import { toNarrativeEvents, buildRunNarrative } from "../narrative";

// ── Prompts ─────────────────────────────────────────────────────────────────

const EXAMPLE_PROMPTS = [
  "帮我制定一个 3 天青岛旅行计划",
  "给这个项目的 --version 参数补一个测试",
  "分析最近的失败日志，找出根因",
  "把下面这段需求整理成一页 PRD",
];

// ── Phase labels ─────────────────────────────────────────────────────────────

const PHASE_LABELS: Record<string, string> = {
  thinking:     "思考中",
  plan:         "规划中",
  tool:         "执行工具",
  result:       "整理结果",
  verification: "验证中",
  repair:       "修复中",
  error:        "遇到错误",
};

// ── Helpers ───────────────────────────────────────────────────────────────────

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
  const kindLabels: Record<string, string> = {
    thinking: "思考", plan: "规划", tool: "工具调用",
    result: "文件变化", repair: "修复", verification: "验证", error: "错误",
  };
  const seen = new Set<string>();
  const kinds: string[] = [];
  for (const s of steps) {
    const label = kindLabels[s.kind] ?? s.label;
    if (!seen.has(label)) { seen.add(label); kinds.push(label); }
  }
  return `${steps.length} 步 · ${kinds.slice(0, 4).join(" · ")}`;
}

/** Pull the last model telemetry from any step's events. */
function extractTelemetry(steps: NarrativeStepType[]): {
  modelId: string | null;
  tokens: number;
  latencyMs: number;
} {
  const allEvents = steps.flatMap((s) => s.events);
  const last = [...allEvents].reverse().find((e) => e.model_provider && e.telemetry);
  if (!last) return { modelId: null, tokens: 0, latencyMs: 0 };
  const tel = (last.telemetry ?? {}) as Record<string, number>;
  const tokens = tel.total_tokens ?? (tel.input_tokens ?? 0) + (tel.output_tokens ?? 0);
  const latencyMs = tel.latency_ms ?? tel.duration_ms ?? 0;
  const modelId = last.model_name
    ? `${last.model_provider}/${last.model_name}`
    : (last.model_provider ?? null);
  return { modelId, tokens, latencyMs };
}

/** Collect unique file changes from result-kind steps. */
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

// ── EmptyState ─────────────────────────────────────────────────────────────

function EmptyState({ onPrompt }: { onPrompt: (text: string) => void }) {
  return (
    <section className="emptyThread">
      <div className="emptyPanel">
        <CircleDot size={25} />
        <h2>从一个目标开始</h2>
        <p>告诉我要完成什么任务。我会制定计划、申请权限、执行，并把结果放回这条任务线。</p>
        <div className="examplePrompts">
          {EXAMPLE_PROMPTS.map((ex) => (
            <button key={ex} onClick={() => onPrompt(ex)}>{ex}</button>
          ))}
        </div>
      </div>
    </section>
  );
}

// ── LiveStream ────────────────────────────────────────────────────────────────
// Shown WHILE a turn is running.  Surfaces LLM token stream + tool chips +
// file-change chips so the user can watch progress in real time.

function LiveStream({
  steps,
  onPermit,
}: {
  steps: NarrativeStepType[];
  onPermit: (jobId: string, action: "allow" | "deny") => Promise<void>;
}) {
  const activeStep = steps.at(-1);
  const phaseLabel = activeStep ? (PHASE_LABELS[activeStep.kind] ?? activeStep.label) : "处理中";
  const isWaiting = activeStep?.status === "waiting_user";

  // ── Streaming model text ─────────────────────────────────────────
  // Concat all model/thinking output so the user sees every word as it arrives.
  const modelText = steps
    .filter((s) => s.kind === "thinking" || s.kind === "plan" || s.kind === "verification")
    .map((s) => s.events[0]?.content_delta || s.summary || "")
    .filter(Boolean)
    .join("\n\n");

  // ── Tool call chips ─────────────────────────────────────────────
  const toolSteps = steps.filter((s) => s.kind === "tool" || s.kind === "repair");

  // ── File change chips ──────────────────────────────────────────
  const fileChanges = extractFileChanges(steps);

  // ── Tool stdout (if Runtime emits content_delta on tool events) ──
  const toolOutputs = toolSteps
    .flatMap((s) => s.events.map((e) => ({ id: s.id, text: e.content_delta, cmd: e.command })))
    .filter((o) => o.text);

  // ── Pending permission card ─────────────────────────────────────
  const permEvent = steps
    .flatMap((s) => s.events)
    .find((e) => e.type === "permission_request" && e.status === "waiting_user" && e.job_id);

  return (
    <div className="liveStream">
      {/* Phase header */}
      <div className="livePhaseRow">
        {isWaiting
          ? <span className="livePhaseDot waiting" />
          : <Loader2 size={13} className="spinning liveSpinner" />}
        <span className="livePhaseLabel">{phaseLabel}</span>
        {activeStep?.title && activeStep.title !== phaseLabel && (
          <span className="livePhaseTitle">{activeStep.title}</span>
        )}
      </div>

      {/* Tool call chips — inline log of every tool invoked */}
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

      {/* Tool stdout — shown when Runtime emits output on tool_delta events */}
      {toolOutputs.length > 0 && (
        <div className="liveToolOutputs">
          {toolOutputs.map((o, i) => (
            <pre key={i} className="liveToolOutput">{o.text}</pre>
          ))}
        </div>
      )}

      {/* File change chips */}
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
          {fileChanges.length > 10 && (
            <span className="liveFileChip muted">+{fileChanges.length - 10} 更多</span>
          )}
        </div>
      )}

      {/* Streaming LLM text — this is the model's actual words arriving token by token */}
      {modelText && <pre className="liveModelText">{modelText}</pre>}

      {/* Permission card — always surfaces immediately, not buried in a collapsed step */}
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

// ── TurnMiddle ────────────────────────────────────────────────────────────────
// Shown AFTER a turn completes.  Collapsed by default — this is the process
// archive for inspection, not the primary reading surface.

function TurnMiddle({
  steps,
  selected,
  onSelect,
  onPermit,
}: {
  steps: NarrativeStepType[];
  selected: StudioEvent | null;
  onSelect: (e: StudioEvent) => void;
  onPermit: (jobId: string, action: "allow" | "deny") => Promise<void>;
}) {
  const hasPendingPermission = steps.some((s) =>
    s.events.some((e) => e.type === "permission_request" && e.status === "waiting_user")
  );
  const [open, setOpen] = useState(hasPendingPermission);

  if (steps.length === 0) return null;

  return (
    <div className="turnMiddle">
      <button
        className={`turnMiddleBadge ${open ? "open" : ""}`}
        onClick={() => setOpen((o) => !o)}
      >
        {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
        <Wrench size={11} />
        <span>{middleSummary(steps)}</span>
      </button>
      {open && (
        <div className="turnMiddleSteps">
          {steps.map((step) => {
            const permStep = step.events.find(
              (e) => e.type === "permission_request" && e.status === "waiting_user" && e.job_id
            );
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
            return (
              <NarrativeStep
                key={step.id}
                step={step}
                selected={selected}
                onSelect={onSelect}
              />
            );
          })}
        </div>
      )}
    </div>
  );
}

// ── TurnFinal ─────────────────────────────────────────────────────────────────
// The agent's formal reply.  Shows actual content plus model/token metadata.

function TurnFinal({
  step,
  middleSteps,
}: {
  step: NarrativeStepType;
  middleSteps: NarrativeStepType[];
}) {
  const event = step.events[0];
  const text = event?.content_delta || step.summary || step.title || "（无内容）";
  const isError = step.kind === "error" || step.status === "failed";

  const { modelId, tokens, latencyMs } = extractTelemetry(middleSteps);
  const sections = splitFinalSections(text);

  return (
    <div className={`turnFinal ${isError ? "failed" : ""}`}>
      <div className="turnFinalHeader">
        <span className="turnFinalAvatar">A</span>
        <span className="turnFinalLabel">Asteria</span>
        {modelId && <span className="turnFinalMeta">{modelId}</span>}
        {tokens > 0 && (
          <span className="turnFinalMeta">
            {tokens.toLocaleString()} tokens
            {latencyMs > 0 && ` · ${(latencyMs / 1000).toFixed(1)}s`}
          </span>
        )}
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

function splitFinalSections(text: string): { title: string; lines: string[] }[] {
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

// ── ConversationTurn ──────────────────────────────────────────────────────────
// One full user ↔ agent exchange.
//
// RUNNING  → LiveStream (LLM tokens stream in, tool + file chips inline)
// DONE     → TurnMiddle (collapsed process archive) + TurnFinal (reply)

function ConversationTurn({
  steps,
  selected,
  onSelect,
  onPermit,
  isLast,
  isRunning,
}: {
  steps: NarrativeStepType[];
  selected: StudioEvent | null;
  onSelect: (e: StudioEvent) => void;
  onPermit: (jobId: string, action: "allow" | "deny") => Promise<void>;
  isLast: boolean;
  isRunning: boolean;
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
  const middleSteps = responseIndex >= 0
    ? restSteps.filter((_, index) => index !== responseIndex)
    : restSteps;

  const goalEvent = goalStep.events[0];
  const userText = goalEvent?.content_delta || goalStep.summary || goalStep.title || "";
  const time = goalEvent ? formatEventTime(goalEvent.created_at) : "";

  const turnRunning = isLast && isRunning && !responseStep;

  return (
    <div className="conversationTurn">
      {/* User message bubble */}
      <div className="turnUser">
        <div className="turnUserBubble">
          <p>{userText}</p>
          <span className="turnUserTime">{time}</span>
        </div>
      </div>

      {turnRunning ? (
        /* LIVE: stream LLM output while the run is active */
        middleSteps.length === 0 ? (
          <div className="turnRunning">
            <Loader2 size={14} className="spinning" />
            <span>正在启动...</span>
          </div>
        ) : (
          <LiveStream steps={middleSteps} onPermit={onPermit} />
        )
      ) : (
        /* DONE: collapsed process archive */
        middleSteps.length > 0 && (
          <TurnMiddle
            steps={middleSteps}
            selected={selected}
            onSelect={onSelect}
            onPermit={onPermit}
          />
        )
      )}

      {/* Formal reply — always shown once available */}
      {responseStep && <TurnFinal step={responseStep} middleSteps={middleSteps} />}
    </div>
  );
}

// ── Thread (root export) ──────────────────────────────────────────────────────

export function Thread({
  events,
  selected,
  isRunning,
  onSelect,
  onPrompt,
  onPermit,
}: {
  events: StudioEvent[];
  selected: StudioEvent | null;
  isRunning: boolean;
  onSelect: (event: StudioEvent) => void;
  onPrompt: (text: string) => void;
  onPermit: (jobId: string, action: "allow" | "deny") => Promise<void>;
}) {
  const threadRef = useRef<HTMLElement>(null);

  const mainEvents = useMemo(
    () => events.filter((e) => !e.display_level || e.display_level === "main"),
    [events]
  );

  const narrativeEvents = useMemo(() => toNarrativeEvents(mainEvents), [mainEvents]);
  const narrative = useMemo(() => buildRunNarrative(narrativeEvents), [narrativeEvents]);
  const turns = useMemo(() => splitIntoTurns(narrative.steps), [narrative.steps]);

  useEffect(() => {
    const el = threadRef.current;
    if (!el) return;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 220;
    if (nearBottom || isRunning) {
      requestAnimationFrame(() => { el.scrollTop = el.scrollHeight; });
    }
  }, [mainEvents.length, isRunning]);

  if (!turns.length) {
    return <EmptyState onPrompt={onPrompt} />;
  }

  return (
    <section className="thread" ref={threadRef}>
      {turns.map((turnSteps, i) => (
        <ConversationTurn
          key={turnSteps[0].id}
          steps={turnSteps}
          selected={selected}
          onSelect={onSelect}
          onPermit={onPermit}
          isLast={i === turns.length - 1}
          isRunning={isRunning}
        />
      ))}
    </section>
  );
}
