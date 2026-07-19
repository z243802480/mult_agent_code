import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { AnyRecord, StudioEvent, StudioSession } from "../types";
import { api, subscribeToEvents, type ConnectivityStatus } from "../api";
import { isSessionLive } from "../narrative";
import { latestActiveEvent } from "../features/thread/runtimeNarrative";
import { mergeEventLists } from "./eventUtils";
import { deriveRunState } from "./runState";
import { toast } from "../components/toast";

/** How often we ask the server whether the job is still alive while the events look live. */
const JOB_PROBE_INTERVAL_MS = 4000;

export function useSessionEvents(
  activeSession: StudioSession | null,
  sessions: StudioSession[],
  setSessions: (sessions: StudioSession[]) => void,
) {
  const [events, setEvents] = useState<StudioEvent[]>([]);
  const [pendingTurn, setPendingTurn] = useState<{
    message: string;
    mode: string;
    startedAt: number;
  } | null>(null);
  const [connectivity, setConnectivity] = useState<ConnectivityStatus>("live");
  // Whether this session's transcript has been read at least once. Before it has, `isRunning` is
  // false only because we have not looked yet — consumers that act on "not running" (the composer
  // flushing its restored queue) must wait, or they would fire a message into a live run.
  const [runStateKnown, setRunStateKnown] = useState(false);
  const unsubRef = useRef<(() => void) | null>(null);
  // Per-session event cache (I6): switching back to a session restores its events instantly instead
  // of flashing to [] and re-reading the whole transcript. The on-disk JSONL stays the source of
  // truth — this is a UI accelerator; a background refresh + the live subscription reconcile drift.
  const cacheRef = useRef<Map<string, StudioEvent[]>>(new Map());
  const latestEventsRef = useRef<StudioEvent[]>([]);
  latestEventsRef.current = events;

  const mergeEvents = useCallback((incoming: StudioEvent[]) => {
    setEvents((prev) => mergeEventLists(prev, incoming));
  }, []);

  useEffect(() => {
    if (!activeSession) return;
    const sid = activeSession.session_id;
    setEvents(cacheRef.current.get(sid) ?? []);
    setConnectivity("live");
    setRunStateKnown(false);
    void api
      .events(sid)
      .then((data) => mergeEvents(data.events ?? []))
      .catch(() => {})
      .finally(() => setRunStateKnown(true));
    unsubRef.current?.();
    unsubRef.current = subscribeToEvents(sid, mergeEvents, setConnectivity);
    return () => {
      // Persist the latest events for the session being left so returning to it is instant.
      cacheRef.current.set(sid, latestEventsRef.current);
      unsubRef.current?.();
      unsubRef.current = null;
    };
  }, [activeSession?.session_id, mergeEvents]);

  // The event log is a hint; the server's job registry is the authority (see runState.ts).
  const eventsLive = useMemo(() => isSessionLive(events), [events]);
  // The loop is parked on the user: the latest still-active signal is a permission/decision gate
  // awaiting your approval (isSessionLive already treats waiting_user as live). This is a deliberate
  // pause, so we report "waiting", not the warn-toned "interrupted" a jobs-registry miss would give.
  const waitingForUser = useMemo(
    () => latestActiveEvent(events)?.status === "waiting_user",
    [events],
  );
  const [jobsRunning, setJobsRunning] = useState<number | null>(null);
  const [staleChecks, setStaleChecks] = useState(0);
  // A settled run (job terminal in the registry, none running) is finishing cleanly, not dead — this
  // suppresses the false "已中断" flash during the completion race. See deriveRunState.
  const [settled, setSettled] = useState(false);

  useEffect(() => {
    // Probe while EITHER signal says (or could say) a run is alive. Gating on eventsLive alone
    // stopped the probe the moment the event hint misread a grinding run as dead — so the registry
    // (the authority, per runState.ts) was never even consulted during exactly the window it was
    // needed (F2/F3, dogfood replay 2026-07-19). `jobsRunning === null` (never asked / last ask
    // failed) also probes, so a session opened mid-run learns the truth on the first tick.
    const registryMayBeLive = jobsRunning === null || jobsRunning > 0;
    if (!activeSession || (!eventsLive && !registryMayBeLive)) {
      setStaleChecks(0);
      return;
    }
    const sid = activeSession.session_id;
    let cancelled = false;
    const probe = async () => {
      try {
        const payload = await api.sessionJobs(sid);
        if (cancelled) return;
        const running = typeof payload.running === "number" ? payload.running : 0;
        setJobsRunning(running);
        setSettled(Boolean(payload.settled));
        // Consecutive-miss counter, not a one-shot: a job that finishes normally drops out of the
        // running set a beat before its final event lands, and that beat must not read as death.
        setStaleChecks((seen) => (running > 0 ? 0 : seen + 1));
      } catch {
        if (cancelled) return;
        // Could not ask ≠ the run died. Fall back to the event signal.
        setJobsRunning(null);
        setSettled(false);
        setStaleChecks(0);
      }
    };
    void probe();
    const timer = setInterval(() => void probe(), JOB_PROBE_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
    // jobsRunning is a dep on purpose: its 0↔N/null transitions open and close the probe window
    // (steady-state probes set the same value, so no effect churn between transitions).
  }, [activeSession?.session_id, eventsLive, jobsRunning]);

  const runState = deriveRunState({
    eventsLive,
    jobsRunning,
    staleChecks,
    waitingForUser,
    settled,
  });
  const isRunning = runState === "running";
  const interrupted = runState === "interrupted";
  const waiting = runState === "waiting";

  const resetRunProbe = useCallback(() => {
    setJobsRunning(null);
    setSettled(false);
    setStaleChecks(0);
  }, []);

  async function sendGoal(
    message: string,
    mode: string,
    permission: string,
    permissionMode?: string,
    attachments?: string[],
  ): Promise<boolean> {
    if (!activeSession) return false;
    // A new goal supersedes any earlier verdict about a dead job — re-probe from scratch.
    resetRunProbe();
    setPendingTurn({ message, mode, startedAt: Date.now() });
    try {
      await api.send(
        activeSession.session_id,
        message,
        mode,
        permission,
        undefined,
        permissionMode,
        attachments,
      );
      const refreshed = await api.sessions();
      setSessions(refreshed.sessions ?? []);
      return true;
    } catch {
      // Never silently swallow a failed send — the message was NOT delivered. Offer a Retry that
      // re-sends the exact text (so the draft is not lost) instead of clearing it into the void.
      toast.error("无法发送你的消息——它未被送达。", {
        action: {
          label: "重试",
          onClick: () => void sendGoal(message, mode, permission, permissionMode, attachments),
        },
      });
      return false;
    } finally {
      setPendingTurn(null);
    }
  }

  async function sendSideAsk(message: string) {
    if (!activeSession) return;
    try {
      await api.send(activeSession.session_id, message, "chat", "ask", "side");
    } catch {
      toast.error("无法发送——侧边提问未被送达。", {
        action: { label: "重试", onClick: () => void sendSideAsk(message) },
      });
    }
  }

  async function permitJob(jobId: string, action: "allow" | "deny") {
    if (!activeSession) return;
    try {
      await api.permitJob(activeSession.session_id, jobId, action);
    } catch {
      toast.error(`无法记录你的${action === "allow" ? "批准" : "拒绝"}——请重试。`);
    }
  }

  async function stopRun() {
    if (!activeSession) return;
    try {
      await api.stopSession(activeSession.session_id);
    } catch {
      // Never let Stop fail in silence — the run may still be going and the user needs to know.
      toast.error("无法停止运行——请重试。");
    }
    const eventData = await api
      .events(activeSession.session_id)
      .catch(() => ({ events: [] as StudioEvent[] }));
    mergeEvents(eventData.events ?? []);
  }

  async function pauseRun() {
    if (!activeSession) return;
    try {
      const result = await api.pauseSession(activeSession.session_id);
      if (result?.ok) {
        // Honest wording: this is a REQUEST. The run keeps going until it reaches a turn boundary —
        // we never cut a tool batch in half. Claiming "已暂停" the instant the button is clicked would
        // be a lie for however long the current step takes.
        toast.success("已请求暂停——它会在当前这一步做完后停下。");
      } else {
        toast.error(String(result?.error || "无法暂停——请重试。"));
      }
    } catch {
      toast.error("无法暂停——请重试。");
    }
  }

  async function steerRun(instruction: string): Promise<boolean> {
    if (!activeSession) return false;
    try {
      const result = await api.steerSession(activeSession.session_id, instruction);
      if (result?.ok) {
        // Honest wording: like pause, this is delivered at a turn boundary, not this instant. The
        // running step finishes first; the model sees the instruction on its next turn.
        toast.success("已发给运行中的任务——它会在下一轮开始时收到。");
        return true;
      }
      toast.error(String(result?.error || "无法发送——请重试。"));
      return false;
    } catch {
      toast.error("无法发送——请重试。");
      return false;
    }
  }

  async function runRuntimeAction(nextAction: string): Promise<AnyRecord> {
    if (!activeSession) return { ok: false };
    let result: AnyRecord;
    try {
      // These actions are ALL triggered by an explicit user click (Review / Accept / Decide /
      // Continue / a suggested-action chip). The click IS the approval, so send permission="allow":
      // sending "ask" made the server append a SECOND permission card and NOT run the action, while
      // the caller still reported success — the "标记完成 lies" bug. (Explicit click = consent.)
      result = await api.runtimeAction(activeSession.session_id, nextAction, "allow");
    } catch {
      toast.error("无法启动该操作——请重试。", {
        action: { label: "重试", onClick: () => void runRuntimeAction(nextAction) },
      });
      return { ok: false };
    }
    // Server rejections come back as {ok:false} with HTTP 200 (no throw). Surface them instead of
    // clearing the spinner and silently doing nothing.
    if (!result?.ok) {
      toast.error(`该操作未能执行${result?.error ? `：${result.error}` : ""}。`);
      return result;
    }
    const [eventData, refreshed] = await Promise.all([
      api.events(activeSession.session_id).catch(() => ({ events: [] as StudioEvent[] })),
      api.sessions().catch(() => ({ sessions })),
    ]);
    mergeEvents(eventData.events ?? []);
    setSessions(refreshed.sessions ?? sessions);
    return result;
  }

  async function resolveDecision(
    runId: string,
    decisionId: string,
    optionId: string,
    setRunDetail: (detail: Awaited<ReturnType<typeof api.runDetail>> | null) => void,
  ) {
    if (!activeSession) return;
    try {
      await api.resolveDecision(activeSession.session_id, runId, decisionId, optionId);
    } catch {
      toast.error("无法提交你的选择——请重试。");
      return;
    }
    const [eventData, refreshed] = await Promise.all([
      api.events(activeSession.session_id).catch(() => ({ events: [] as StudioEvent[] })),
      waitForDecisionState(runId, decisionId).catch(() => api.runDetail(runId).catch(() => null)),
    ]);
    mergeEvents(eventData.events ?? []);
    if (refreshed) setRunDetail(refreshed);
  }

  async function answerDecision(
    runId: string,
    decisionId: string,
    answer: string,
    setRunDetail: (detail: Awaited<ReturnType<typeof api.runDetail>> | null) => void,
  ) {
    if (!activeSession) return;
    try {
      await api.answerDecision(activeSession.session_id, runId, decisionId, answer);
    } catch {
      toast.error("无法发送你的回答——请重试。");
      return;
    }
    const [eventData, refreshed] = await Promise.all([
      api.events(activeSession.session_id).catch(() => ({ events: [] as StudioEvent[] })),
      waitForDecisionState(runId, decisionId).catch(() => api.runDetail(runId).catch(() => null)),
    ]);
    mergeEvents(eventData.events ?? []);
    if (refreshed) setRunDetail(refreshed);
  }

  function clearEvents() {
    setEvents([]);
  }

  return {
    events,
    mergeEvents,
    pendingTurn,
    isRunning,
    interrupted,
    waiting,
    runState,
    runStateKnown,
    connectivity,
    sendGoal,
    sendSideAsk,
    permitJob,
    stopRun,
    pauseRun,
    steerRun,
    runRuntimeAction,
    resolveDecision,
    answerDecision,
    clearEvents,
  };
}

async function waitForDecisionState(runId: string, decisionId: string) {
  const deadline = Date.now() + 15_000;
  let latest: Awaited<ReturnType<typeof api.runDetail>> | null = null;
  while (Date.now() < deadline) {
    latest = await api.runDetail(runId);
    const stillPending = (latest.decision_requests ?? []).some(
      (decision) => String(decision.decision_id ?? "") === decisionId,
    );
    if (!stillPending) return latest;
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  return latest;
}
