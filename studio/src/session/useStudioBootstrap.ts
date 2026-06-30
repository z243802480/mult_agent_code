import { useCallback, useEffect, useRef, useState } from "react";
import type { OverviewPayload, SettingsPayload, StudioSession, WorkspaceFile } from "../types";
import { api } from "../api";

type BootstrapCallbacks = {
  onOverviewReady?: (overview: OverviewPayload) => void | Promise<void>;
};

export function useStudioBootstrap(callbacks: BootstrapCallbacks = {}) {
  const onOverviewReadyRef = useRef(callbacks.onOverviewReady);
  onOverviewReadyRef.current = callbacks.onOverviewReady;
  const [sessions, setSessions] = useState<StudioSession[]>([]);
  const [activeSession, setActiveSession] = useState<StudioSession | null>(null);
  const [settings, setSettings] = useState<SettingsPayload | null>(null);
  const [overview, setOverview] = useState<OverviewPayload | null>(null);
  const [files, setFiles] = useState<WorkspaceFile[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [workspaceOpen, setWorkspaceOpen] = useState(false);
  const [promptSignal, setPromptSignal] = useState({ text: "", id: 0 });

  const bootstrap = useCallback(async () => {
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
      await onOverviewReadyRef.current?.(overviewData);
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
  }, []);

  useEffect(() => {
    void bootstrap();
  }, [bootstrap]);

  async function newSession(onSessionSelected?: () => void) {
    const created = await api.createSession();
    setSessions([created.session, ...sessions]);
    setActiveSession(created.session);
    onSessionSelected?.();
  }

  async function deleteSession(session: StudioSession, onSessionRemoved?: () => void) {
    const ok = window.confirm(
      `Delete session "${session.title || session.session_id}"? This only removes Studio conversation history.`,
    );
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
      onSessionRemoved?.();
    }
  }

  function pushPrompt(text: string) {
    setPromptSignal((prev) => ({ text, id: prev.id + 1 }));
  }

  return {
    sessions,
    setSessions,
    activeSession,
    setActiveSession,
    settings,
    setSettings,
    overview,
    files,
    error,
    loading,
    workspaceOpen,
    setWorkspaceOpen,
    promptSignal,
    bootstrap,
    newSession,
    deleteSession,
    pushPrompt,
  };
}
