import type { StudioSession, StudioEvent, WorkspaceFile, FilePreview, SettingsPayload, OverviewPayload, RunDetailPayload, AnyRecord, WorkspacesPayload, OpenWorkspacePayload, BrowseWorkspacePayload, WorkspaceProfile, GitStatusPayload, GitDiffPayload, GitFileActionPayload } from "./types";

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json() as Promise<T>;
}

export const api = {
  sessions: () => requestJson<{ ok: boolean; sessions: StudioSession[] }>("/api/studio/sessions"),
  createSession: () => requestJson<{ ok: boolean; session: StudioSession }>("/api/studio/sessions", { method: "POST" }),
  deleteSession: (id: string) => requestJson<{ ok: boolean; deleted: string }>(`/api/studio/sessions/${encodeURIComponent(id)}`, { method: "DELETE" }),
  updateSession: (id: string, body: { title?: string; goal_preview?: string; ui_state?: Record<string, unknown> }) =>
    requestJson<{ ok: boolean; session: StudioSession }>(`/api/studio/sessions/${encodeURIComponent(id)}`, {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    }),
  events: (id: string) => requestJson<{ ok: boolean; events: StudioEvent[] }>(`/api/studio/sessions/${encodeURIComponent(id)}/events`),
  send: (id: string, message: string, mode: string, permission: string) =>
    requestJson<AnyRecord>(`/api/studio/sessions/${encodeURIComponent(id)}/messages`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ message, mode, permission }),
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
  permitJob: (sessionId: string, jobId: string, action: "allow" | "deny") =>
    requestJson<AnyRecord>(
      `/api/studio/sessions/${encodeURIComponent(sessionId)}/jobs/${encodeURIComponent(jobId)}/permission`,
      { method: "PATCH", headers: { "content-type": "application/json" }, body: JSON.stringify({ action }) }
    ),
  files: () => requestJson<{ ok: boolean; files: WorkspaceFile[] }>("/api/studio/files"),
  previewFile: (path: string) =>
    requestJson<FilePreview>("/api/studio/files/preview", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ path }),
    }),
  settings: () => requestJson<{ ok: boolean; settings: SettingsPayload }>("/api/studio/settings"),
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
    requestJson<WorkspaceProfile>(`/api/studio/workspace/profile?path=${encodeURIComponent(pathValue)}`),
  gitStatus: () => requestJson<GitStatusPayload>("/api/studio/git/status"),
  gitDiff: (pathValue: string, stage = "all") =>
    requestJson<GitDiffPayload>(`/api/studio/git/diff?path=${encodeURIComponent(pathValue)}&stage=${encodeURIComponent(stage)}`),
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
  runDetail: (runId: string) => requestJson<RunDetailPayload>(`/api/runs/${encodeURIComponent(runId)}`),
};

export function subscribeToEvents(
  sessionId: string,
  onEvents: (events: StudioEvent[]) => void
): () => void {
  let stopped = false;
  let pollTimer: ReturnType<typeof setInterval> | null = null;
  let es: EventSource | null = null;
  const seen = new Set<string>();

  function addFresh(evts: StudioEvent[]) {
    const fresh = evts.filter((e) => !seen.has(e.event_id));
    for (const e of fresh) seen.add(e.event_id);
    if (fresh.length) onEvents(fresh);
  }

  function startPoll(interval = 1200) {
    pollTimer = setInterval(async () => {
      if (stopped) { if (pollTimer) clearInterval(pollTimer); return; }
      try {
        const data = await api.events(sessionId);
        addFresh(data.events ?? []);
      } catch {}
    }, interval);
  }

  if (typeof EventSource !== "undefined") {
    es = new EventSource(`/api/studio/sessions/${encodeURIComponent(sessionId)}/events/stream`);
    es.onmessage = (e) => {
      if (!e.data || e.data.startsWith(":")) return;
      try { addFresh([JSON.parse(e.data) as StudioEvent]); } catch {}
    };
    es.onerror = () => {
      es?.close();
      es = null;
      if (!stopped) startPoll(1500);
    };
    // Also poll every 8s for runtime events from user_progress.jsonl that bypass SSE
    startPoll(8000);
  } else {
    startPoll(900);
  }

  return () => {
    stopped = true;
    es?.close();
    if (pollTimer) clearInterval(pollTimer);
  };
}
