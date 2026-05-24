import React, { useMemo, useEffect, useRef, useState } from "react";
import { ChevronDown, ChevronRight, CircleDot, FileText, Loader2, Terminal, Wrench } from "lucide-react";
import type { AnyRecord, StudioEvent, NarrativeStep as NarrativeStepType } from "../types";
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
  const kindLabels: Record<string, string> = {
    thinking: "thinking",
    plan: "plan",
    tool: "tool",
    result: "file change",
    repair: "repair",
    verification: "verification",
    error: "error",
  };
  const seen = new Set<string>();
  const kinds: string[] = [];
  for (const s of steps) {
    const label = kindLabels[s.kind] ?? s.label;
    if (!seen.has(label)) { seen.add(label); kinds.push(label); }
  }
  return `${steps.length} step(s): ${kinds.slice(0, 4).join(" / ")}`;
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

function TurnMiddle({ steps, selected, onSelect, onPermit }: {
  steps: NarrativeStepType[];
  selected: StudioEvent | null;
  onSelect: (e: StudioEvent) => void;
  onPermit: (jobId: string, action: "allow" | "deny") => Promise<void>;
}) {
  const hasPendingPermission = steps.some((s) => s.events.some((e) => e.type === "permission_request" && e.status === "waiting_user"));
  const [open, setOpen] = useState(hasPendingPermission);
  if (steps.length === 0) return null;
  return (
    <div className="turnMiddle">
      <button className={`turnMiddleBadge ${open ? "open" : ""}`} onClick={() => setOpen((o) => !o)}>
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

function TurnFinal({ step, middleSteps }: { step: NarrativeStepType; middleSteps: NarrativeStepType[]; }) {
  const event = step.events[0];
  const text = event?.content_delta || step.summary || step.title || "No content";
  const isError = step.kind === "error" || step.status === "failed";
  const visibleText = stripContextNoise(text);
  const sections = splitFinalSections(visibleText);

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

function ConversationTurn({ steps, selected, onSelect, onPermit, isLast, isRunning }: {
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
        middleSteps.length > 0 && <TurnMiddle steps={middleSteps} selected={selected} onSelect={onSelect} onPermit={onPermit} />
      )}
      {responseStep && <TurnFinal step={responseStep} middleSteps={middleSteps} />}
    </div>
  );
}

export function Thread({ events, selected, isRunning, onSelect, onPrompt, onPermit, pendingTurn }: {
  events: StudioEvent[];
  selected: StudioEvent | null;
  isRunning: boolean;
  onSelect: (event: StudioEvent) => void;
  onPrompt: (text: string) => void;
  onPermit: (jobId: string, action: "allow" | "deny") => Promise<void>;
  pendingTurn?: { message: string; mode: string; startedAt: number } | null;
}) {
  const threadRef = useRef<HTMLElement>(null);
  const mainEvents = useMemo(() => events.filter((e) => !e.display_level || e.display_level === "main"), [events]);
  const shouldShowPending = Boolean(pendingTurn) && !mainEvents.some((event) =>
    event.type === "user_message" && event.content_delta === pendingTurn?.message
  );
  const narrativeEvents = useMemo(() => toNarrativeEvents(mainEvents), [mainEvents]);
  const narrative = useMemo(() => buildRunNarrative(narrativeEvents), [narrativeEvents]);
  const turns = useMemo(() => splitIntoTurns(narrative.steps), [narrative.steps]);

  useEffect(() => {
    const el = threadRef.current;
    if (!el) return;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 220;
    if (nearBottom || isRunning) requestAnimationFrame(() => { el.scrollTop = el.scrollHeight; });
  }, [mainEvents.length, isRunning]);

  if (!turns.length && !shouldShowPending) return <EmptyState onPrompt={onPrompt} />;

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
      {shouldShowPending && pendingTurn && <PendingTurn {...pendingTurn} />}
    </section>
  );
}
