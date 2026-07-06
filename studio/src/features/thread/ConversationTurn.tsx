import React, { useEffect, useState } from "react";
import { Brain, Check, ChevronRight, Loader2, Pencil, Wrench } from "lucide-react";
import type { NarrativeStep as NarrativeStepType, StudioEvent } from "../../types";
import { NarrativeStep } from "../../components/NarrativeStep";
import { PermissionCard } from "../../components/PermissionCard";
import { ClampedOutput } from "../../components/ClampedOutput";
import { AggregateDiffChip } from "../../components/AggregateDiffChip";
import { extractFileChangesFromSteps, aggregateFileChangeStats } from "../../fileChanges";
import { LiveStream } from "./LiveStream";
import { ToolCallCard } from "./ToolCallCard";
import { TurnFinal } from "./TurnFinal";
import { runVerificationHint, latestCorrectnessVerdict } from "./runtimeNarrative";
import { cleanReasoning } from "../../narrative";
import { SuggestedActions } from "./SuggestedActions";
import { TurnRewindButton } from "./TurnRewindButton";
import { middleRepresentativeEvent, middleSummary, hasFinalAnswerForPhase, isModelThinkingStep } from "./turnHelpers";
import { formatEventTime } from "./threadUtils";

export type ProcessExpandSignal = { mode: "expand" | "collapse"; id: number } | null;

function TurnMiddle({ steps, selected, onSelect, onPermit, expandSignal, onFileChangeClick, onFileAccept, onFileRevert, turnIndex, turnDiffLabel, onTurnDiffSelect, onAggregateDiffClick, compactDiff, excludeFilePaths }: {
  steps: NarrativeStepType[];
  selected: StudioEvent | null;
  onSelect: (e: StudioEvent) => void;
  onPermit: (jobId: string, action: "allow" | "deny") => Promise<void>;
  expandSignal: ProcessExpandSignal;
  onFileChangeClick?: (path: string) => void;
  onFileAccept?: (path: string) => Promise<boolean> | void;
  onFileRevert?: (path: string) => Promise<boolean> | void;
  turnIndex?: number;
  turnDiffLabel?: string;
  onTurnDiffSelect?: (turnIndex: number) => void;
  onAggregateDiffClick?: (turnIndex: number) => void;
  compactDiff?: boolean;
  excludeFilePaths?: Set<string>;
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
  // Hide files already shown in an earlier turn so each file appears once (in the turn that first
  // changed it) instead of repeating down the whole thread.
  const fileChanges = extractFileChangesFromSteps(steps).filter(
    (change) => !excludeFilePaths?.has(change.path),
  );
  const fileStats = aggregateFileChangeStats(fileChanges);

  if (compactDiff) {
    return (
      <div className="turnMiddle compact">
        {fileStats.files > 0 && (
          <div className="turnFileRowWrap">
            {/* Mainstream (Cursor / Copilot) don't scatter per-file cards through the conversation —
                changed files live in ONE review surface (the right-side Changes pane). The thread
                carries only a single "N files changed → review" entry point that opens it. */}
            <AggregateDiffChip
              files={fileStats.files}
              additions={fileStats.additions}
              deletions={fileStats.deletions}
              onClick={turnIndex && onAggregateDiffClick ? () => onAggregateDiffClick(turnIndex) : undefined}
            />
          </div>
        )}
        {hasPendingPermission && steps.map((step) => {
          const permStep = step.events.find((e) => e.type === "permission_request" && e.status === "waiting_user" && e.job_id);
          if (!permStep) return null;
          return (
            <PermissionCard
              key={permStep.event_id}
              event={permStep}
              onAllow={() => onPermit(permStep.job_id!, "allow")}
              onDeny={() => onPermit(permStep.job_id!, "deny")}
            />
          );
        })}
      </div>
    );
  }

  // Surface the concrete process after completion instead of burying everything behind a closed
  // "Ran N actions" badge. Tool/repair/subagent cards render persistently (compact, output foldable),
  // pending permissions stay visible, and only the softer detail (plan / verification / observation)
  // folds into the disclosure. Diffs + summary keep reading from ALL steps so nothing is lost.
  const permissionSteps = steps.filter((step) =>
    step.events.some((e) => e.type === "permission_request" && e.status === "waiting_user" && e.job_id)
  );
  const permIds = new Set(permissionSteps.map((step) => step.id));
  // The model's own per-step message (ADR-0021): real model prose, shown as the model speaking above
  // the process cards — this is the LLM's actual output on the panel, not a harness label.
  const narrationSteps = steps.filter((step) => !permIds.has(step.id) && step.kind === "narration");
  const narrationIds = new Set(narrationSteps.map((step) => step.id));
  // Context/document association (ADR-0021 slice 3): its own visible step above the tool cards, so
  // "what context did the agent attach" reads as real process — not buried in the folded detail.
  const contextSteps = steps.filter((step) => !permIds.has(step.id) && step.kind === "context");
  const contextIds = new Set(contextSteps.map((step) => step.id));
  const toolSteps = steps.filter(
    (step) => !permIds.has(step.id) && !contextIds.has(step.id) && !narrationIds.has(step.id) && (step.kind === "tool" || step.kind === "repair" || step.kind === "subagent")
  );
  const toolIds = new Set(toolSteps.map((step) => step.id));
  // Holistic rule (ADR-0021): the main thread is a conversation, not a machine dashboard. The user
  // sees their message, the model's words (narration + final), the real tools/commands it ran, the
  // files it changed, and any real problem (repair / error / subagent). EVERYTHING else the loop emits
  // to drive itself — "Agent 步骤 执行迭代", "已记录能力决策", "计划思考中", "观察", phase narration,
  // "正在压缩上下文", thinking placeholders — is machinery. It lives in the Inspector (raw evidence),
  // never on the main thread. This is a WHITELIST, not a per-card blacklist.
  const DETAIL_KINDS = new Set(["repair", "error", "subagent"]);
  const detailSteps = steps.filter(
    (step) =>
      !permIds.has(step.id) && !toolIds.has(step.id) && !contextIds.has(step.id) && !narrationIds.has(step.id)
      && DETAIL_KINDS.has(step.kind)
  );

  return (
    <div className="turnMiddle">
      {narrationSteps.length > 0 && (
        <div className="turnNarration">
          {narrationSteps.map((step) => {
            const text = cleanReasoning(
              step.events.map((e) => e.content_delta || "").join("") || step.summary || ""
            );
            return text ? <p key={step.id} className="turnNarrationText">{text}</p> : null;
          })}
        </div>
      )}
      {fileStats.files > 0 && (
        <div className="turnFileRowWrap">
          {/* One "N files changed → review" entry point, not a scattered per-file list — changed
              files are reviewed in the consolidated Changes pane (Cursor / Copilot pattern). */}
          <AggregateDiffChip
            files={fileStats.files}
            additions={fileStats.additions}
            deletions={fileStats.deletions}
            onClick={turnIndex && onAggregateDiffClick ? () => onAggregateDiffClick(turnIndex) : undefined}
          />
        </div>
      )}
      {contextSteps.length > 0 && (
        <div className="turnContextCards">
          {contextSteps.map((step) => (
            <NarrativeStep key={step.id} step={step} selected={selected} onSelect={onSelect} />
          ))}
        </div>
      )}
      {toolSteps.length > 0 && (
        <div className="turnToolCards">
          {toolSteps.map((step) => (
            <ToolCallCard key={step.id} step={step} showOutput={!compactDiff} />
          ))}
        </div>
      )}
      {permissionSteps.map((step) => {
        const permStep = step.events.find((e) => e.type === "permission_request" && e.status === "waiting_user" && e.job_id);
        if (!permStep) return null;
        return (
          <PermissionCard
            key={permStep.event_id}
            event={permStep}
            onAllow={() => onPermit(permStep.job_id!, "allow")}
            onDeny={() => onPermit(permStep.job_id!, "deny")}
          />
        );
      })}
      {detailSteps.length > 0 && (
        <>
          <button
            className={`turnMiddleBadge ${open ? "open" : ""} ${selectedInMiddle ? "selected" : ""}`}
            onClick={() => {
              setOpen((o) => !o);
              if (representative) onSelect(representative);
            }}
          >
            <ChevronRight size={13} className={`chevron ${open ? "open" : ""}`} />
            <Wrench size={11} />
            <span>{middleSummary(detailSteps)}</span>
          </button>
          <div className={`turnMiddleStepsWrap ${open ? "open" : ""}`}>
            <div className="turnMiddleSteps">
              {detailSteps.map((step) => (
                <NarrativeStep key={step.id} step={step} selected={selected} onSelect={onSelect} />
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function ChatStreamPreview({ step }: { step: NarrativeStepType }) {
  const event = step.events.at(-1) || step.events[0];
  // Honest streaming: render the real content_delta exactly as events land. No client-side
  // typewriter — perceived latency tracks the runtime transport, not an artificial timer.
  const text = cleanReasoning(step.events.map((item) => item.content_delta || "").join(""));
  const modelId = event?.model_name
    ? `${event.model_provider || "model"}/${event.model_name}`
    : event?.model_provider || "model";
  return (
    <div className="chatStreamPreview">
      <div className="chatStreamHeader">
        <Loader2 size={13} className="spinning" />
        <strong>思考中</strong>
        {modelId && <span>{modelId}</span>}
      </div>
      {text ? (
        <div className="streamTextWrap">
          <ClampedOutput text={text} maxLines={8} />
          <span className="streamCaret" aria-hidden="true" />
        </div>
      ) : (
        <p>等待首个响应…</p>
      )}
    </div>
  );
}

// Real elapsed seconds across the thinking events (from event timestamps — never fabricated).
function thinkingDurationSeconds(steps: NarrativeStepType[]): number {
  const times = steps
    .flatMap((step) => step.events)
    .map((event) => Date.parse(String(event.created_at ?? "")))
    .filter((value) => Number.isFinite(value));
  if (times.length < 2) return 0;
  return Math.max(0, Math.round((Math.max(...times) - Math.min(...times)) / 1000));
}

// Token count ONLY when real telemetry carries it — otherwise we show nothing rather than a guess.
function thinkingTokens(steps: NarrativeStepType[]): number {
  let total = 0;
  let found = false;
  for (const step of steps) {
    for (const event of step.events) {
      const telemetry = event.telemetry as Record<string, unknown> | undefined;
      if (!telemetry) continue;
      const raw = telemetry.output_tokens ?? telemetry.completion_tokens ?? telemetry.tokens ?? telemetry.total_tokens;
      const value = Number(raw);
      if (Number.isFinite(value) && value > 0) { total += value; found = true; }
    }
  }
  return found ? total : 0;
}

// Persistent, honest reasoning block. Replaces the old "delete the thinking stream once a final
// answer lands" behavior: after completion the reasoning collapses into a re-openable chip instead
// of vanishing into the process badge. Renders nothing when there is no real reasoning text (no
// empty chip). Default-collapsed while completed; auto-open while still streaming.
// Harness-authored placeholder lines the model_start/model_end events carry when the real reasoning
// stream is kept in the Inspector (not surfaced to the thread). They are machine status text, not the
// model thinking — strip them so we never render an empty/English "思考过程" chip (ADR-0021).
const THINKING_PLACEHOLDERS = new Set([
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

function ThinkingBlock({ steps, live = false }: { steps: NarrativeStepType[]; live?: boolean }) {
  // Filter per EVENT before joining: within a step the harness "preparing"/"drafting" placeholders
  // concatenate with no separator, so a line-based filter would miss the merged string. Drop each
  // placeholder event, keep only real reasoning text.
  const text = cleanReasoning(
    steps
      .flatMap((step) => step.events)
      .map((event) => cleanReasoning(event.content_delta || "").trim())
      .filter((t) => t && !THINKING_PLACEHOLDERS.has(t))
      .join("\n\n")
  ).trim();
  const [open, setOpen] = useState(live);
  useEffect(() => { if (live) setOpen(true); }, [live]);
  if (!text) return null;
  const duration = thinkingDurationSeconds(steps);
  const tokens = thinkingTokens(steps);
  const label = live
    ? "思考中…"
    : duration > 0
      ? `思考了 ${duration} 秒${tokens > 0 ? ` · ${tokens} tokens` : ""}`
      : "思考过程";

  return (
    <div className={`thinkingBlock ${open ? "open" : ""}`}>
      <button type="button" className="thinkingChip" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        {live ? <Loader2 size={12} className="spinning" /> : <Brain size={12} />}
        <span className="thinkingChipLabel">{label}</span>
        <ChevronRight size={12} className={`chevron ${open ? "open" : ""}`} />
      </button>
      {open && (
        <div className="thinkingBody">
          <ClampedOutput text={text} className="thinkingText" maxLines={live ? 8 : 14} defaultExpanded={live} />
        </div>
      )}
    </div>
  );
}

export function PendingTurn({ message, mode, startedAt }: { message: string; mode: string; startedAt: number }) {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    const tick = () => setElapsed(Math.max(0, Math.floor((Date.now() - startedAt) / 1000)));
    tick();
    const timer = window.setInterval(tick, 1000);
    return () => window.clearInterval(timer);
  }, [startedAt]);

  // Main thread shows one calm loading phrase regardless of internal routing mode.
  // (mode is retained for callers; the user-facing copy is uniform.)
  void mode;
  const phase = "思考中…";

  return (
    <div className="conversationTurn pendingTurn">
      <div className="turnUser">
        <div className="turnUserBubble optimistic">
          <p>{message}</p>
          <span className="turnUserTime">发送中</span>
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

export function ConversationTurn({ steps, selected, onSelect, onPermit, isLast, isRunning, expandSignal, onFileChangeClick, onFileAccept, onFileRevert, turnIndex, turnDiffLabel, onTurnDiffSelect, onAggregateDiffClick, compactDiff, excludeFilePaths, runDetail, viewMode, onTurnRewind, onSuggestedAction, suppressSuggested, onEditMessage, failed }: {
  steps: NarrativeStepType[];
  selected: StudioEvent | null;
  onSelect: (e: StudioEvent) => void;
  onPermit: (jobId: string, action: "allow" | "deny") => Promise<void>;
  isLast: boolean;
  isRunning: boolean;
  expandSignal: ProcessExpandSignal;
  excludeFilePaths?: Set<string>;
  onFileChangeClick?: (path: string) => void;
  onFileAccept?: (path: string) => Promise<boolean> | void;
  onFileRevert?: (path: string) => Promise<boolean> | void;
  turnIndex?: number;
  turnDiffLabel?: string;
  onTurnDiffSelect?: (turnIndex: number) => void;
  onAggregateDiffClick?: (turnIndex: number) => void;
  compactDiff?: boolean;
  runDetail?: import("../../types").RunDetailPayload | null;
  viewMode?: import("../../hooks/useViewMode").StudioViewMode;
  onTurnRewind?: (turnIndex: number, action: string) => Promise<void>;
  onSuggestedAction?: (command: string) => Promise<void>;
  suppressSuggested?: boolean;
  onEditMessage?: (text: string) => void;
  failed?: boolean;
}) {
  const goalStep = steps[0];
  // A leading turn that has no user_message (steps before the first goal) renders goal-less:
  // no user bubble, and every step is body. Normal turns keep steps[0] as the user message.
  const isGoalTurn = goalStep?.kind === "goal";
  const restSteps = isGoalTurn ? steps.slice(1) : steps;
  const responseIndex = (() => {
    for (let index = restSteps.length - 1; index >= 0; index -= 1) {
      if (restSteps[index].kind === "final" || restSteps[index].kind === "error") return index;
    }
    return -1;
  })();
  const responseStep = responseIndex >= 0 ? restSteps[responseIndex] : null;
  const rawMiddleSteps = responseIndex >= 0 ? restSteps.filter((_, index) => index !== responseIndex) : restSteps;
  const responsePhase = responseStep?.events[0]?.phase;
  // The same-phase thinking behind a final answer is just the streamed version of that answer —
  // drop only that duplicate (chat turns) so it isn't shown twice. Reasoning in OTHER phases is
  // genuine intermediate work and is preserved into the ThinkingBlock, NOT surgically deleted on
  // completion (deleting it is what made a real run look like "thought a while, then a review").
  const hideResponseDuplicate = responseStep ? hasFinalAnswerForPhase([responseStep], responsePhase) : false;
  const thinkingSteps = rawMiddleSteps.filter(
    (step) => step.kind === "thinking" && !(hideResponseDuplicate && isModelThinkingStep(step, responsePhase))
  );
  const processSteps = rawMiddleSteps.filter((step) => step.kind !== "thinking");
  const goalEvent = goalStep?.events[0];
  const userText = goalEvent?.content_delta || goalStep?.summary || goalStep?.title || "";
  const time = goalEvent ? formatEventTime(goalEvent.created_at) : "";
  const turnRunning = isLast && isRunning && !responseStep;
  // Honesty: /run reports lifecycle "completed" but does not inline-run review, so qualify the
  // conclusion with a plain "done but not yet verified" note when the run is unverified.
  const unverifiedHint = responseStep && isLast && !isRunning ? runVerificationHint(runDetail ?? null) : "";
  // Symmetry: when the /run loop recorded a passing executable verdict, affirm it explicitly. A bare
  // "completed" with the nag merely suppressed leaves the user unsure verification even happened —
  // the positive badge closes the "completed ≠ verified" gap honestly.
  const verifiedPass = responseStep && isLast && !isRunning
    && latestCorrectnessVerdict(runDetail ?? null) === "pass";

  return (
    <div className={`conversationTurn${failed ? " failed" : ""}`} id={turnIndex ? `thread-turn-${turnIndex}` : undefined} data-failed={failed ? "true" : undefined}>
      {isGoalTurn && (
        <div className="turnUser">
          <div className="turnUserBubble">
            <p>{userText}</p>
            <span className="turnUserTime">{time}</span>
            {isLast && !isRunning && onEditMessage && userText && (
              <button
                type="button"
                className="turnUserEdit"
                title="编辑并重发——把这条消息放回输入框,作为新的一轮"
                onClick={() => onEditMessage(userText)}
              >
                <Pencil size={11} />
                <span>编辑</span>
              </button>
            )}
          </div>
        </div>
      )}
      {turnRunning ? (
        rawMiddleSteps.length === 0 ? (
          <div className="turnRunning"><Loader2 size={14} className="spinning" /><span>启动中…</span></div>
        ) : rawMiddleSteps.length === 1 && isModelThinkingStep(rawMiddleSteps[0], "chat") ? (
          <ChatStreamPreview step={rawMiddleSteps[0]} />
        ) : (
          <LiveStream
            steps={rawMiddleSteps}
            onPermit={onPermit}
            onFileChangeClick={onFileChangeClick}
            showToolStreams={!compactDiff}
            compactDiff={compactDiff}
            turnIndex={turnIndex}
            onAggregateDiffClick={onAggregateDiffClick}
            viewMode={viewMode}
          />
        )
      ) : (
        <>
          {/* Answer-first (Cursor / Claude Code): lead with the assistant's prose answer, then fold
              the reasoning + process + file cards BELOW it. Leading with process is what made the
              thread read like a dashboard instead of a reply. */}
          {responseStep && <TurnFinal step={responseStep} middleSteps={processSteps} />}
          {/* No thinking block on a completed turn (ADR-0021 whitelist): the model's real reasoning
              stream stays in the Inspector, and its conversational voice is the narration/final. The
              only thing this block ever carried on the main thread was harness placeholders / a goal
              echo — machinery, not the model's thought. Real live streaming still uses LiveStream. */}
          {processSteps.length > 0 && (
            <TurnMiddle
              steps={processSteps}
              selected={selected}
              onSelect={onSelect}
              onPermit={onPermit}
              expandSignal={expandSignal}
              onFileChangeClick={onFileChangeClick}
              onFileAccept={isLast ? onFileAccept : undefined}
              onFileRevert={isLast ? onFileRevert : undefined}
              turnIndex={turnIndex}
              turnDiffLabel={turnDiffLabel}
              onTurnDiffSelect={onTurnDiffSelect}
              onAggregateDiffClick={onAggregateDiffClick}
              compactDiff={compactDiff}
              excludeFilePaths={excludeFilePaths}
            />
          )}
        </>
      )}
      {unverifiedHint && (
        <div className="turnUnverifiedNote" role="note">{unverifiedHint}</div>
      )}
      {verifiedPass && (
        <div className="turnVerifiedNote" role="note">
          <Check size={12} />
          <span>验证通过——记录的测试/检查均已跑绿。</span>
        </div>
      )}
      {responseStep && isLast && onSuggestedAction && !suppressSuggested && (
        <SuggestedActions steps={restSteps} onAction={onSuggestedAction} />
      )}
      {turnIndex && onTurnRewind && viewMode && (
        <TurnRewindButton
          turnIndex={turnIndex}
          isLast={isLast}
          isRunning={isRunning}
          runDetail={runDetail}
          viewMode={viewMode}
          onRewind={onTurnRewind}
        />
      )}
    </div>
  );
}

