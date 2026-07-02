import React, { useEffect, useMemo, useRef, useState } from "react";
import { ThreadSkeleton } from "../../components/Skeleton";
import type { OverviewPayload, RunDetailPayload, StudioEvent } from "../../types";
import { toNarrativeEvents, buildRunNarrative } from "../../narrative";
import { splitIntoTurns } from "../../turnDiff";
import type { StudioViewMode } from "../../hooks/useViewMode";
import { RuntimeSnapshot, runtimeSnapshotActionable } from "./RuntimeSnapshot";
import { runtimeSessionEvents } from "./runtimeNarrative";
import { EmptyState } from "./EmptyState";
import { ConversationTurn, PendingTurn, type ProcessExpandSignal } from "./ConversationTurn";
import { PhaseStrip } from "./PhaseStrip";
import { PlanChecklist } from "./PlanChecklist";
import { derivePlan } from "./planModel";
import { ContextMeter } from "../../components/ContextMeter";
import { readContextUsage } from "../inspector/inspectorUtils";

// Event types that mean the session carries its OWN granular run output (a real token/tool/file
// stream), as opposed to just a user message or an intent acknowledgement. Used to decide whether
// to render the session's own rich events vs. the coarse runDetail-derived fallback.
const RUN_OUTPUT_TYPES = new Set<StudioEvent["type"]>([
  "model_start", "model_delta", "model_end", "model_error",
  "reasoning_delta", "assistant_delta",
  "tool_start", "tool_delta", "tool_end", "tool_observation",
  "file_changed", "final_answer", "error",
]);

export function Thread({
  events,
  selected,
  isRunning,
  onSelect,
  onPrompt,
  onPermit,
  onRuntimeAction,
  onOpenReview,
  onResolveDecision,
  pendingTurn,
  overview,
  runDetail,
  workspaceChangeCount,
  onFileChangeClick,
  onTurnDiffSelect,
  turnDiffLabel,
  onAggregateDiffClick,
  viewMode,
  onTurnRewind,
  loading,
}: {
  events: StudioEvent[];
  selected: StudioEvent | null;
  isRunning: boolean;
  loading?: boolean;
  onSelect: (event: StudioEvent) => void;
  onPrompt: (text: string) => void;
  onPermit: (jobId: string, action: "allow" | "deny") => Promise<void>;
  onRuntimeAction: (nextAction: string) => Promise<void>;
  onOpenReview: () => Promise<void>;
  onResolveDecision: (runId: string, decisionId: string, optionId: string) => Promise<void>;
  pendingTurn?: { message: string; mode: string; startedAt: number } | null;
  overview?: OverviewPayload | null;
  runDetail?: RunDetailPayload | null;
  workspaceChangeCount?: number;
  onFileChangeClick?: (path: string) => void;
  onTurnDiffSelect?: (turnIndex: number) => void;
  turnDiffLabel?: (turnIndex: number) => string;
  onAggregateDiffClick?: (turnIndex: number) => void;
  viewMode: StudioViewMode;
  onTurnRewind?: (turnIndex: number, action: string) => Promise<void>;
}) {
  const threadRef = useRef<HTMLElement>(null);
  const [expandSignal, setExpandSignal] = useState<ProcessExpandSignal>(null);
  const compactDiff = viewMode === "focus";
  const mainEvents = useMemo(() => events.filter((event) => !event.display_level || event.display_level === "main"), [events]);
  const shouldShowPending = Boolean(pendingTurn) && !mainEvents.some((event) =>
    event.type === "user_message" && event.content_delta === pendingTurn?.message
  );
  const runtimeEvents = useMemo(() => runtimeSessionEvents(runDetail ?? null), [runDetail]);
  const selectedRunId = String(runDetail?.run_id ?? "");
  const hasSelectedRunEvents = Boolean(selectedRunId) && mainEvents.some((event) => String(event.run_id ?? "") === selectedRunId);
  // Whether the session already carries its OWN granular run output (streamed model/tool/file/final
  // events, or projected transcript steps). This is the key liveness signal: those events hold the
  // real token stream. runtimeSessionEvents (the coarse fallback) drops every event without a
  // transcript_kind, so it can only ever show phase labels ("Thinking"/"Checking the work") + the
  // final — never the streamed text. So whenever the session owns run output we MUST prefer it.
  const hasOwnRunOutput = useMemo(
    () => mainEvents.some((event) => RUN_OUTPUT_TYPES.has(event.type) || Boolean(event.transcript_kind)),
    [mainEvents]
  );
  // Selection order:
  //  - empty session => empty thread (never render another session's / the workspace's run).
  //  - session owns run output (matching run_id, OR its own streamed/tool/final events) => render it,
  //    so the real token stream shows instead of decaying to coarse phase labels. This fixes the
  //    "thought for a long time, not a single word, then a review" report: run_id linkage can be
  //    absent/mismatched, but the session's own events.jsonl still holds the deltas.
  //  - otherwise (thin session shell + a runDetail run that lives elsewhere) => coarse runtimeEvents.
  const sessionEvents = mainEvents.length === 0
    ? mainEvents
    : hasSelectedRunEvents || hasOwnRunOutput || !runtimeEvents.length
      ? mainEvents
      : runtimeEvents;
  // Plan/phase "spine" for the current run (I3). Derived from the run's real task_plan + the latest
  // event phase; only shown when the session actually owns this run's output (never a foreign run).
  const ownsRun = hasSelectedRunEvents || hasOwnRunOutput;
  const plan = useMemo(() => (ownsRun ? derivePlan(runDetail ?? null) : null), [ownsRun, runDetail]);
  const contextUsage = useMemo(() => (ownsRun ? readContextUsage(runDetail ?? null) : null), [ownsRun, runDetail]);
  const currentPhase = useMemo(() => {
    for (let i = sessionEvents.length - 1; i >= 0; i -= 1) {
      const p = sessionEvents[i]?.phase;
      if (p) return p;
    }
    return undefined;
  }, [sessionEvents]);
  const narrativeEvents = useMemo(() => toNarrativeEvents(sessionEvents), [sessionEvents]);
  const narrative = useMemo(() => buildRunNarrative(narrativeEvents), [narrativeEvents]);
  const turns = useMemo(() => splitIntoTurns(narrative.steps), [narrative.steps]);
  const hasProcessBlocks = turns.some((turn) => turn.length > 2 || (turn.length > 1 && turn.at(-1)?.kind !== "final" && turn.at(-1)?.kind !== "error"));
  const showProcessControls = viewMode === "verbose" && hasProcessBlocks;
  // The bottom Next-action bar is the authoritative next-step surface. When it owns a next step,
  // suppress the last turn's inline SuggestedActions so the thread shows one prompt, not two that
  // can disagree (stale "Decide" chip vs. a run that already passed review and is ready to Accept).
  const snapshotOwnsNextStep = runtimeSnapshotActionable(overview ?? null, runDetail ?? null, events);

  useEffect(() => {
    const el = threadRef.current;
    if (!el) return;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 220;
    if (nearBottom || isRunning) {
      const smooth = !window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
      requestAnimationFrame(() => {
        el.scrollTo({ top: el.scrollHeight, behavior: smooth ? "smooth" : "auto" });
      });
    }
  }, [mainEvents.length, isRunning]);

  if (!turns.length && !shouldShowPending) {
    return (
      <section className="thread" ref={threadRef}>
        {/* A brand-new / empty session shows only the welcome prompt — never the workspace-level
            RuntimeSnapshot. That "next action / review" bar belongs to a session that has actually
            run something; surfacing another task's leftover review/finalize state (and runtime
            vocabulary) at the top of an empty conversation is confusing and violates AGENTS.md §9.
            The header "Review N" chip already signals unhandled workspace changes. */}
        {/* During bootstrap, sessions/runs are still loading — show a quiet placeholder instead of
            the "What would you like to do?" prompt, which would otherwise flash before the
            transcript populates. Once loading settles and there is genuinely nothing, the prompt shows. */}
        {loading ? (
          <ThreadSkeleton />
        ) : (
          <EmptyState onPrompt={onPrompt} />
        )}
      </section>
    );
  }

  return (
    <section className="thread" ref={threadRef}>
      {(plan || contextUsage) && (
        <div className="threadPlanBar">
          {plan && <PhaseStrip phase={currentPhase} running={isRunning} />}
          {plan && <PlanChecklist plan={plan} defaultOpen={isRunning} />}
          {contextUsage && <ContextMeter usage={contextUsage} />}
        </div>
      )}
      {showProcessControls && (
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
          onFileChangeClick={onFileChangeClick}
          turnIndex={i + 1}
          turnDiffLabel={turnDiffLabel?.(i + 1)}
          onTurnDiffSelect={onTurnDiffSelect}
          onAggregateDiffClick={onAggregateDiffClick}
          compactDiff={compactDiff}
          runDetail={runDetail}
          viewMode={viewMode}
          onTurnRewind={onTurnRewind}
          onSuggestedAction={onRuntimeAction}
          suppressSuggested={snapshotOwnsNextStep}
        />
      ))}
      {shouldShowPending && pendingTurn && <PendingTurn {...pendingTurn} />}
      <RuntimeSnapshot
        overview={overview ?? null}
        runDetail={runDetail ?? null}
        workspaceChangeCount={workspaceChangeCount}
        events={events}
        onRuntimeAction={onRuntimeAction}
        onOpenReview={onOpenReview}
        onResolveDecision={onResolveDecision}
      />
    </section>
  );
}
