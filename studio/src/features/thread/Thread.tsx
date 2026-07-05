import React, { useEffect, useMemo, useRef, useState } from "react";
import { RefreshCw, AlertTriangle } from "lucide-react";
import { ThreadSkeleton } from "../../components/Skeleton";
import type { OverviewPayload, RunDetailPayload, StudioEvent } from "../../types";
import { toNarrativeEvents, buildRunNarrative } from "../../narrative";
import { splitIntoTurns } from "../../turnDiff";
import { extractFileChangesFromSteps } from "../../fileChanges";
import type { StudioViewMode } from "../../hooks/useViewMode";
import { RuntimeSnapshot, runtimeSnapshotActionable } from "./RuntimeSnapshot";
import { runtimeSessionEvents } from "./runtimeNarrative";
import { EmptyState } from "./EmptyState";
import { ConversationTurn, PendingTurn, type ProcessExpandSignal } from "./ConversationTurn";
import { PhaseStrip } from "./PhaseStrip";
import { PlanChecklist } from "./PlanChecklist";
import { derivePlan } from "./planModel";

// Event types that mean the session carries its OWN granular run output (a real token/tool/file
// stream), as opposed to just a user message or an intent acknowledgement. Used to decide whether
// to render the session's own rich events vs. the coarse runDetail-derived fallback.
const RUN_OUTPUT_TYPES = new Set<StudioEvent["type"]>([
  "model_start", "model_delta", "model_end", "model_error",
  "reasoning_delta", "assistant_delta",
  "tool_start", "tool_delta", "tool_end", "tool_observation",
  "file_changed", "final_answer", "error",
]);

// Cap the number of fully-rendered turns so a very long run bounds the DOM node count and stays at
// 60fps (I7). Older turns render nothing until the user asks for them; the on-disk transcript keeps
// everything. This is what keeps opening a long-running session from freezing the tab.
const MAX_RENDERED_TURNS = 60;

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
  onAnswerDecision,
  pendingTurn,
  overview,
  runDetail,
  workspaceChangeCount,
  onFileChangeClick,
  onFileAccept,
  onFileRevert,
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
  onAnswerDecision?: (runId: string, decisionId: string, answer: string) => Promise<void>;
  pendingTurn?: { message: string; mode: string; startedAt: number } | null;
  overview?: OverviewPayload | null;
  runDetail?: RunDetailPayload | null;
  workspaceChangeCount?: number;
  onFileChangeClick?: (path: string) => void;
  onFileAccept?: (path: string) => Promise<boolean> | void;
  onFileRevert?: (path: string) => Promise<boolean> | void;
  onTurnDiffSelect?: (turnIndex: number) => void;
  turnDiffLabel?: (turnIndex: number) => string;
  onAggregateDiffClick?: (turnIndex: number) => void;
  viewMode: StudioViewMode;
  onTurnRewind?: (turnIndex: number, action: string) => Promise<void>;
}) {
  const threadRef = useRef<HTMLElement>(null);
  const [expandSignal, setExpandSignal] = useState<ProcessExpandSignal>(null);
  const [showEarlier, setShowEarlier] = useState(false);
  const [atBottom, setAtBottom] = useState(true);
  const atBottomRef = useRef(true);
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
  const currentPhase = useMemo(() => {
    for (let i = sessionEvents.length - 1; i >= 0; i -= 1) {
      const p = sessionEvents[i]?.phase;
      if (p) return p;
    }
    return undefined;
  }, [sessionEvents]);
  // Live auto-repair progress (S78). The per-attempt events are inspector-level (kept out of the
  // main narrative to keep the thread compact), so read them from the full `events` — not
  // mainEvents. Show a summary chip only while running and only when a repair attempt is the current
  // tail activity: scanning from the newest event, bail if a success/final lands after the last
  // attempt so the chip never lingers once the repair resolved.
  const repairProgress = useMemo(() => {
    if (!isRunning) return null;
    for (let i = events.length - 1; i >= 0; i -= 1) {
      const ev = events[i];
      const data = (ev?.data ?? {}) as Record<string, unknown>;
      if (typeof data.auto_repair_attempt === "number") {
        return { attempt: data.auto_repair_attempt, budget: Number(data.auto_repair_budget ?? 0) };
      }
      if (ev?.type === "final_answer" || ev?.runtime_event_type === "final_report") return null;
    }
    return null;
  }, [events, isRunning]);
  const narrativeEvents = useMemo(() => toNarrativeEvents(sessionEvents), [sessionEvents]);
  const narrative = useMemo(() => buildRunNarrative(narrativeEvents), [narrativeEvents]);
  const turns = useMemo(() => splitIntoTurns(narrative.steps), [narrative.steps]);
  // Files are deliverables, not per-message noise: once a file has been shown in an earlier turn it
  // must not reappear as a "changed file" in every later turn (the event stream re-emits the same
  // file_change many times across a resumed/multi-goal run). Precompute each turn's file paths so a
  // turn can hide files already shown above it — each turn surfaces only what it newly touched.
  const turnFilePaths = useMemo(
    () => turns.map((turnSteps) => extractFileChangesFromSteps(turnSteps).map((change) => change.path)),
    [turns],
  );
  // B1: failed-turn markers + issue navigator. A turn "failed" if any of its steps errored or carries
  // a failed status (a tool that broke, a repair that gave up). In a long run these get buried in the
  // scrollback; we mark each turn and give a pill that cycles focus through them (1-based turn numbers
  // to match the turnIndex passed to ConversationTurn).
  const failedTurnNumbers = useMemo(() => {
    const nums: number[] = [];
    turns.forEach((turnSteps, i) => {
      if (turnSteps.some((s) => s.kind === "error" || s.status === "failed")) nums.push(i + 1);
    });
    return nums;
  }, [turns]);
  const [issueCursor, setIssueCursor] = useState(0);
  const hasProcessBlocks = turns.some((turn) => turn.length > 2 || (turn.length > 1 && turn.at(-1)?.kind !== "final" && turn.at(-1)?.kind !== "error"));
  const showProcessControls = viewMode === "verbose" && hasProcessBlocks;
  // The bottom Next-action bar is the authoritative next-step surface. When it owns a next step,
  // suppress the last turn's inline SuggestedActions so the thread shows one prompt, not two that
  // can disagree (stale "Decide" chip vs. a run that already passed review and is ready to Accept).
  const snapshotOwnsNextStep = runtimeSnapshotActionable(overview ?? null, runDetail ?? null, events);

  // Track whether the viewport is pinned to the live edge, so we (a) never yank a user who scrolled
  // up back to the bottom, and (b) can show a "Jump to latest" affordance (I7).
  useEffect(() => {
    const el = threadRef.current;
    if (!el) return;
    const onScroll = () => {
      const near = el.scrollHeight - el.scrollTop - el.clientHeight < 220;
      atBottomRef.current = near;
      setAtBottom(near);
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
    return () => el.removeEventListener("scroll", onScroll);
  }, []);

  // Auto-follow only while pinned to the bottom (read via ref to avoid a scroll↔state feedback loop).
  useEffect(() => {
    const el = threadRef.current;
    if (!el || !atBottomRef.current) return;
    const smooth = !window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    requestAnimationFrame(() => {
      el.scrollTo({ top: el.scrollHeight, behavior: smooth ? "smooth" : "auto" });
    });
  }, [mainEvents.length, isRunning]);

  // Reset the "load earlier" reveal and issue cursor when switching to a different run/session.
  useEffect(() => { setShowEarlier(false); setIssueCursor(0); }, [selectedRunId]);

  const hiddenTurnCount = showEarlier ? 0 : Math.max(0, turns.length - MAX_RENDERED_TURNS);
  const visibleTurns = hiddenTurnCount > 0 ? turns.slice(-MAX_RENDERED_TURNS) : turns;
  const turnIndexOffset = turns.length - visibleTurns.length;
  const scrollToLatest = () => {
    const el = threadRef.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  };
  const jumpToIssue = () => {
    if (!failedTurnNumbers.length) return;
    const turnNo = failedTurnNumbers[issueCursor % failedTurnNumbers.length];
    const focus = () => {
      const el = threadRef.current?.querySelector<HTMLElement>(`#thread-turn-${turnNo}`);
      el?.scrollIntoView({ behavior: "smooth", block: "center" });
      el?.classList.add("issueFlash");
      window.setTimeout(() => el?.classList.remove("issueFlash"), 1200);
    };
    // A failed turn can be inside the windowed-out earlier region — reveal it first, then focus after
    // React has committed the fuller list.
    if (turnNo <= turnIndexOffset && !showEarlier) {
      setShowEarlier(true);
      window.setTimeout(focus, 60);
    } else {
      requestAnimationFrame(focus);
    }
    setIssueCursor((c) => c + 1);
  };

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
      {/* The plan checklist is the loop's spine — the persistent, self-ticking task list that makes
          a long autonomous run legible (Claude Code todos, Manus todo.md, Replit task list). It stays
          visible after completion so the finished plan reads as "what got done". The phase strip is
          live-progress only, so it shows while running and folds away when done. */}
      {(plan || repairProgress) && (
        <div className="threadPlanBar">
          {plan && isRunning && <PhaseStrip phase={currentPhase} running={isRunning} />}
          {repairProgress && (
            <span className="repairProgressChip" role="status" aria-live="polite">
              <RefreshCw size={12} className="spinning" />
              自动修复中 · 第 {repairProgress.attempt} 次尝试
              {repairProgress.budget > 0 ? ` / ${repairProgress.budget}` : ""}
            </span>
          )}
          {plan && <PlanChecklist plan={plan} defaultOpen={isRunning} />}
        </div>
      )}
      {showProcessControls && (
        <div className="threadProcessControls" aria-label="过程显示控制">
          <button type="button" onClick={() => setExpandSignal({ mode: "expand", id: Date.now() })}>展开过程</button>
          <button type="button" onClick={() => setExpandSignal({ mode: "collapse", id: Date.now() })}>收起过程</button>
        </div>
      )}
      {hiddenTurnCount > 0 && (
        <button type="button" className="loadEarlierTurns" onClick={() => setShowEarlier(true)}>
          加载更早的 {hiddenTurnCount} 轮
        </button>
      )}
      {visibleTurns.map((turnSteps, i) => {
        const globalIndex = turnIndexOffset + i;
        // Files already shown in any earlier turn — this turn hides them so a file appears once,
        // in the turn that first changed it, instead of repeating down the whole thread.
        const priorFilePaths = new Set(turnFilePaths.slice(0, globalIndex).flat());
        return (
          <ConversationTurn
            key={turnSteps[0].id}
            steps={turnSteps}
            excludeFilePaths={priorFilePaths}
            selected={selected}
            onSelect={onSelect}
            onPermit={onPermit}
            isLast={globalIndex === turns.length - 1}
            isRunning={isRunning}
            expandSignal={expandSignal}
            onFileChangeClick={onFileChangeClick}
            onFileAccept={onFileAccept}
            onFileRevert={onFileRevert}
            turnIndex={globalIndex + 1}
            turnDiffLabel={turnDiffLabel?.(globalIndex + 1)}
            onTurnDiffSelect={onTurnDiffSelect}
            onAggregateDiffClick={onAggregateDiffClick}
            compactDiff={compactDiff}
            runDetail={runDetail}
            viewMode={viewMode}
            onTurnRewind={onTurnRewind}
            onSuggestedAction={onRuntimeAction}
            suppressSuggested={snapshotOwnsNextStep}
            onEditMessage={onPrompt}
            failed={failedTurnNumbers.includes(globalIndex + 1)}
          />
        );
      })}
      {failedTurnNumbers.length > 0 && (
        <button
          type="button"
          className="issueNav"
          onClick={jumpToIssue}
          aria-label={`跳到下一个问题（共 ${failedTurnNumbers.length} 个）`}
          title="跳到下一个失败的轮次"
        >
          <AlertTriangle size={12} />
          {failedTurnNumbers.length} 个问题
        </button>
      )}
      {!atBottom && (
        <button type="button" className="jumpToLatest" onClick={scrollToLatest} aria-label="跳到最新">
          跳到最新 ↓
        </button>
      )}
      {shouldShowPending && pendingTurn && <PendingTurn {...pendingTurn} />}
      <RuntimeSnapshot
        overview={overview ?? null}
        runDetail={runDetail ?? null}
        workspaceChangeCount={workspaceChangeCount}
        events={events}
        onRuntimeAction={onRuntimeAction}
        onOpenReview={onOpenReview}
        onResolveDecision={onResolveDecision}
        onAnswerDecision={onAnswerDecision}
      />
    </section>
  );
}
