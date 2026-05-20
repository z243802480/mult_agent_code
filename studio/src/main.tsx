import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { CheckCircle2, ChevronDown, ChevronRight, FileText, FolderOpen, Play, RefreshCw, Send, Settings, ShieldAlert, Terminal, XCircle } from "lucide-react";
import "./styles.css";

type AnyRecord = Record<string, any>;

type StudioSession = {
  session_id: string;
  title: string;
  workspace: string;
  created_at: string;
  updated_at: string;
};

type StudioEvent = {
  event_id: string;
  session_id: string;
  type: "user_message" | "assistant_delta" | "reasoning_delta" | "model_start" | "model_delta" | "model_end" | "model_error" | "tool_start" | "tool_delta" | "tool_end" | "permission_request" | "file_changed" | "final_answer" | "error";
  status: "queued" | "running" | "waiting_user" | "completed" | "failed";
  title: string;
  summary: string;
  content_delta?: string;
  command?: string[];
  artifact_refs?: string[];
  evidence_refs?: string[];
  model_provider?: string;
  model_name?: string;
  telemetry?: AnyRecord;
  phase?: "understand" | "plan" | "execute" | "review" | "resume" | "result" | "next" | string;
  display_level?: "main" | "inspector";
  created_at: string;
};

type WorkspaceFile = {
  path: string;
  size: number;
  modified_at: string;
};

type FilePreview = {
  ok: boolean;
  path?: string;
  content?: string;
  error?: string;
};

type SettingsPayload = {
  workMode: string;
  permissionMode: string;
  shell: string;
  streamMode: string;
  workspace: string;
  runtimeRoot: string;
};

const api = {
  sessions: (): Promise<{ ok: boolean; sessions: StudioSession[] }> => requestJson("/api/studio/sessions"),
  createSession: (): Promise<{ ok: boolean; session: StudioSession }> => requestJson("/api/studio/sessions", { method: "POST" }),
  session: (id: string): Promise<{ ok: boolean; session: StudioSession; events: StudioEvent[] }> => requestJson(`/api/studio/sessions/${encodeURIComponent(id)}`),
  events: (id: string): Promise<{ ok: boolean; events: StudioEvent[] }> => requestJson(`/api/studio/sessions/${encodeURIComponent(id)}/events`),
  send: (id: string, message: string, mode: string, permission: string): Promise<AnyRecord> => requestJson(`/api/studio/sessions/${encodeURIComponent(id)}/messages`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ message, mode, permission })
  }),
  files: (): Promise<{ ok: boolean; files: WorkspaceFile[] }> => requestJson("/api/studio/files"),
  previewFile: (path: string): Promise<FilePreview> => requestJson("/api/studio/files/preview", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ path })
  }),
  settings: (): Promise<{ ok: boolean; settings: SettingsPayload }> => requestJson("/api/studio/settings")
};

function App() {
  const [sessions, setSessions] = useState<StudioSession[]>([]);
  const [activeSession, setActiveSession] = useState<StudioSession | null>(null);
  const [events, setEvents] = useState<StudioEvent[]>([]);
  const [selectedEvent, setSelectedEvent] = useState<StudioEvent | null>(null);
  const [files, setFiles] = useState<WorkspaceFile[]>([]);
  const [preview, setPreview] = useState<FilePreview | null>(null);
  const [settings, setSettings] = useState<SettingsPayload | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function bootstrap() {
    setError(null);
    try {
      const [sessionData, fileData, settingsData] = await Promise.all([api.sessions(), api.files(), api.settings()]);
      let nextSessions = sessionData.sessions ?? [];
      if (!nextSessions.length) {
        const created = await api.createSession();
        nextSessions = [created.session];
      }
      setSessions(nextSessions);
      setFiles(fileData.files ?? []);
      setSettings(settingsData.settings);
      setActiveSession((current) => current ?? nextSessions[0]);
    } catch (err) {
      setError(String((err as Error).message || err));
    }
  }

  useEffect(() => {
    void bootstrap();
  }, []);

  useEffect(() => {
    if (!activeSession) return;
    let stopped = false;
    async function poll() {
      try {
        const data = await api.events(activeSession!.session_id);
        if (!stopped) setEvents(data.events ?? []);
      } catch {
        // Keep the thread responsive during transient API failures.
      }
    }
    void poll();
    const timer = window.setInterval(poll, 700);
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [activeSession]);

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
    const data = await api.events(activeSession.session_id);
    setEvents(data.events ?? []);
    const refreshed = await api.sessions();
    setSessions(refreshed.sessions ?? []);
  }

  async function openFile(path: string) {
    const result = await api.previewFile(path);
    setPreview(result);
  }

  return (
    <div className="appShell">
      <Sidebar sessions={sessions} active={activeSession} onSelect={setActiveSession} onNew={() => void newSession()} />
      <main className="threadPane">
        <header className="topBar">
          <div>
            <p className="eyebrow">Asteria Studio</p>
            <h1>{activeSession?.title ?? "Agent Workspace"}</h1>
            <p>{settings?.workspace ?? "Connecting..."}</p>
          </div>
          <div className="topActions">
            <span>{settings?.streamMode ?? "runtime-model-events"}</span>
            <button title="Refresh" onClick={() => void bootstrap()}><RefreshCw size={17} /></button>
          </div>
        </header>
        {error && <Banner tone="bad" text={error} />}
        <Thread events={events} selected={selectedEvent} onSelect={setSelectedEvent} />
        <Composer onSend={sendGoal} />
      </main>
      <Inspector event={selectedEvent} files={files} preview={preview} settings={settings} onOpenFile={openFile} />
    </div>
  );
}

function Sidebar({ sessions, active, onSelect, onNew }: { sessions: StudioSession[]; active: StudioSession | null; onSelect: (session: StudioSession) => void; onNew: () => void }) {
  return (
    <aside className="sidebar">
      <div className="brand">Asteria</div>
      <button className="newButton" onClick={onNew}>New task</button>
      <nav>
        {sessions.map((session) => (
          <button className={active?.session_id === session.session_id ? "session active" : "session"} key={session.session_id} onClick={() => onSelect(session)}>
            <span>{session.title || "Untitled"}</span>
            <small>{new Date(session.updated_at).toLocaleString()}</small>
          </button>
        ))}
      </nav>
      <div className="settingsLink"><Settings size={15} /> Settings</div>
    </aside>
  );
}

function Thread({ events, selected, onSelect }: { events: StudioEvent[]; selected: StudioEvent | null; onSelect: (event: StudioEvent) => void }) {
  const threadEvents = useMemo(() => toThreadEvents(events), [events]);
  if (!threadEvents.length) {
    return (
      <section className="emptyThread">
        <h2>What should Asteria work on?</h2>
        <p>Describe a goal. The agent will stream model feedback, planning, permission requests, files, and final answers into this thread.</p>
      </section>
    );
  }
  return (
    <section className="thread">
      {threadEvents.map((event) => (
        <EventCard event={event} selected={selected?.event_id === event.event_id} key={event.event_id} onSelect={() => onSelect(event)} />
      ))}
    </section>
  );
}

function EventCard({ event, selected, onSelect }: { event: StudioEvent; selected: boolean; onSelect: () => void }) {
  const [open, setOpen] = useState(event.type === "reasoning_delta" && event.status === "running");
  const icon = iconFor(event.type);
  const isUser = event.type === "user_message";
  const isModel = event.type === "model_start" || event.type === "model_delta" || event.type === "model_end" || event.type === "model_error";
  const showBody = isUser || isModel || event.type === "assistant_delta" || event.type === "reasoning_delta" || event.type === "final_answer" || event.type === "error" || event.type === "permission_request";
  const showCommandInline = event.type === "permission_request";
  return (
    <article className={`eventCard ${event.type} ${event.status} ${selected ? "selected" : ""}`} onClick={onSelect}>
      <div className="eventHeader">
        <div>
          <span className="eventIcon">{icon}</span>
          <strong>{phaseLabel(event.phase, event.title)}</strong>
          <Status status={event.status} />
        </div>
        {event.type === "reasoning_delta" && (
          <button className="foldButton" onClick={(click) => { click.stopPropagation(); setOpen(!open); }}>
            {open ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
          </button>
        )}
      </div>
      <p className="eventSummary">{event.summary}</p>
      {event.model_provider && <p className="eventMeta">{event.model_provider}/{event.model_name ?? "unknown"}</p>}
      {showBody && (open || event.type !== "reasoning_delta") && event.content_delta && <pre className={isUser ? "messageText" : "deltaText"}>{event.content_delta}</pre>}
      {showCommandInline && event.command && <code className="commandLine">{event.command.join(" ")}</code>}
    </article>
  );
}

function toThreadEvents(events: StudioEvent[]) {
  const result: StudioEvent[] = [];
  let activeModel: StudioEvent | null = null;
  for (const event of events) {
    if (event.display_level === "inspector" || event.type === "tool_start" || event.type === "tool_delta" || event.type === "tool_end") {
      continue;
    }
    if (event.type === "model_start") {
      activeModel = { ...event, type: "model_delta", summary: event.summary || "正在等待模型返回内容。" };
      result.push(activeModel);
      continue;
    }
    if (event.type === "model_delta") {
      if (activeModel && activeModel.phase === event.phase && activeModel.model_provider === event.model_provider) {
        activeModel.content_delta = `${activeModel.content_delta || ""}${event.content_delta || ""}`;
        activeModel.summary = event.summary || activeModel.summary;
        activeModel.status = event.status;
        activeModel.created_at = event.created_at;
      } else {
        activeModel = { ...event };
        result.push(activeModel);
      }
      continue;
    }
    if (event.type === "model_end") {
      if (activeModel && activeModel.phase === event.phase && activeModel.model_provider === event.model_provider) {
        activeModel.status = "completed";
        activeModel.summary = event.summary || activeModel.summary;
        activeModel.telemetry = event.telemetry;
      }
      activeModel = null;
      continue;
    }
    if (event.type === "model_error") {
      activeModel = null;
      result.push(event);
      continue;
    }
    activeModel = null;
    result.push(event);
  }
  return result;
}

function phaseLabel(phase: StudioEvent["phase"], fallback: string) {
  if (phase === "understand") return "理解目标";
  if (phase === "plan") return "制定计划";
  if (phase === "execute") return "执行";
  if (phase === "review") return "核对";
  if (phase === "resume") return "继续";
  if (phase === "result") return "结果";
  if (phase === "next") return "下一步";
  return fallback;
}

function Composer({ onSend }: { onSend: (message: string, mode: string, permission: string) => Promise<void> }) {
  const [message, setMessage] = useState("");
  const [mode, setMode] = useState("plan");
  const [permission, setPermission] = useState("ask");
  const [sending, setSending] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const text = message.trim();
    if (!text) return;
    setMessage("");
    setSending(true);
    try {
      await onSend(text, mode, permission);
    } finally {
      setSending(false);
    }
  }

  return (
    <form className="composer" onSubmit={(event) => void submit(event)}>
      <textarea value={message} onChange={(event) => setMessage(event.target.value)} placeholder="Ask Asteria to plan, build, inspect, or continue a task..." />
      <div className="composerBar">
        <select value={mode} onChange={(event) => setMode(event.target.value)}>
          <option value="plan">Plan</option>
          <option value="run">Run bounded</option>
          <option value="review">Review</option>
          <option value="resume">Resume</option>
        </select>
        <select value={permission} onChange={(event) => setPermission(event.target.value)}>
          <option value="ask">Ask before write/tools</option>
          <option value="allow">Allow once</option>
        </select>
        <button disabled={sending}><Send size={16} /> Send</button>
      </div>
    </form>
  );
}

function Inspector({ event, files, preview, settings, onOpenFile }: { event: StudioEvent | null; files: WorkspaceFile[]; preview: FilePreview | null; settings: SettingsPayload | null; onOpenFile: (path: string) => Promise<void> }) {
  const eventFiles = useMemo(() => files.slice(0, 12), [files]);
  return (
    <aside className="inspector">
      <section>
        <h2>Inspector</h2>
        {!event && <p className="muted">Select an event to inspect command output, evidence, and artifacts.</p>}
        {event && (
          <div className="detail">
            <strong>{event.title}</strong>
            <Status status={event.status} />
            {event.command && <code>{event.command.join(" ")}</code>}
            {event.model_provider && <small>{event.model_provider}/{event.model_name ?? "unknown"}</small>}
            {event.telemetry && <pre>{JSON.stringify(event.telemetry, null, 2)}</pre>}
            {event.content_delta && <pre>{event.content_delta}</pre>}
            {event.evidence_refs?.map((ref) => <small key={ref}>{ref}</small>)}
            {event.artifact_refs?.map((ref) => <small key={ref}>{ref}</small>)}
          </div>
        )}
      </section>
      <section>
        <h2>Files</h2>
        <div className="fileList">
          {eventFiles.map((file) => (
            <button key={file.path} onClick={() => void onOpenFile(file.path)}>
              <FileText size={14} />
              <span>{file.path}</span>
            </button>
          ))}
        </div>
        {preview && (
          <div className="preview">
            <strong>{preview.path ?? "Preview"}</strong>
            {preview.ok ? <pre>{(preview.content ?? "").slice(0, 5000)}</pre> : <p>{preview.error}</p>}
          </div>
        )}
      </section>
      <section>
        <h2>Runtime</h2>
        <p className="muted">Mode: {settings?.workMode ?? "unknown"}</p>
        <p className="muted">Permission: {settings?.permissionMode ?? "unknown"}</p>
        <p className="muted">Shell: {settings?.shell ?? "unknown"}</p>
      </section>
    </aside>
  );
}

function Status({ status }: { status: StudioEvent["status"] }) {
  return <span className={`status ${status}`}>{status}</span>;
}

function Banner({ text, tone }: { text: string; tone: "good" | "bad" }) {
  return <div className={`banner ${tone}`}>{tone === "good" ? <CheckCircle2 size={18} /> : <XCircle size={18} />} {text}</div>;
}

function iconFor(type: StudioEvent["type"]) {
  if (type === "tool_start" || type === "tool_delta" || type === "tool_end") return <Terminal size={15} />;
  if (type === "model_start" || type === "model_delta" || type === "model_end") return <Play size={15} />;
  if (type === "model_error") return <XCircle size={15} />;
  if (type === "permission_request") return <ShieldAlert size={15} />;
  if (type === "file_changed") return <FolderOpen size={15} />;
  if (type === "final_answer") return <CheckCircle2 size={15} />;
  if (type === "error") return <XCircle size={15} />;
  if (type === "reasoning_delta") return <Play size={15} />;
  return null;
}

async function requestJson(path: string, init?: RequestInit) {
  const response = await fetch(path, init);
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json();
}

createRoot(document.getElementById("root")!).render(<App />);
