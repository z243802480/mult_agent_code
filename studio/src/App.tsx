import React, { useEffect, useMemo, useState, useRef } from "react";
import { RefreshCw } from "lucide-react";
import type {
  StudioSession,
  StudioEvent,
  SettingsPayload,
  OverviewPayload,
} from "./types";
import { api, subscribeToEvents } from "./api";
import { isSessionLive } from "./narrative";
import { Banner } from "./components/Shared";
import { Sidebar } from "./components/Sidebar";
import { Thread } from "./components/Thread";
import { Composer, type PromptSignal } from "./components/Composer";

function eventTimeValue(event: StudioEvent): number {
  const value = Date.parse(String(event.created_at ?? ""));
  if (Number.isFinite(value)) return value;
  const sequence = Number((event as unknown as Record<string, unknown>).sequence);
  if (Number.isFinite(sequence)) return sequence;
  return 0;
}

export function App() {
  const [sessions, setSessions] = useState<StudioSession[]>([]);
  const [activeSession, setActiveSession] = useState<StudioSession | null>(null);
  const [events, setEvents] = useState<StudioEvent[]>([]);
  const [selectedEvent, setSelectedEvent] = useState<StudioEvent | null>(null);
  const [settings, setSettings] = useState<SettingsPayload | null>(null);
  const [overview, setOverview] = useState<OverviewPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [promptSignal, setPromptSignal] = useState<PromptSignal>({ text: "", id: 0 });
  const [pendingTurn, setPendingTurn] = useState<{ message: string; mode: string; startedAt: number } | null>(null);
  const unsubRef = useRef<(() => void) | null>(null);

  function mergeEvents(incoming: StudioEvent[]) {
    setEvents((prev) => {
      const existingIds = new Set(prev.map((e) => e.event_id));
      const fresh = incoming.filter((e) => !existingIds.has(e.event_id));
      if (!fresh.length) return prev;
      return [...prev, ...fresh].sort((a, b) => eventTimeValue(a) - eventTimeValue(b));
    });
  }

  async function bootstrap() {
    setError(null);
    setLoading(true);
    try {
      const [sessionData, settingsData, overviewData] = await Promise.all([
        api.sessions(),
        api.settings(),
        api.overview(),
      ]);
      let nextSessions = sessionData.sessions ?? [];
      if (!nextSessions.length) {
        const created = await api.createSession();
        nextSessions = [created.session];
      }
      setSessions(nextSessions);
      setSettings(settingsData.settings);
      setOverview(overviewData);
      setActiveSession((current) => current ?? nextSessions[0]);
    } catch (err) {
      setError(String((err as Error).message || err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void bootstrap(); }, []);

  // Subscribe to events (SSE or polling) when active session changes
  useEffect(() => {
    if (!activeSession) return;
    setEvents([]);

    // Load initial events
    void api.events(activeSession.session_id).then((data) => mergeEvents(data.events ?? [])).catch(() => {});

    // Subscribe for live updates
    unsubRef.current?.();
    unsubRef.current = subscribeToEvents(activeSession.session_id, mergeEvents);

    return () => { unsubRef.current?.(); unsubRef.current = null; };
  }, [activeSession?.session_id]);


  async function newSession() {
    const created = await api.createSession();
    setSessions([created.session, ...sessions]);
    setActiveSession(created.session);
    setEvents([]);
    setSelectedEvent(null);
  }

  async function deleteSession(session: StudioSession) {
    const ok = window.confirm(`Delete session "${session.title || session.session_id}"? This only removes Studio conversation history.`);
    if (!ok) return;
    await api.deleteSession(session.session_id);
    const refreshed = await api.sessions();
    const nextSessions = refreshed.sessions ?? [];
    setSessions(nextSessions);
    if (activeSession?.session_id === session.session_id) {
      if (nextSessions.length) {
        setActiveSession(nextSessions[0]);
      } else {
        const created = await api.createSession();
        setSessions([created.session]);
        setActiveSession(created.session);
      }
      setEvents([]);
      setSelectedEvent(null);
    }
  }

  async function sendGoal(message: string, mode: string, permission: string) {
    if (!activeSession) return;
    setPendingTurn({ message, mode, startedAt: Date.now() });
    try {
      await api.send(activeSession.session_id, message, mode, permission);
      // SSE will pick up the new events; also refresh session list
      const refreshed = await api.sessions();
      setSessions(refreshed.sessions ?? []);
    } finally {
      setPendingTurn(null);
    }
  }

  async function permitJob(jobId: string, action: "allow" | "deny") {
    if (!activeSession) return;
    await api.permitJob(activeSession.session_id, jobId, action);
  }


  function selectSession(session: StudioSession) {
    setActiveSession(session);
    setSelectedEvent(null);
  }

  const isRunning = useMemo(() => isSessionLive(events), [events]);

  return (
    <div className="appShell">
      <Sidebar
        sessions={sessions}
        active={activeSession}
        overview={overview}
        settings={settings}
        onSelect={selectSession}
        onNew={() => void newSession()}
        onDelete={(session) => void deleteSession(session)}
      />
      <main className="missionPane">
        <header className="topBar">
          <div>
            <p className="eyebrow">Asteria</p>
            <h1>{activeSession?.title ?? "New task"}</h1>
            <p>Ask, plan, or continue a goal.</p>
          </div>
          <div className="topActions">
            <button title="Refresh" onClick={() => void bootstrap()} disabled={loading}>
              <RefreshCw size={17} className={loading ? "spinning" : ""} />
            </button>
          </div>
        </header>
        {error && <Banner tone="bad" text={error} />}
        <Thread
          events={events}
          selected={selectedEvent}
          isRunning={isRunning}
          onSelect={setSelectedEvent}
          onPrompt={(text) => setPromptSignal((prev) => ({ text, id: prev.id + 1 }))}
          onPermit={permitJob}
          pendingTurn={pendingTurn}
        />
        <Composer
          onSend={sendGoal}
          promptSignal={promptSignal}
        />
      </main>
    </div>
  );
}
