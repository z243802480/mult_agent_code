import { useCallback, useEffect, useRef, useState } from "react";
import type { OverviewPayload, SettingsPayload, StudioSession, WorkspaceFile } from "../types";
import { api } from "../api";
import { toast } from "../components/toast";

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
      void api
        .diagnostics()
        .then((diagnostics) => {
          setOverview((current) => ({
            ...(current ?? overviewData),
            ...diagnostics,
            runs: current?.runs ?? overviewData.runs,
            modelRoutes:
              diagnostics.modelRoutes ?? current?.modelRoutes ?? overviewData.modelRoutes,
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

  // Light sessions poll (G3): keeps the sidebar's per-session status dots (run_status projected by
  // the BFF from its job registry) and archive changes live without any user action. Local BFF, a
  // handful of session.json reads — cheap. Only commits state when the payload actually changed, so
  // the idle steady-state causes zero re-renders.
  useEffect(() => {
    let lastPayload = "";
    const timer = window.setInterval(() => {
      void api
        .sessions()
        .then((data) => {
          if (!data?.sessions) return;
          const payload = JSON.stringify(data.sessions);
          if (payload === lastPayload) return;
          lastPayload = payload;
          setSessions(data.sessions);
        })
        .catch(() => {
          /* transient — the connectivity banner already covers a down server */
        });
    }, 7000);
    return () => window.clearInterval(timer);
  }, []);

  async function newSession(onSessionSelected?: () => void) {
    const created = await api.createSession();
    setSessions([created.session, ...sessions]);
    setActiveSession(created.session);
    onSessionSelected?.();
  }

  async function deleteSession(session: StudioSession, onSessionRemoved?: () => void) {
    // No modal: soft-delete is reversible (the server keeps events.jsonl until an explicit purge),
    // so the mainstream instant-delete + prominent Undo pattern is both lower-friction and safer
    // for long-task sessions than a permanent delete gated only by a confirm dialog.
    const res = await api.deleteSession(session.session_id).catch(() => null);
    if (!res?.ok) {
      toast.error("无法删除该会话。请重试。");
      return;
    }
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
    toast.info(`已删除“${session.title || "会话"}”`, {
      duration: 7000,
      action: { label: "撤销", onClick: () => void restoreSession(session) },
    });
  }

  async function restoreSession(session: StudioSession) {
    const res = await api.restoreSession(session.session_id).catch(() => null);
    if (!res?.ok) {
      toast.error("无法恢复该会话。");
      return;
    }
    const refreshed = await api.sessions();
    setSessions(refreshed.sessions ?? []);
    toast.success(`已恢复“${session.title || "会话"}”。`);
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
    restoreSession,
    pushPrompt,
  };
}
