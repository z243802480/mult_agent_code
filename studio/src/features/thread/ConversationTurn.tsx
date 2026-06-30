import React, { useEffect, useState } from "react";
import { ChevronRight, Loader2, Wrench } from "lucide-react";
import type { NarrativeStep as NarrativeStepType, StudioEvent } from "../../types";
import { NarrativeStep } from "../../components/NarrativeStep";
import { PermissionCard } from "../../components/PermissionCard";
import { ClampedOutput } from "../../components/ClampedOutput";
import { AggregateDiffChip } from "../../components/AggregateDiffChip";
import { FileChangeChips } from "../../components/FileChangeChips";
import { extractFileChangesFromSteps, aggregateFileChangeStats } from "../../fileChanges";
import { LiveStream } from "./LiveStream";
import { TurnFinal } from "./TurnFinal";
import { SuggestedActions } from "./SuggestedActions";
import { TurnRewindButton } from "./TurnRewindButton";
import { middleRepresentativeEvent, middleSummary, hasFinalAnswerForPhase, isModelThinkingStep } from "./turnHelpers";
import { formatEventTime } from "./threadUtils";

export type ProcessExpandSignal = { mode: "expand" | "collapse"; id: number } | null;

function TurnMiddle({ steps, selected, onSelect, onPermit, expandSignal, onFileChangeClick, turnIndex, turnDiffLabel, onTurnDiffSelect, onAggregateDiffClick, compactDiff }: {
  steps: NarrativeStepType[];
  selected: StudioEvent | null;
  onSelect: (e: StudioEvent) => void;
  onPermit: (jobId: string, action: "allow" | "deny") => Promise<void>;
  expandSignal: ProcessExpandSignal;
  onFileChangeClick?: (path: string) => void;
  turnIndex?: number;
  turnDiffLabel?: string;
  onTurnDiffSelect?: (turnIndex: number) => void;
  onAggregateDiffClick?: (turnIndex: number) => void;
  compactDiff?: boolean;
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
  const fileChanges = extractFileChangesFromSteps(steps);
  const fileStats = aggregateFileChangeStats(fileChanges);

  if (compactDiff) {
    return (
      <div className="turnMiddle compact">
        {fileStats.files > 0 && (
          <div className="turnFileRowWrap">
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

  return (
    <div className="turnMiddle">
      <button
        className={`turnMiddleBadge ${open ? "open" : ""} ${selectedInMiddle ? "selected" : ""}`}
        onClick={() => {
          setOpen((o) => !o);
          if (representative) onSelect(representative);
        }}
      >
        <ChevronRight size={13} className={`chevron ${open ? "open" : ""}`} />
        <Wrench size={11} />
        <span>{middleSummary(steps)}</span>
      </button>
      <div className="turnFileRowWrap">
        <AggregateDiffChip
          files={fileStats.files}
          additions={fileStats.additions}
          deletions={fileStats.deletions}
          onClick={turnIndex && onAggregateDiffClick ? () => onAggregateDiffClick(turnIndex) : undefined}
        />
        <FileChangeChips changes={fileChanges} className="turnFileRow" onSelect={onFileChangeClick} />
        {turnIndex && fileChanges.length > 0 && onTurnDiffSelect && (
          <button type="button" className="turnDiffButton" onClick={() => onTurnDiffSelect(turnIndex)}>
            {turnDiffLabel ?? `T${turnIndex}`} diff · {fileChanges.length}
          </button>
        )}
      </div>
      <div className={`turnMiddleStepsWrap ${open ? "open" : ""}`}>
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
      </div>
    </div>
  );
}

function ChatStreamPreview({ step }: { step: NarrativeStepType }) {
  const event = step.events.at(-1) || step.events[0];
  // Honest streaming: render the real content_delta exactly as events land. No client-side
  // typewriter — perceived latency tracks the runtime transport, not an artificial timer.
  const text = step.events.map((item) => item.content_delta || "").join("");
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
      {text ? (
        <ClampedOutput text={text} maxLines={8} />
      ) : (
        <p>Waiting for the first response...</p>
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

  const phase = mode === "auto"
    ? "Intent routing"
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

export function ConversationTurn({ steps, selected, onSelect, onPermit, isLast, isRunning, expandSignal, onFileChangeClick, turnIndex, turnDiffLabel, onTurnDiffSelect, onAggregateDiffClick, compactDiff, runDetail, viewMode, onTurnRewind, onSuggestedAction, suppressSuggested }: {
  steps: NarrativeStepType[];
  selected: StudioEvent | null;
  onSelect: (e: StudioEvent) => void;
  onPermit: (jobId: string, action: "allow" | "deny") => Promise<void>;
  isLast: boolean;
  isRunning: boolean;
  expandSignal: ProcessExpandSignal;
  onFileChangeClick?: (path: string) => void;
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
  const hideCompletedModelStream = responseStep ? hasFinalAnswerForPhase([responseStep], responsePhase) : false;
  const middleSteps = hideCompletedModelStream
    ? rawMiddleSteps.filter((step) => !isModelThinkingStep(step, responsePhase))
    : rawMiddleSteps;
  const goalEvent = goalStep?.events[0];
  const userText = goalEvent?.content_delta || goalStep?.summary || goalStep?.title || "";
  const time = goalEvent ? formatEventTime(goalEvent.created_at) : "";
  const turnRunning = isLast && isRunning && !responseStep;

  return (
    <div className="conversationTurn">
      {isGoalTurn && (
        <div className="turnUser">
          <div className="turnUserBubble">
            <p>{userText}</p>
            <span className="turnUserTime">{time}</span>
          </div>
        </div>
      )}
      {turnRunning ? (
        middleSteps.length === 0 ? (
          <div className="turnRunning"><Loader2 size={14} className="spinning" /><span>Starting...</span></div>
        ) : middleSteps.length === 1 && isModelThinkingStep(middleSteps[0], "chat") ? (
          <ChatStreamPreview step={middleSteps[0]} />
        ) : (
          <LiveStream
            steps={middleSteps}
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
        middleSteps.length > 0 && (
          <TurnMiddle
            steps={middleSteps}
            selected={selected}
            onSelect={onSelect}
            onPermit={onPermit}
            expandSignal={expandSignal}
            onFileChangeClick={onFileChangeClick}
            turnIndex={turnIndex}
            turnDiffLabel={turnDiffLabel}
            onTurnDiffSelect={onTurnDiffSelect}
            onAggregateDiffClick={onAggregateDiffClick}
            compactDiff={compactDiff}
          />
        )
      )}
      {responseStep && <TurnFinal step={responseStep} middleSteps={middleSteps} />}
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

