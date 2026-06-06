import React, { useEffect, useMemo, useState, useRef } from "react";
import { RefreshCw, FolderOpen } from "lucide-react";
import type {
  StudioSession,
  StudioEvent,
  SettingsPayload,
  OverviewPayload,
  RunDetailPayload,
  WorkspaceFile,
  FilePreview,
  GitStatusPayload,
  GitDiffPayload,
} from "./types";
import { api, subscribeToEvents } from "./api";
import { isSessionLive } from "./narrative";
import { buildTurnDiffScopes } from "./turnDiff";
import type { DiffLayout, DiffStage } from "./components/DiffPreview";
import { Banner } from "./components/Shared";
import { Sidebar } from "./components/Sidebar";
import { Thread } from "./components/Thread";
import { Inspector } from "./components/Inspector";
import { WorkflowPhaseStrip } from "./components/WorkflowPhaseStrip";
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
  const [files, setFiles] = useState<WorkspaceFile[]>([]);
  const [preview, setPreview] = useState<FilePreview | null>(null);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [runDetail, setRunDetail] = useState<RunDetailPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [promptSignal, setPromptSignal] = useState<PromptSignal>({ text: "", id: 0 });
  const [pendingTurn, setPendingTurn] = useState<{ message: string; mode: string; startedAt: number } | null>(null);
  const [workspaceOpen, setWorkspaceOpen] = useState(false);
  const [gitStatus, setGitStatus] = useState<GitStatusPayload | null>(null);
  const [gitLoading, setGitLoading] = useState(false);
  const [gitSelectedPath, setGitSelectedPath] = useState<string | null>(null);
  const [gitDiffPayload, setGitDiffPayload] = useState<GitDiffPayload | null>(null);
  const [diffScopeId, setDiffScopeId] = useState("current");
  const [diffStage, setDiffStage] = useState<DiffStage>("all");
  const [diffLayout, setDiffLayout] = useState<DiffLayout>("unified");
  const [gitActionLoading, setGitActionLoading] = useState(false);
  const [compactLoading, setCompactLoading] = useState(false);
  const [contextSectionId, setContextSectionId] = useState<string | null>(null);
  const unsubRef = useRef<(() => void) | null>(null);
  const refreshedRunEventRef = useRef<string>("");

  function mergeEvents(incoming: StudioEvent[]) {
    setEvents((prev) => {
      const existingIds = new Set(prev.map((e) => e.event_id));
      const fresh = incoming.filter((e) => !existingIds.has(e.event_id));
      if (!fresh.length) return prev;
      return [...prev, ...fresh].sort((a, b) => eventTimeValue(a) - eventTimeValue(b));
    });
  }

  async function refreshGitStatus() {
    setGitLoading(true);
    try {
      setGitStatus(await api.gitStatus());
    } catch {
      setGitStatus({ ok: false, available: false, reason: "Could not load git status." });
    } finally {
      setGitLoading(false);
    }
  }

  async function openFileChange(pathValue: string, stage: DiffStage = diffStage) {
    setGitSelectedPath(pathValue);
    try {
      const diff = await api.gitDiff(pathValue, stage);
      setGitDiffPayload(diff);
      const diffText = String(diff.diff ?? "");
      if (diff.ok && diffText && !diffText.includes("(no diff")) {
        setPreview({
          ok: true,
          path: diff.path ?? pathValue,
          content: diffText,
        });
        return;
      }
      setPreview(await api.previewFile(pathValue));
    } catch (err) {
      setGitDiffPayload(null);
      setPreview({ ok: false, error: String((err as Error).message || err) });
    }
  }

  async function openGitDiff(pathValue: string) {
    await openFileChange(pathValue);
  }

  function selectTurnDiff(turnIndex: number) {
    const scope = turnDiffScopes.find((item) => item.turnIndex === turnIndex);
    if (scope) {
      setDiffScope(scope.id);
    } else {
      setDiffScope(`turn-chrono-${turnIndex}`);
    }
    const firstPath = scope?.files[0]?.path;
    if (firstPath) {
      void openFileChange(firstPath);
    }
  }

  const turnDiffScopes = useMemo(() => buildTurnDiffScopes(events), [events]);

  async function persistSessionUiState(nextScopeId = diffScopeId, nextStage = diffStage, nextLayout = diffLayout) {
    if (!activeSession) return;
    await api.updateSession(activeSession.session_id, {
      ui_state: {
        diffScopeId: nextScopeId,
        diffStage: nextStage,
        diffLayout: nextLayout,
      },
    }).catch(() => {});
  }

  function setDiffScope(scopeId: string) {
    setDiffScopeId(scopeId);
    void persistSessionUiState(scopeId);
  }

  function setDiffStageAndReload(stage: DiffStage) {
    setDiffStage(stage);
    void persistSessionUiState(diffScopeId, stage);
    if (gitSelectedPath) void openFileChange(gitSelectedPath, stage);
  }

  function setDiffLayoutMode(layout: DiffLayout) {
    setDiffLayout(layout);
    void persistSessionUiState(diffScopeId, diffStage, layout);
  }

  async function stageSelectedFile() {
    if (!gitSelectedPath) return;
    setGitActionLoading(true);
    try {
      await api.gitStage(gitSelectedPath);
      await refreshGitStatus();
      await openFileChange(gitSelectedPath, diffStage);
    } finally {
      setGitActionLoading(false);
    }
  }

  async function discardSelectedFile() {
    if (!gitSelectedPath) return;
    const ok = window.confirm(`Discard uncommitted changes in ${gitSelectedPath}?`);
    if (!ok) return;
    setGitActionLoading(true);
    try {
      await api.gitDiscard(gitSelectedPath);
      await refreshGitStatus();
      await openFileChange(gitSelectedPath, diffStage);
    } finally {
      setGitActionLoading(false);
    }
  }

  async function compactContext() {
    if (!activeSession) return;
    const ok = window.confirm("Compact session context? Older turns may be summarized.");
    if (!ok) return;
    setCompactLoading(true);
    try {
      await api.runtimeAction(activeSession.session_id, "compact", "ask");
      if (selectedRunId) {
        setRunDetail(await api.runDetail(selectedRunId));
      }
    } finally {
      setCompactLoading(false);
    }
  }

  useEffect(() => {
    if (diffScopeId === "current") return;
    if (!turnDiffScopes.some((scope) => scope.id === diffScopeId)) {
      setDiffScopeId("current");
    }
  }, [diffScopeId, turnDiffScopes]);

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
      const fileData = await api.files().catch(() => ({ files: [] as WorkspaceFile[] }));
      setFiles(fileData.files ?? []);
      await openLatestRun(overviewData);
      void refreshGitStatus();
      void api.diagnostics()
        .then((diagnostics) => {
          setOverview((current) => ({
            ...(current ?? overviewData),
            ...diagnostics,
            runs: current?.runs ?? overviewData.runs,
            modelRoutes: diagnostics.modelRoutes ?? current?.modelRoutes ?? overviewData.modelRoutes,
          }));
        })
        .catch(() => {});
    } catch (err) {
      setError(String((err as Error).message || err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void bootstrap(); }, []);

  async function openLatestRun(overviewData: OverviewPayload | null = overview) {
    const latestRunId = String(overviewData?.runs?.[0]?.run_id ?? "");
    if (!latestRunId) {
      setSelectedRunId(null);
      setRunDetail(null);
      return;
    }
    await openRun(latestRunId);
  }

  async function openRun(runId: string) {
    if (!runId) return;
    setSelectedRunId(runId);
    const detail = await api.runDetail(runId);
    setRunDetail(detail);
  }

  async function openFile(path: string) {
    setGitSelectedPath(null);
    setPreview(await api.previewFile(path));
  }

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

  const latestRunEvent = useMemo(() => {
    return [...events].reverse().find((event) => (
      event.run_id
      && ["tool_end", "final_answer", "error"].includes(String(event.type ?? ""))
    ));
  }, [events]);

  useEffect(() => {
    const runId = String(latestRunEvent?.run_id ?? "");
    const eventId = String(latestRunEvent?.event_id ?? "");
    if (!runId || !eventId || eventId === refreshedRunEventRef.current) return;
    refreshedRunEventRef.current = eventId;
    void openRun(runId);
    void refreshGitStatus();
  }, [latestRunEvent?.event_id, latestRunEvent?.run_id]);

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

  async function resolveDecision(runId: string, decisionId: string, optionId: string) {
    if (!activeSession) return;
    await api.resolveDecision(activeSession.session_id, runId, decisionId, optionId);
    const [eventData, refreshed] = await Promise.all([
      api.events(activeSession.session_id).catch(() => ({ events: [] as StudioEvent[] })),
      waitForDecisionState(runId, decisionId).catch(() => api.runDetail(runId).catch(() => null)),
    ]);
    mergeEvents(eventData.events ?? []);
    if (refreshed) setRunDetail(refreshed);
  }

  async function waitForDecisionState(runId: string, decisionId: string): Promise<RunDetailPayload | null> {
    const deadline = Date.now() + 15_000;
    let latest: RunDetailPayload | null = null;
    while (Date.now() < deadline) {
      latest = await api.runDetail(runId);
      const stillPending = (latest.decision_requests ?? []).some((decision) => String(decision.decision_id ?? "") === decisionId);
      if (!stillPending) return latest;
      await new Promise((resolve) => setTimeout(resolve, 500));
    }
    return latest;
  }


  function selectSession(session: StudioSession) {
    setActiveSession(session);
    setSelectedEvent(null);
    const ui = session.ui_state ?? {};
    setDiffScopeId(String(ui.diffScopeId || "current"));
    setDiffStage((String(ui.diffStage || "all") as DiffStage));
    setDiffLayout((String(ui.diffLayout || "unified") as DiffLayout));
  }

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (!event.ctrlKey || sessions.length < 2) return;
      if (event.key !== "Tab") return;
      event.preventDefault();
      const index = sessions.findIndex((session) => session.session_id === activeSession?.session_id);
      if (index < 0) return;
      const delta = event.shiftKey ? -1 : 1;
      const next = sessions[(index + delta + sessions.length) % sessions.length];
      selectSession(next);
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [sessions, activeSession?.session_id]);

  const isRunning = useMemo(() => isSessionLive(events), [events]);

  function selectEvent(event: StudioEvent) {
    setSelectedEvent(event);
    if (event.run_id && event.run_id !== selectedRunId) {
      void openRun(event.run_id);
    }
  }

  function selectRunEvidenceEvent(event: StudioEvent) {
    setSelectedEvent(event);
    const runId = String(event.run_id ?? "");
    if (runId && runId !== selectedRunId) {
      void openRun(runId);
    }
  }

  return (
    <div className="appShell">
      <Sidebar
        sessions={sessions}
        active={activeSession}
        overview={overview}
        settings={settings}
        isRunning={isRunning}
        onSelect={selectSession}
        onNew={() => void newSession()}
        onDelete={(session) => void deleteSession(session)}
        onRename={async (session, title) => {
          const result = await api.updateSession(session.session_id, { title });
          setSessions((prev) => prev.map((item) => (item.session_id === session.session_id ? result.session : item)));
          if (activeSession?.session_id === session.session_id) setActiveSession(result.session);
        }}
        onWorkspaceChanged={() => void bootstrap()}
        workspaceOpen={workspaceOpen}
        onWorkspaceOpenChange={setWorkspaceOpen}
      />
      <main className="missionPane">
        <header className="topBar">
          <div>
            <p className="eyebrow">Asteria</p>
            <h1>{activeSession?.title ?? "New task"}</h1>
            <p>Ask, plan, or continue a goal.</p>
            <button
              type="button"
              className="workspaceChip"
              title={settings?.workspace ?? "Open workspace folder"}
              onClick={() => setWorkspaceOpen(true)}
            >
              <FolderOpen size={14} />
              <span>{settings?.workspaceName ?? "Workspace"}</span>
            </button>
          </div>
          <div className="topActions">
            <button title="Refresh" onClick={() => void bootstrap()} disabled={loading}>
              <RefreshCw size={17} className={loading ? "spinning" : ""} />
            </button>
          </div>
        </header>
        <WorkflowPhaseStrip runDetail={runDetail} isRunning={isRunning} />
        {error && <Banner tone="bad" text={error} />}
        <Thread
          events={events}
          selected={selectedEvent}
          isRunning={isRunning}
          onSelect={selectEvent}
          onPrompt={(text) => setPromptSignal((prev) => ({ text, id: prev.id + 1 }))}
          onPermit={permitJob}
          onRuntimeAction={runRuntimeAction}
          onResolveDecision={resolveDecision}
          pendingTurn={pendingTurn}
          overview={overview}
          runDetail={runDetail}
          onFileChangeClick={(pathValue) => void openFileChange(pathValue)}
          onTurnDiffSelect={selectTurnDiff}
          turnDiffLabel={(turnIndex) =>
            turnDiffScopes.find((scope) => scope.turnIndex === turnIndex)?.label ?? `T${turnIndex}`
          }
          onAggregateDiffClick={(turnIndex) => selectTurnDiff(turnIndex)}
          onCompactContext={() => void compactContext()}
          compactLoading={compactLoading}
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
        gitStatus={gitStatus}
        gitLoading={gitLoading}
        gitSelectedPath={gitSelectedPath}
        diffScopes={turnDiffScopes}
        diffScopeId={diffScopeId}
        onSelectDiffScope={setDiffScope}
        diffStage={diffStage}
        onSelectDiffStage={setDiffStageAndReload}
        diffLayout={diffLayout}
        onSelectDiffLayout={setDiffLayoutMode}
        gitDiffPayload={gitDiffPayload}
        gitActionLoading={gitActionLoading}
        onStageFile={() => void stageSelectedFile()}
        onDiscardFile={() => void discardSelectedFile()}
        contextSectionId={contextSectionId}
        onSelectContextSection={setContextSectionId}
        onCompactContext={() => void compactContext()}
        compactLoading={compactLoading}
        isRunning={isRunning}
        onRefreshGit={() => void refreshGitStatus()}
        onSelectGitChange={(pathValue) => void openGitDiff(pathValue)}
        onOpenFile={openFile}
        onOpenRun={openRun}
        onSelectRunEvent={selectRunEvidenceEvent}
      />
    </div>
  );
}
