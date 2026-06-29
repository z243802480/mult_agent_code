import React, { useEffect, useMemo, useRef, useState } from "react";
import { Loader2 } from "lucide-react";
import type { OverviewPayload, RunDetailPayload, StudioEvent } from "../../types";
import { toNarrativeEvents, buildRunNarrative } from "../../narrative";
import { splitIntoTurns } from "../../turnDiff";
import type { StudioViewMode } from "../../hooks/useViewMode";
import { RuntimeSnapshot, runtimeSnapshotActionable } from "./RuntimeSnapshot";
import { runtimeSessionEvents } from "./runtimeNarrative";
import { EmptyState } from "./EmptyState";
import { ConversationTurn, PendingTurn, type ProcessExpandSignal } from "./ConversationTurn";

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
  const sessionEvents = hasSelectedRunEvents || !runtimeEvents.length ? mainEvents : runtimeEvents;
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
    if (nearBottom || isRunning) requestAnimationFrame(() => { el.scrollTop = el.scrollHeight; });
  }, [mainEvents.length, isRunning]);

  if (!turns.length && !shouldShowPending) {
    return (
      <section className="thread" ref={threadRef}>
        <RuntimeSnapshot
          overview={overview ?? null}
          runDetail={runDetail ?? null}
          workspaceChangeCount={workspaceChangeCount}
          events={events}
          onRuntimeAction={onRuntimeAction}
          onOpenReview={onOpenReview}
          onResolveDecision={onResolveDecision}
        />
        {/* During bootstrap, sessions/runs are still loading — show a quiet placeholder instead of
            the "What would you like to do?" prompt, which would otherwise flash before the
            transcript populates. Once loading settles and there is genuinely nothing, the prompt shows. */}
        {loading ? (
          <div className="turnRunning"><Loader2 size={14} className="spinning" /><span>Loading session…</span></div>
        ) : (
          <EmptyState onPrompt={onPrompt} />
        )}
      </section>
    );
  }

  return (
    <section className="thread" ref={threadRef}>
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
