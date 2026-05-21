import React, { useEffect, useMemo, useState, useRef } from "react";
import { RefreshCw, Route } from "lucide-react";
import type {
  StudioSession,
  StudioEvent,
  WorkspaceFile,
  FilePreview,
  SettingsPayload,
  OverviewPayload,
  RunDetailPayload,
} from "./types";
import { api, subscribeToEvents } from "./api";
import { isSessionLive } from "./narrative";
import { Banner, routeDecision } from "./components/Shared";
import { Sidebar } from "./components/Sidebar";
import { Thread } from "./components/Thread";
import { Composer, type PromptSignal } from "./components/Composer";
import { Inspector } from "./components/Inspector";

export function App() {
  const [sessions, setSessions] = useState<StudioSession[]>([]);
  const [activeSession, setActiveSession] = useState<StudioSession | null>(null);
  const [events, setEvents] = useState<StudioEvent[]>([]);
  const [selectedEvent, setSelectedEvent] = useState<StudioEvent | null>(null);
  const [files, setFiles] = useState<WorkspaceFile[]>([]);
  const [preview, setPreview] = useState<FilePreview | null>(null);
  const [settings, setSettings] = useState<SettingsPayload | null>(null);
  const [overview, setOverview] = useState<OverviewPayload | null>(null);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [runDetail, setRunDetail] = useState<RunDetailPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [promptSignal, setPromptSignal] = useState<PromptSignal>({ text: "", id: 0 });
  const unsubRef = useRef<(() => void) | null>(null);

  function mergeEvents(incoming: StudioEvent[]) {
    setEvents((prev) => {
      const existingIds = new Set(prev.map((e) => e.event_id));
      const fresh = incoming.filter((e) => !existingIds.has(e.event_id));
      if (!fresh.length) return prev;
      return [...prev, ...fresh].sort((a, b) => a.created_at.localeCompare(b.created_at));
    });
  }

  async function bootstrap() {
    setError(null);
    setLoading(true);
    try {
      const [sessionData, fileData, settingsData, overviewData] = await Promise.all([
        api.sessions(),
        api.files(),
        api.settings(),
        api.overview(),
      ]);
      let nextSessions = sessionData.sessions ?? [];
      if (!nextSessions.length) {
        const created = await api.createSession();
        nextSessions = [created.session];
      }
      setSessions(nextSessions);
      setFiles(fileData.files ?? []);
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

  // Auto-open latest run when overview loads
  useEffect(() => {
    const latestRunId = String(overview?.runs?.[0]?.run_id ?? "");
    if (!latestRunId || selectedRunId) return;
    void openRun(latestRunId);
  }, [overview, selectedRunId]);

  async function newSession() {
    const created = await api.createSession();
    setSessions([created.session, ...sessions]);
    setActiveSession(created.session);
    setEvents([]);
    setSelectedEvent(null);
  }

  async function sendGoal(message: string, mode: string, permission: string) {
    if (!activeSession) return;
    await api.send(activeSession.session_id, message, mode, permission);
    // SSE will pick up the new events; also refresh session list
    const refreshed = await api.sessions();
    setSessions(refreshed.sessions ?? []);
  }

  async function permitJob(jobId: string, action: "allow" | "deny") {
    if (!activeSession) return;
    await api.permitJob(activeSession.session_id, jobId, action);
  }

  async function openFile(path: string) {
    const result = await api.previewFile(path);
    setPreview(result);
  }

  async function openRun(runId: string) {
    setSelectedRunId(runId);
    const result = await api.runDetail(runId);
    setRunDetail(result);
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
      />
      <main className="missionPane">
        <header className="topBar">
          <div>
            <p className="eyebrow">Asteria Studio</p>
            <h1>{activeSession?.title ?? "Agent Workspace"}</h1>
            <p>{settings?.workspace ?? "正在连接..."}</p>
          </div>
          <div className="topActions">
            <span>
              <Route size={14} /> {routeDecision(overview)}
            </span>
            <button title="刷新" onClick={() => void bootstrap()} disabled={loading}>
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
        />
        <Composer
          onSend={sendGoal}
          promptSignal={promptSignal}
        />
      </main>
      <Inspector
        event={selectedEvent}
        files={files}
        preview={preview}
        settings={settings}
        overview={overview}
        selectedRunId={selectedRunId}
        runDetail={runDetail}
        onOpenFile={openFile}
        onOpenRun={openRun}
      />
    </div>
  );
}
