import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { StudioEvent, StudioSession } from "../types";
import { api, subscribeToEvents, type ConnectivityStatus } from "../api";
import { isSessionLive } from "../narrative";
import { mergeEventLists } from "./eventUtils";
import { toast } from "../components/toast";

export function useSessionEvents(activeSession: StudioSession | null, sessions: StudioSession[], setSessions: (sessions: StudioSession[]) => void) {
  const [events, setEvents] = useState<StudioEvent[]>([]);
  const [pendingTurn, setPendingTurn] = useState<{ message: string; mode: string; startedAt: number } | null>(null);
  const [connectivity, setConnectivity] = useState<ConnectivityStatus>("live");
  const unsubRef = useRef<(() => void) | null>(null);

  const mergeEvents = useCallback((incoming: StudioEvent[]) => {
    setEvents((prev) => mergeEventLists(prev, incoming));
  }, []);

  useEffect(() => {
    if (!activeSession) return;
    setEvents([]);
    setConnectivity("live");
    void api.events(activeSession.session_id).then((data) => mergeEvents(data.events ?? [])).catch(() => {});
    unsubRef.current?.();
    unsubRef.current = subscribeToEvents(activeSession.session_id, mergeEvents, setConnectivity);
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
    } catch {
      // Never silently swallow a failed send — the message was NOT delivered. Offer a Retry that
      // re-sends the exact text (so the draft is not lost) instead of clearing it into the void.
      toast.error("Couldn't send your message — it wasn't delivered.", {
        action: { label: "Retry", onClick: () => void sendGoal(message, mode, permission, permissionMode) },
      });
    } finally {
      setPendingTurn(null);
    }
  }

  async function sendSideAsk(message: string) {
    if (!activeSession) return;
    try {
      await api.send(activeSession.session_id, message, "chat", "ask", "side");
    } catch {
      toast.error("Couldn't send — the side question wasn't delivered.", {
        action: { label: "Retry", onClick: () => void sendSideAsk(message) },
      });
    }
  }

  async function permitJob(jobId: string, action: "allow" | "deny") {
    if (!activeSession) return;
    try {
      await api.permitJob(activeSession.session_id, jobId, action);
    } catch {
      toast.error(`Couldn't record your ${action === "allow" ? "approval" : "denial"} — try again.`);
    }
  }

  async function stopRun() {
    if (!activeSession) return;
    await api.stopSession(activeSession.session_id).catch(() => {});
    const eventData = await api.events(activeSession.session_id).catch(() => ({ events: [] as StudioEvent[] }));
    mergeEvents(eventData.events ?? []);
  }

  async function runRuntimeAction(nextAction: string) {
    if (!activeSession) return;
    try {
      await api.runtimeAction(activeSession.session_id, nextAction, "ask");
    } catch {
      toast.error("Couldn't start that action — try again.", {
        action: { label: "Retry", onClick: () => void runRuntimeAction(nextAction) },
      });
      return;
    }
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
    try {
      await api.resolveDecision(activeSession.session_id, runId, decisionId, optionId);
    } catch {
      toast.error("Couldn't submit your choice — try again.");
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
    connectivity,
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
