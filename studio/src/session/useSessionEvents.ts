import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { StudioEvent, StudioSession } from "../types";
import { api, subscribeToEvents } from "../api";
import { isSessionLive } from "../narrative";
import { mergeEventLists } from "./eventUtils";

export function useSessionEvents(activeSession: StudioSession | null, sessions: StudioSession[], setSessions: (sessions: StudioSession[]) => void) {
  const [events, setEvents] = useState<StudioEvent[]>([]);
  const [pendingTurn, setPendingTurn] = useState<{ message: string; mode: string; startedAt: number } | null>(null);
  const unsubRef = useRef<(() => void) | null>(null);

  const mergeEvents = useCallback((incoming: StudioEvent[]) => {
    setEvents((prev) => mergeEventLists(prev, incoming));
  }, []);

  useEffect(() => {
    if (!activeSession) return;
    setEvents([]);
    void api.events(activeSession.session_id).then((data) => mergeEvents(data.events ?? [])).catch(() => {});
    unsubRef.current?.();
    unsubRef.current = subscribeToEvents(activeSession.session_id, mergeEvents);
    return () => {
      unsubRef.current?.();
      unsubRef.current = null;
    };
  }, [activeSession?.session_id, mergeEvents]);

  const isRunning = useMemo(() => isSessionLive(events), [events]);

  async function sendGoal(message: string, mode: string, permission: string, permissionMode?: string) {
    if (!activeSession) return;
    setPendingTurn({ message, mode, startedAt: Date.now() });
    try {
      await api.send(activeSession.session_id, message, mode, permission, undefined, permissionMode);
      const refreshed = await api.sessions();
      setSessions(refreshed.sessions ?? []);
    } finally {
      setPendingTurn(null);
    }
  }

  async function sendSideAsk(message: string) {
    if (!activeSession) return;
    await api.send(activeSession.session_id, message, "chat", "ask", "side");
  }

  async function permitJob(jobId: string, action: "allow" | "deny") {
    if (!activeSession) return;
    await api.permitJob(activeSession.session_id, jobId, action);
  }

  async function stopRun() {
    if (!activeSession) return;
    await api.stopSession(activeSession.session_id).catch(() => {});
    const eventData = await api.events(activeSession.session_id).catch(() => ({ events: [] as StudioEvent[] }));
    mergeEvents(eventData.events ?? []);
  }

  async function runRuntimeAction(nextAction: string) {
    if (!activeSession) return;
    await api.runtimeAction(activeSession.session_id, nextAction, "ask");
    const [eventData, refreshed] = await Promise.all([
      api.events(activeSession.session_id).catch(() => ({ events: [] as StudioEvent[] })),
      api.sessions().catch(() => ({ sessions })),
    ]);
    mergeEvents(eventData.events ?? []);
    setSessions(refreshed.sessions ?? sessions);
  }

  async function resolveDecision(
    runId: string,
    decisionId: string,
    optionId: string,
    setRunDetail: (detail: Awaited<ReturnType<typeof api.runDetail>> | null) => void,
  ) {
    if (!activeSession) return;
    await api.resolveDecision(activeSession.session_id, runId, decisionId, optionId);
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
    sendGoal,
    sendSideAsk,
    permitJob,
    stopRun,
    runRuntimeAction,
    resolveDecision,
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
