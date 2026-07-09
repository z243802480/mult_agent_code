import type {
  StudioSession,
  StudioEvent,
  WorkspaceFile,
  FilePreview,
  SettingsPayload,
  OverviewPayload,
  RunDetailPayload,
  AnyRecord,
  WorkspacesPayload,
  OpenWorkspacePayload,
  BrowseWorkspacePayload,
  WorkspaceProfile,
  GitStatusPayload,
  GitDiffPayload,
  GitFileActionPayload,
} from "./types";

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json() as Promise<T>;
}

export const api = {
  sessions: () => requestJson<{ ok: boolean; sessions: StudioSession[] }>("/api/studio/sessions"),
  createSession: () =>
    requestJson<{ ok: boolean; session: StudioSession }>("/api/studio/sessions", {
      method: "POST",
    }),
  deleteSession: (id: string, purge = false) =>
    requestJson<{ ok: boolean; deleted: string; soft_deleted?: boolean; purged?: boolean }>(
      `/api/studio/sessions/${encodeURIComponent(id)}${purge ? "?purge=1" : ""}`,
      { method: "DELETE" },
    ),
  restoreSession: (id: string) =>
    requestJson<{ ok: boolean; session?: StudioSession; restored?: string }>(
      `/api/studio/sessions/${encodeURIComponent(id)}/restore`,
      { method: "POST" },
    ),
  // Direct download URL — an <a href download> streams the bundle (with the server's
  // Content-Disposition filename) without loading a large session into JS memory.
  previewInfo: () =>
    requestJson<{
      ok: boolean;
      port: number | null;
      mode?: "static" | "proxy";
      target?: string | null;
    }>("/api/studio/preview-info"),
  exportUrl: (id: string) => `/api/studio/sessions/${encodeURIComponent(id)}/export`,
  importSession: (bundle: unknown) =>
    requestJson<{ ok: boolean; session?: StudioSession; imported?: number; error?: string }>(
      "/api/studio/sessions/import",
      {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ bundle }),
      },
    ),
  updateSession: (
    id: string,
    body: { title?: string; goal_preview?: string; ui_state?: Record<string, unknown> },
  ) =>
    requestJson<{ ok: boolean; session: StudioSession }>(
      `/api/studio/sessions/${encodeURIComponent(id)}`,
      {
        method: "PATCH",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
      },
    ),
  events: (id: string) =>
    requestJson<{ ok: boolean; events: StudioEvent[] }>(
      `/api/studio/sessions/${encodeURIComponent(id)}/events`,
    ),
  send: (
    id: string,
    message: string,
    mode: string,
    permission: string,
    channel?: string,
    permissionMode?: string,
  ) =>
    requestJson<AnyRecord>(`/api/studio/sessions/${encodeURIComponent(id)}/messages`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ message, mode, permission, channel, permissionMode }),
    }),
  runtimeAction: (id: string, nextAction: string, permission = "ask") =>
    requestJson<AnyRecord>(`/api/studio/sessions/${encodeURIComponent(id)}/runtime-actions`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ next_action: nextAction, permission }),
    }),
  resolveDecision: (id: string, runId: string, decisionId: string, optionId: string) =>
    requestJson<AnyRecord>(`/api/studio/sessions/${encodeURIComponent(id)}/decisions/resolve`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ run_id: runId, decision_id: decisionId, option_id: optionId }),
    }),
  answerDecision: (id: string, runId: string, decisionId: string, answer: string) =>
    requestJson<AnyRecord>(`/api/studio/sessions/${encodeURIComponent(id)}/decisions/answer`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ run_id: runId, decision_id: decisionId, answer }),
    }),
  permitJob: (sessionId: string, jobId: string, action: "allow" | "deny") =>
    requestJson<AnyRecord>(
      `/api/studio/sessions/${encodeURIComponent(sessionId)}/jobs/${encodeURIComponent(jobId)}/permission`,
      {
        method: "PATCH",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ action }),
      },
    ),
  stopSession: (sessionId: string) =>
    requestJson<AnyRecord>(`/api/studio/sessions/${encodeURIComponent(sessionId)}/stop`, {
      method: "POST",
    }),
  files: () => requestJson<{ ok: boolean; files: WorkspaceFile[] }>("/api/studio/files"),
  previewFile: (path: string) =>
    requestJson<FilePreview>("/api/studio/files/preview", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ path }),
    }),
  settings: () => requestJson<{ ok: boolean; settings: SettingsPayload }>("/api/studio/settings"),
  updateSettings: (body: Partial<SettingsPayload>) =>
    requestJson<{ ok: boolean; settings: SettingsPayload; error?: string }>(
      "/api/studio/settings",
      {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
      },
    ),
  workspaces: () => requestJson<WorkspacesPayload>("/api/studio/workspaces"),
  openWorkspace: (pathValue: string) =>
    requestJson<OpenWorkspacePayload>("/api/studio/workspace/open", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ path: pathValue }),
    }),
  browseWorkspace: () =>
    requestJson<BrowseWorkspacePayload>("/api/studio/workspace/browse", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({}),
    }),
  workspaceProfile: (pathValue: string) =>
    requestJson<WorkspaceProfile>(
      `/api/studio/workspace/profile?path=${encodeURIComponent(pathValue)}`,
    ),
  gitStatus: () => requestJson<GitStatusPayload>("/api/studio/git/status"),
  gitDiff: (pathValue: string, stage = "all") =>
    requestJson<GitDiffPayload>(
      `/api/studio/git/diff?path=${encodeURIComponent(pathValue)}&stage=${encodeURIComponent(stage)}`,
    ),
  gitStage: (pathValue: string) =>
    requestJson<GitFileActionPayload>("/api/studio/git/stage", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ path: pathValue }),
    }),
  gitDiscard: (pathValue: string) =>
    requestJson<GitFileActionPayload>("/api/studio/git/discard", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ path: pathValue }),
    }),
  overview: () => requestJson<OverviewPayload>("/api/overview"),
  diagnostics: () => requestJson<OverviewPayload>("/api/diagnostics"),
  runDetail: (runId: string) =>
    requestJson<RunDetailPayload>(`/api/runs/${encodeURIComponent(runId)}`),
};

export type ConnectivityStatus = "live" | "reconnecting" | "offline";

export function subscribeToEvents(
  sessionId: string,
  onEvents: (events: StudioEvent[]) => void,
  onStatus?: (status: ConnectivityStatus) => void,
): () => void {
  let stopped = false;
  let pollTimer: ReturnType<typeof setInterval> | null = null;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let es: EventSource | null = null;
  let sseOk = false;
  let pollFailures = 0;
  let reconnectAttempts = 0;
  let lastStatus: ConnectivityStatus | null = null;
  const seen = new Set<string>();

  function setStatus(next: ConnectivityStatus) {
    if (stopped || next === lastStatus) return;
    lastStatus = next;
    onStatus?.(next);
  }

  // Honest status: "live" while SSE is healthy; "reconnecting" when SSE is down but the
  // fallback poll may still be delivering (degraded, not dead); "offline" only when polling
  // also fails repeatedly (server likely down). Never claim "live" on a dead stream.
  function computeStatus() {
    if (sseOk) return setStatus("live");
    if (pollFailures >= 2) return setStatus("offline");
    setStatus("reconnecting");
  }

  function addFresh(evts: StudioEvent[]) {
    const fresh = evts.filter((e) => !seen.has(e.event_id));
    for (const e of fresh) seen.add(e.event_id);
    if (fresh.length) onEvents(fresh);
  }

  function startPoll(interval = 8000) {
    if (pollTimer) return;
    pollTimer = setInterval(async () => {
      if (stopped) {
        if (pollTimer) clearInterval(pollTimer);
        pollTimer = null;
        return;
      }
      try {
        const data = await api.events(sessionId);
        addFresh(data.events ?? []);
        pollFailures = 0;
        computeStatus();
      } catch {
        pollFailures += 1;
        computeStatus();
      }
    }, interval);
  }

  function openStream() {
    if (stopped || typeof EventSource === "undefined") return;
    es = new EventSource(`/api/studio/sessions/${encodeURIComponent(sessionId)}/events/stream`);
    es.onopen = () => {
      sseOk = true;
      reconnectAttempts = 0;
      computeStatus();
    };
    es.onmessage = (e) => {
      if (!e.data || e.data.startsWith(":")) return;
      sseOk = true;
      try {
        addFresh([JSON.parse(e.data) as StudioEvent]);
      } catch {}
      computeStatus();
    };
    es.onerror = () => {
      sseOk = false;
      computeStatus();
      // Native EventSource auto-retries while readyState===CONNECTING. Only when it gives up
      // (CLOSED) do we reconnect manually with capped exponential backoff (1s→2s→…→30s), so we
      // neither hammer a down server nor abandon SSE forever (the old code polled at 1.5s and
      // never re-opened the stream). The baseline poll keeps data flowing meanwhile.
      if (es && es.readyState === EventSource.CLOSED) {
        es.close();
        es = null;
        if (stopped || reconnectTimer) return;
        const delay = Math.min(30000, 1000 * 2 ** reconnectAttempts);
        reconnectAttempts += 1;
        reconnectTimer = setTimeout(() => {
          reconnectTimer = null;
          openStream();
        }, delay);
      }
    };
  }

  if (typeof EventSource !== "undefined") {
    openStream();
    // Baseline poll: runtime events from user_progress.jsonl bypass SSE, and this doubles as the
    // fallback delivery path while SSE is reconnecting.
    startPoll(8000);
  } else {
    startPoll(1500);
  }

  return () => {
    stopped = true;
    es?.close();
    if (pollTimer) clearInterval(pollTimer);
    if (reconnectTimer) clearTimeout(reconnectTimer);
  };
}
