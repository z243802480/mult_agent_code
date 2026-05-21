import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  ArrowUpRight,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CircleDot,
  Clock3,
  FileText,
  FolderOpen,
  GitBranch,
  Play,
  RefreshCw,
  Route,
  Send,
  Settings,
  ShieldAlert,
  Sparkles,
  Terminal,
  XCircle
} from "lucide-react";
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
  type:
    | "user_message"
    | "assistant_delta"
    | "reasoning_delta"
    | "model_start"
    | "model_delta"
    | "model_end"
    | "model_error"
    | "tool_start"
    | "tool_delta"
    | "tool_end"
    | "permission_request"
    | "file_changed"
    | "final_answer"
    | "error";
  status: "queued" | "running" | "waiting_user" | "completed" | "failed" | "blocked";
  title: string;
  summary: string;
  content_delta?: string;
  command?: string[];
  artifact_refs?: string[];
  evidence_refs?: string[];
  model_provider?: string;
  model_name?: string;
  telemetry?: AnyRecord;
  file_changes?: AnyRecord[];
  runtime_channel?: string;
  runtime_event_type?: string;
  source?: string;
  run_id?: string;
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

type OverviewPayload = {
  ok: boolean;
  workspace: string;
  runtimeRoot: string;
  gateStatus?: AnyRecord;
  doctor?: AnyRecord;
  packageCheck?: AnyRecord;
  runs?: AnyRecord[];
  modelRoutes?: AnyRecord[];
};

type RunDetailPayload = {
  ok: boolean;
  error?: string;
  run_id?: string;
  run?: AnyRecord;
  cost_report?: AnyRecord;
  goal_spec?: AnyRecord;
  task_plan?: AnyRecord;
  task_plan_eval?: AnyRecord;
  agent_run_graph?: AnyRecord;
  model_calls?: AnyRecord[];
  task_execution_evidence?: AnyRecord[];
  worker_results?: AnyRecord[];
  validation_results?: AnyRecord[];
  events?: AnyRecord[];
  user_progress?: AnyRecord[];
  files?: WorkspaceFile[];
};

type NarrativeStep = {
  id: string;
  label: string;
  title: string;
  summary: string;
  status: StudioEvent["status"];
  kind: "goal" | "thinking" | "plan" | "tool" | "result" | "repair" | "verification" | "final" | "error";
  events: StudioEvent[];
  defaultOpen: boolean;
};

type RunNarrative = {
  steps: NarrativeStep[];
  report: {
    status: "running" | "completed" | "failed";
    headline: string;
    goal: string;
    modelEvents: number;
    toolEvents: number;
    evidenceRefs: number;
    artifactRefs: number;
    finalText: string;
  };
};

const api = {
  sessions: (): Promise<{ ok: boolean; sessions: StudioSession[] }> => requestJson("/api/studio/sessions"),
  createSession: (): Promise<{ ok: boolean; session: StudioSession }> => requestJson("/api/studio/sessions", { method: "POST" }),
  events: (id: string): Promise<{ ok: boolean; events: StudioEvent[] }> => requestJson(`/api/studio/sessions/${encodeURIComponent(id)}/events`),
  send: (id: string, message: string, mode: string, permission: string): Promise<AnyRecord> =>
    requestJson(`/api/studio/sessions/${encodeURIComponent(id)}/messages`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ message, mode, permission })
    }),
  files: (): Promise<{ ok: boolean; files: WorkspaceFile[] }> => requestJson("/api/studio/files"),
  previewFile: (path: string): Promise<FilePreview> =>
    requestJson("/api/studio/files/preview", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ path })
    }),
  settings: (): Promise<{ ok: boolean; settings: SettingsPayload }> => requestJson("/api/studio/settings"),
  overview: (): Promise<OverviewPayload> => requestJson("/api/overview"),
  runDetail: (runId: string): Promise<RunDetailPayload> => requestJson(`/api/runs/${encodeURIComponent(runId)}`)
};

function App() {
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

  async function bootstrap() {
    setError(null);
    try {
      const [sessionData, fileData, settingsData, overviewData] = await Promise.all([api.sessions(), api.files(), api.settings(), api.overview()]);
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
    const timer = window.setInterval(poll, 900);
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [activeSession]);

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
    const data = await api.events(activeSession.session_id);
    setEvents(data.events ?? []);
    const refreshed = await api.sessions();
    setSessions(refreshed.sessions ?? []);
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

  const latestRun = overview?.runs?.[0];

  return (
    <div className="appShell">
      <Sidebar sessions={sessions} active={activeSession} overview={overview} onSelect={setActiveSession} onNew={() => void newSession()} />
      <main className="missionPane">
        <header className="topBar">
          <div>
            <p className="eyebrow">Asteria Studio</p>
            <h1>{activeSession?.title ?? "Agent Workspace"}</h1>
            <p>{settings?.workspace ?? "Connecting..."}</p>
          </div>
          <div className="topActions">
            <span><Route size={14} /> {routeDecision(overview)}</span>
            <button title="Refresh" onClick={() => void bootstrap()}><RefreshCw size={17} /></button>
          </div>
        </header>
        {error && <Banner tone="bad" text={error} />}
        <Readiness overview={overview} latestRun={latestRun} />
        <ActionableReadiness overview={overview} settings={settings} />
        <Thread events={events} selected={selectedEvent} onSelect={setSelectedEvent} />
        <Composer onSend={sendGoal} />
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

function Sidebar({
  sessions,
  active,
  overview,
  onSelect,
  onNew
}: {
  sessions: StudioSession[];
  active: StudioSession | null;
  overview: OverviewPayload | null;
  onSelect: (session: StudioSession) => void;
  onNew: () => void;
}) {
  return (
    <aside className="sidebar">
      <div className="brandBlock">
        <div className="brand">Asteria</div>
        <small>Local Runtime OS</small>
      </div>
      <button className="newButton" onClick={onNew}><Sparkles size={15} /> New task</button>
      <div className="sideSection">
        <p className="sideTitle">Workspace</p>
        <Metric label="Gate" value={gateStage(overview)} tone={readinessTone(overview)} />
        <Metric label="Routes" value={routeDecision(overview)} tone={routeTone(overview)} />
      </div>
      <nav className="sessionList">
        <p className="sideTitle">Sessions</p>
        {sessions.map((session) => (
          <button className={active?.session_id === session.session_id ? "session active" : "session"} key={session.session_id} onClick={() => onSelect(session)}>
            <span>{session.title || "Untitled"}</span>
            <small>{new Date(session.updated_at).toLocaleString()}</small>
          </button>
        ))}
      </nav>
      <div className="settingsLink"><Settings size={15} /> Local only</div>
    </aside>
  );
}

function Readiness({ overview, latestRun }: { overview: OverviewPayload | null; latestRun?: AnyRecord }) {
  const gate = overview?.gateStatus ?? {};
  const doctor = overview?.doctor ?? {};
  const packageCheck = overview?.packageCheck ?? {};
  return (
    <section className="readinessStrip">
      <SignalCard
        icon={<ShieldAlert size={17} />}
        label="Gate"
        value={gateStage(overview)}
        detail={firstText(gate.blocking_reason, gate.rollout_state, gate.status)}
        tone={readinessTone(overview)}
      />
      <SignalCard
        icon={<Route size={17} />}
        label="Provider Route"
        value={routeDecision(overview)}
        detail={routeDetail(overview)}
        tone={routeTone(overview)}
      />
      <SignalCard
        icon={<Terminal size={17} />}
        label="Runtime"
        value={healthValue(doctor, packageCheck)}
        detail={healthDetail(doctor, packageCheck)}
        tone={healthTone(doctor, packageCheck)}
      />
      <SignalCard
        icon={<GitBranch size={17} />}
        label="Latest Run"
        value={latestRun?.run_id ?? "no run"}
        detail={latestRunDetail(latestRun)}
        tone={latestRunTone(latestRun)}
      />
    </section>
  );
}

function SignalCard({ icon, label, value, detail, tone }: { icon: React.ReactNode; label: string; value: string; detail: string; tone: string }) {
  return (
    <div className={`signalCard ${tone}`}>
      <div className="signalHead">
        {icon}
        <span>{label}</span>
      </div>
      <strong>{value}</strong>
      <small>{detail || "No evidence yet"}</small>
    </div>
  );
}

function ActionableReadiness({ overview, settings }: { overview: OverviewPayload | null; settings: SettingsPayload | null }) {
  const actions = readinessActions(overview, settings).slice(0, 4);
  if (!actions.length) return null;
  return (
    <section className="actionableReadiness">
      <div>
        <p className="eyebrow">Actionable Readiness</p>
        <h2>Next safe moves</h2>
      </div>
      <div className="actionList">
        {actions.map((action) => (
          <div className={`actionItem ${action.tone}`} key={`${action.source}-${action.text}`}>
            <strong>{action.source}</strong>
            <span>{action.text}</span>
            {action.command && <code>{action.command}</code>}
          </div>
        ))}
      </div>
    </section>
  );
}

function Thread({ events, selected, onSelect }: { events: StudioEvent[]; selected: StudioEvent | null; onSelect: (event: StudioEvent) => void }) {
  const narrativeEvents = useMemo(() => toNarrativeEvents(events), [events]);
  const narrative = useMemo(() => buildRunNarrative(narrativeEvents), [narrativeEvents]);
  if (!narrativeEvents.length) {
    return (
      <section className="emptyThread">
        <div className="emptyPanel">
          <CircleDot size={25} />
          <h2>Start from a bounded runtime task</h2>
          <p>Plan first, then run with explicit permission. Studio keeps commands, route telemetry, artifacts, and evidence in the same task line.</p>
        </div>
      </section>
    );
  }
  return (
    <section className="thread">
      <NarrativeHeader narrative={narrative} />
      {narrative.steps.map((step) => (
        <NarrativeStepCard step={step} selected={selected} key={step.id} onSelect={onSelect} />
      ))}
      {(narrative.report.status === "completed" || narrative.report.status === "failed") && <RunReportV2 narrative={narrative} />}
    </section>
  );
}

function NarrativeHeader({ narrative }: { narrative: RunNarrative }) {
  const active = [...narrative.steps].reverse().find((step) => step.status === "running" || step.status === "waiting_user") ?? narrative.steps.at(-1);
  return (
    <section className={`narrativeHeader ${narrative.report.status}`}>
      <div>
        <p className="eyebrow">Run Narrative</p>
        <h2>{narrative.report.headline}</h2>
        <p>{active ? `${active.label}: ${active.summary}` : "Waiting for the first runtime event."}</p>
      </div>
      <div className="narrativeStats">
        <Metric label="Steps" value={String(narrative.steps.length)} tone="warn" />
        <Metric label="Tools" value={String(narrative.report.toolEvents)} tone="warn" />
        <Metric label="Evidence" value={String(narrative.report.evidenceRefs)} tone="good" />
      </div>
    </section>
  );
}

function NarrativeStepCard({
  step,
  selected,
  onSelect
}: {
  step: NarrativeStep;
  selected: StudioEvent | null;
  onSelect: (event: StudioEvent) => void;
}) {
  const [open, setOpen] = useState(step.defaultOpen);
  const primary = step.events[0];
  return (
    <article className={`narrativeStep ${step.kind} ${step.status}`}>
      <button className="stepChrome" onClick={() => setOpen(!open)}>
        <span className="stepIcon">{stepIcon(step.kind)}</span>
        <span>
          <strong>{step.label}</strong>
          <small>{step.title}</small>
        </span>
        <Status status={step.status} />
        {open ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
      </button>
      <div className="stepSummary">
        <p>{step.summary}</p>
        <div className="eventFacts">
          <span>{step.events.length} events</span>
          {primary?.model_provider && <span>{primary.model_provider}/{primary.model_name ?? "unknown"}</span>}
          <span>{primary ? new Date(primary.created_at).toLocaleTimeString() : "--:--"}</span>
        </div>
      </div>
      {open && (
        <div className="stepEvents">
          {step.events.map((event) => (
            <EventCard event={event} compact selected={selected?.event_id === event.event_id} key={event.event_id} onSelect={() => onSelect(event)} />
          ))}
        </div>
      )}
    </article>
  );
}

function RunReport({ narrative }: { narrative: RunNarrative }) {
  const [open, setOpen] = useState(false);
  const conclusionLabel = /已生成计划|Task plan quality|可执行计划/.test(narrative.report.finalText) ? "Plan conclusion" : "Result";
  return (
    <section className={`runReport ${narrative.report.status}`}>
      <button className="reportHeader" onClick={() => setOpen(!open)}>
        <CheckCircle2 size={16} />
        <span>
          <strong>Run Report</strong>
          <small>{narrative.report.headline}</small>
        </span>
        {open ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
      </button>
      <div className="reportGrid">
        <Metric label="Model" value={String(narrative.report.modelEvents)} tone="warn" />
        <Metric label="Tool" value={String(narrative.report.toolEvents)} tone="warn" />
        <Metric label="Artifacts" value={String(narrative.report.artifactRefs)} tone="good" />
        <Metric label="Evidence" value={String(narrative.report.evidenceRefs)} tone="good" />
      </div>
      {open && (
        <div className="reportBody">
          <p><strong>Goal</strong> {narrative.report.goal || "No explicit user goal captured."}</p>
          <p><strong>{conclusionLabel}</strong> {narrative.report.finalText || narrative.report.headline}</p>
          <p><strong>Process</strong> {narrative.steps.map((step) => step.label).join(" -> ")}</p>
        </div>
      )}
    </section>
  );
}

function RunReportV2({ narrative }: { narrative: RunNarrative }) {
  const [open, setOpen] = useState(true);
  const sections = useMemo(() => parseReportSections(narrative.report.finalText), [narrative.report.finalText]);
  const process = summarizeProcess(narrative.steps);
  const outcome = firstText(sections["结果"], sections.Result, narrative.report.finalText, narrative.report.headline);
  const plan = firstText(sections["计划内容"], sections.Plan);
  const quality = firstText(sections["质量判断"], sections.Validation, sections["验证"]);
  const risks = firstText(sections["风险与修正"], sections.Risks, sections["风险"]);
  const next = firstText(sections["下一步"], sections.Next);
  return (
    <section className={`runReport ${narrative.report.status}`}>
      <button className="reportHeader" onClick={() => setOpen(!open)}>
        <CheckCircle2 size={16} />
        <span>
          <strong>Run Report</strong>
          <small>{narrative.report.headline}</small>
        </span>
        {open ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
      </button>
      <div className="reportGrid">
        <Metric label="Model" value={String(narrative.report.modelEvents)} tone="warn" />
        <Metric label="Tool" value={String(narrative.report.toolEvents)} tone="warn" />
        <Metric label="Artifacts" value={String(narrative.report.artifactRefs)} tone="good" />
        <Metric label="Evidence" value={String(narrative.report.evidenceRefs)} tone="good" />
      </div>
      {open && (
        <div className="reportBody">
          <div className="reportLead">
            <span>目标</span>
            <p>{narrative.report.goal || "No explicit user goal captured."}</p>
          </div>
          <ReportSection title="结论" text={outcome} tone="outcome" />
          <div className="reportSection">
            <span>过程</span>
            <ol>
              {process.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ol>
          </div>
          {plan && <ReportSection title="产物" text={plan} />}
          <div className="reportSection">
            <span>证据</span>
            <p>
              记录了 {narrative.report.modelEvents} 个模型事件、{narrative.report.toolEvents} 个工具事件、{narrative.report.artifactRefs} 个产物引用和 {narrative.report.evidenceRefs} 个证据引用。
            </p>
          </div>
          {(quality || risks) && <ReportSection title="验证与风险" text={[quality, risks].filter(Boolean).join("\n")} />}
          {next && <ReportSection title="下一步" text={next} tone="next" />}
        </div>
      )}
    </section>
  );
}

function ReportSection({ title, text, tone = "" }: { title: string; text: string; tone?: string }) {
  return (
    <div className={`reportSection ${tone}`}>
      <span>{title}</span>
      <ReportText text={text} />
    </div>
  );
}

function ReportText({ text }: { text: string }) {
  const lines = text.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  if (lines.length > 1) {
    return (
      <ul>
        {lines.map((line) => (
          <li key={line}>{line.replace(/^-\s*/, "")}</li>
        ))}
      </ul>
    );
  }
  return <p>{text}</p>;
}

function EventCard({ event, selected, onSelect, compact = false }: { event: StudioEvent; selected: boolean; onSelect: () => void; compact?: boolean }) {
  const [open, setOpen] = useState(event.type === "reasoning_delta" && event.status === "running");
  const icon = iconFor(event.type);
  const isUser = event.type === "user_message";
  const isModel = event.type === "model_start" || event.type === "model_delta" || event.type === "model_end" || event.type === "model_error";
  const showBody =
    isUser ||
    isModel ||
    event.type === "assistant_delta" ||
    event.type === "reasoning_delta" ||
    event.type === "final_answer" ||
    event.type === "error" ||
    event.type === "permission_request";
  const showCommandInline = event.type === "permission_request";
  return (
    <article className={`eventCard ${event.type} ${event.status} ${selected ? "selected" : ""} ${compact ? "compact" : ""}`} onClick={onSelect}>
      <div className="phaseRail">
        <span>{phaseLabel(event.phase, event.title)}</span>
      </div>
      <div className="eventBody">
        <div className="eventHeader">
          <div>
            <span className="eventIcon">{icon}</span>
            <strong>{event.title}</strong>
            <Status status={event.status} />
          </div>
          {event.type === "reasoning_delta" && (
            <button className="foldButton" onClick={(click) => { click.stopPropagation(); setOpen(!open); }}>
              {open ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
            </button>
          )}
        </div>
        <p className="eventSummary">{event.summary}</p>
        <div className="eventFacts">
          {event.model_provider && <span>{event.model_provider}/{event.model_name ?? "unknown"}</span>}
          {!!event.evidence_refs?.length && <span>{event.evidence_refs.length} evidence</span>}
          {!!event.artifact_refs?.length && <span>{event.artifact_refs.length} artifacts</span>}
          <span>{new Date(event.created_at).toLocaleTimeString()}</span>
        </div>
        {showBody && (open || event.type !== "reasoning_delta") && event.content_delta && <pre className={isUser ? "messageText" : "deltaText"}>{event.content_delta}</pre>}
        {showCommandInline && event.command && <code className="commandLine">{event.command.join(" ")}</code>}
      </div>
    </article>
  );
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
      <textarea value={message} onChange={(event) => setMessage(event.target.value)} placeholder="Describe a bounded goal: update docs, inspect a run, fix one failing test, or plan the next change..." />
      <div className="composerBar">
        <div className="segmented">
          {["plan", "run", "review", "resume"].map((item) => (
            <button type="button" className={mode === item ? "active" : ""} key={item} onClick={() => setMode(item)}>
              {item}
            </button>
          ))}
        </div>
        <select value={permission} onChange={(event) => setPermission(event.target.value)} aria-label="Permission mode">
          <option value="ask">Ask before write/tools</option>
          <option value="allow">Allow once</option>
        </select>
        <button disabled={sending}><Send size={16} /> Send</button>
      </div>
    </form>
  );
}

function Inspector({
  event,
  files,
  preview,
  settings,
  overview,
  selectedRunId,
  runDetail,
  onOpenFile,
  onOpenRun
}: {
  event: StudioEvent | null;
  files: WorkspaceFile[];
  preview: FilePreview | null;
  settings: SettingsPayload | null;
  overview: OverviewPayload | null;
  selectedRunId: string | null;
  runDetail: RunDetailPayload | null;
  onOpenFile: (path: string) => Promise<void>;
  onOpenRun: (runId: string) => Promise<void>;
}) {
  const eventFiles = useMemo(() => files.slice(0, 12), [files]);
  const routes = overview?.modelRoutes?.slice(0, 5) ?? [];
  const inspectorSections = useMemo(() => buildInspectorSections(event), [event]);
  return (
    <aside className="inspector">
      <section>
        <h2>Selected Event</h2>
        {!event && <p className="muted">Select a timeline event to inspect commands, evidence, artifacts, and telemetry.</p>}
        {event && (
          <div className="detail">
            <div className="detailTitle">
              <strong>{event.title}</strong>
              <Status status={event.status} />
            </div>
            <InspectorTabs sections={inspectorSections} />
          </div>
        )}
      </section>
      <section>
        <h2>Model Routes</h2>
        <div className="routeList">
          {routes.length === 0 && <p className="muted">No route telemetry yet.</p>}
          {routes.map((route) => (
            <div className="routeItem" key={route.key}>
              <strong>{route.provider}/{route.model}</strong>
              <small>{route.purpose} · {route.tier} · {percent(route.successRate)} success</small>
              <small>{route.total ?? 0} calls · p95 {formatMs(route.durationP95)}</small>
            </div>
          ))}
        </div>
      </section>
      <EvidenceExplorer
        runs={overview?.runs ?? []}
        selectedRunId={selectedRunId}
        runDetail={runDetail}
        onOpenRun={onOpenRun}
        onOpenFile={onOpenFile}
      />
      <section>
        <h2>Files</h2>
        <div className="fileList">
          {eventFiles.map((file) => (
            <button key={file.path} onClick={() => void onOpenFile(file.path)}>
              <FileText size={14} />
              <span>{file.path}</span>
              <ArrowUpRight size={13} />
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
        <p className="muted">Stream: {settings?.streamMode ?? "unknown"}</p>
      </section>
    </aside>
  );
}

function RefList({ title, items }: { title: string; items: string[] }) {
  return (
    <div className="refList">
      <small>{title}</small>
      {items.map((item) => <code key={item}>{item}</code>)}
    </div>
  );
}

function EvidenceExplorer({
  runs,
  selectedRunId,
  runDetail,
  onOpenRun,
  onOpenFile
}: {
  runs: AnyRecord[];
  selectedRunId: string | null;
  runDetail: RunDetailPayload | null;
  onOpenRun: (runId: string) => Promise<void>;
  onOpenFile: (path: string) => Promise<void>;
}) {
  const modelCalls = runDetail?.model_calls ?? [];
  const validations = runDetail?.validation_results ?? [];
  const workers = runDetail?.worker_results ?? [];
  const evidence = runDetail?.task_execution_evidence ?? [];
  const userProgress = runDetail?.user_progress ?? [];
  const files = runDetail?.files ?? [];
  return (
    <section className="evidenceExplorer">
      <h2>Evidence Explorer</h2>
      <div className="runPicker">
        {runs.length === 0 && <p className="muted">No local run evidence yet.</p>}
        {runs.slice(0, 6).map((run) => {
          const runId = String(run.run_id ?? "");
          return (
            <button className={selectedRunId === runId ? "active" : ""} key={runId} onClick={() => void onOpenRun(runId)}>
              {runId}
            </button>
          );
        })}
      </div>
      {runDetail?.error && <p className="muted">{runDetail.error}</p>}
      {runDetail?.ok && (
        <>
          <div className="evidenceStats">
            <Metric label="Models" value={String(modelCalls.length)} tone={modelCalls.some((item) => item.status === "failure") ? "bad" : "good"} />
            <Metric label="Validation" value={String(validations.length)} tone={validations.some((item) => /fail|error/i.test(String(item.status ?? item.outcome ?? ""))) ? "bad" : "warn"} />
            <Metric label="Progress" value={String(userProgress.length)} tone={userProgress.length ? "good" : "warn"} />
          </div>
          <EvidenceBlock title="User Progress" items={userProgress.slice(-8)} render={userProgressLine} />
          <EvidenceBlock title="Run Summary" items={compactRecords(runDetail.run, runDetail.cost_report, runDetail.goal_spec)} render={summaryLine} />
          <EvidenceBlock title="Model Calls" items={modelCalls.slice(-5)} render={modelCallLine} />
          <EvidenceBlock title="Validation" items={validations.slice(-5)} render={validationLine} />
          <EvidenceBlock title="Worker Results" items={workers.slice(-4)} render={workerLine} />
          <EvidenceBlock title="Task Evidence" items={evidence.slice(-4)} render={evidenceLine} />
          {!!files.length && (
            <div className="runFiles">
              <small>Run files</small>
              {files.slice(0, 6).map((file) => (
                <button key={file.path} onClick={() => void onOpenFile(file.path)}>
                  <FileText size={13} />
                  <span>{file.path.split("/").pop()}</span>
                </button>
              ))}
            </div>
          )}
        </>
      )}
    </section>
  );
}

function EvidenceBlock({ title, items, render }: { title: string; items: AnyRecord[]; render: (item: AnyRecord) => string }) {
  return (
    <div className="evidenceBlock">
      <small>{title}</small>
      {!items.length && <p className="muted">No records captured.</p>}
      {items.map((item, index) => (
        <details key={`${title}-${index}`}>
          <summary>{render(item)}</summary>
          <pre>{JSON.stringify(item, null, 2)}</pre>
        </details>
      ))}
    </div>
  );
}

function compactRecords(...items: (AnyRecord | undefined)[]) {
  return items.filter((item): item is AnyRecord => Boolean(item));
}

function Metric({ label, value, tone }: { label: string; value: string; tone: string }) {
  return (
    <div className={`metric ${tone}`}>
      <small>{label}</small>
      <strong>{value}</strong>
    </div>
  );
}

function toNarrativeEvents(events: StudioEvent[]) {
  const result: StudioEvent[] = [];
  let activeModel: StudioEvent | null = null;
  for (const event of events) {
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
    if (event.type === "tool_start" || event.type === "tool_delta" || event.type === "tool_end") {
      activeModel = null;
      result.push(event);
      continue;
    }
    activeModel = null;
    result.push(event);
  }
  return result;
}

function buildRunNarrative(events: StudioEvent[]): RunNarrative {
  const visible = events;
  const steps: NarrativeStep[] = [];
  for (const event of visible) {
    const kind = narrativeKind(event);
    const label = narrativeLabel(kind, event);
    const previous = steps.at(-1);
    if (previous && previous.kind === kind && shouldGroup(previous, event)) {
      previous.events.push(event);
      previous.summary = event.summary || previous.summary;
      previous.status = mergeStatus(previous.status, event.status);
      previous.title = event.title || previous.title;
      continue;
    }
    steps.push({
      id: `${kind}-${steps.length}-${event.event_id}`,
      kind,
      label,
      title: event.title,
      summary: event.summary || event.content_delta || event.title,
      status: event.status,
      events: [event],
      defaultOpen: kind === "goal" || kind === "final" || event.status === "running" || event.status === "waiting_user"
    });
  }
  const finalEvent = [...visible].reverse().find((event) => event.type === "final_answer" || event.type === "error");
  const goalEvent = visible.find((event) => event.type === "user_message");
  const status = finalEvent?.type === "error" ? "failed" : finalEvent ? "completed" : "running";
  if (status !== "running") {
    for (const step of steps) {
      if (step.status === "running" || step.status === "queued") step.status = "completed";
      step.events = step.events.map((event) =>
        event.status === "running" || event.status === "queued" ? { ...event, status: "completed" } : event
      );
    }
  }
  return {
    steps,
    report: {
      status,
      headline: status === "running" ? "Agent is working through the task." : status === "failed" ? "Run ended with an issue." : "Run completed with a final answer.",
      goal: goalEvent?.summary ?? "",
      modelEvents: visible.filter((event) => event.type.startsWith("model_") || event.type === "assistant_delta" || event.type === "reasoning_delta").length,
      toolEvents: events.filter((event) => event.type.startsWith("tool_") || event.command?.length).length,
      evidenceRefs: countRefs(visible, "evidence_refs"),
      artifactRefs: countRefs(visible, "artifact_refs"),
      finalText: finalEvent?.content_delta ?? finalEvent?.summary ?? ""
    }
  };
}

function narrativeKind(event: StudioEvent): NarrativeStep["kind"] {
  if (event.type === "user_message") return "goal";
  if (event.type === "permission_request") return "tool";
  if (event.type === "tool_start" || event.type === "tool_delta" || event.type === "tool_end") return "tool";
  if (event.type === "model_error" || event.type === "error") return "error";
  if (event.type === "final_answer") return "final";
  if (event.phase === "plan") return "plan";
  if (event.phase === "review") return "verification";
  if (event.phase === "execute" || event.phase === "resume") return event.status === "failed" ? "repair" : "tool";
  if (event.type === "model_start" || event.type === "model_delta" || event.type === "model_end" || event.type === "reasoning_delta") return "thinking";
  if (event.type === "file_changed") return "result";
  return "thinking";
}

function narrativeLabel(kind: NarrativeStep["kind"], event: StudioEvent) {
  if (kind === "goal") return "User Goal";
  if (kind === "thinking" && event.phase === "plan" && event.model_provider) return "Structured Generation";
  if (kind === "thinking") return "Thinking";
  if (kind === "plan") return "Plan";
  if (kind === "tool") return event.command?.length ? "Tool Call" : "Action";
  if (kind === "result") return "Tool Result";
  if (kind === "repair") return "Repair Loop";
  if (kind === "verification") return "Verification";
  if (kind === "final") return "Final Answer";
  return "Issue";
}

function shouldGroup(step: NarrativeStep, event: StudioEvent) {
  const first = step.events[0];
  if (step.kind === "goal" || step.kind === "final" || step.kind === "error") return false;
  if (step.kind === "thinking") return first.phase === event.phase && first.model_provider === event.model_provider;
  if (step.kind === "tool") {
    if (first.command?.join(" ") === event.command?.join(" ")) return true;
    return first.type.startsWith("tool_") && event.type.startsWith("tool_") && first.title === event.title;
  }
  return first.phase === event.phase;
}

function mergeStatus(current: StudioEvent["status"], next: StudioEvent["status"]): StudioEvent["status"] {
  if (next === "failed" || current === "failed") return "failed";
  if (next === "waiting_user" || current === "waiting_user") return "waiting_user";
  if (next === "running" || current === "running") return "running";
  if (next === "queued" || current === "queued") return "queued";
  return "completed";
}

function countRefs(events: StudioEvent[], key: "evidence_refs" | "artifact_refs") {
  return events.reduce((count, event) => count + (event[key]?.length ?? 0), 0);
}

function parseReportSections(text: string) {
  const sections: Record<string, string> = {};
  let current = "Result";
  for (const rawLine of String(text || "").split(/\r?\n/)) {
    const heading = rawLine.match(/^##\s+(.+?)\s*$/);
    if (heading) {
      current = heading[1].trim();
      sections[current] = "";
      continue;
    }
    sections[current] = [sections[current], rawLine].filter(Boolean).join("\n").trim();
  }
  return sections;
}

function summarizeProcess(steps: NarrativeStep[]) {
  const labels = new Set(steps.map((step) => step.label));
  const items: string[] = [];
  if (labels.has("User Goal")) items.push("接收用户目标，并把它固定为本次 run 的任务契约。");
  if (labels.has("Thinking") || labels.has("Structured Generation")) items.push("接收模型输出，把结构化生成归入规划过程，而不是混进工具日志。");
  if (labels.has("Plan")) items.push("生成任务计划，包含验收条件、运行约束和执行边界。");
  if (labels.has("Tool Call") || labels.has("Action")) items.push("调用本地 runtime 命令，并把原始命令输出留在 Inspector 证据链中。");
  if (labels.has("Verification")) items.push("收集验证或审查信号，用于判断结果是否可信。");
  if (labels.has("Final Answer")) items.push("将过程折叠成最终报告，明确结论、证据、风险和下一步。");
  return items.length ? items : steps.map((step) => `${step.label}: ${step.summary}`).slice(0, 6);
}

function phaseLabel(phase: StudioEvent["phase"], fallback: string) {
  if (phase === "understand") return "understand";
  if (phase === "plan") return "plan";
  if (phase === "execute") return "execute";
  if (phase === "review") return "review";
  if (phase === "resume") return "resume";
  if (phase === "result") return "result";
  if (phase === "next") return "next";
  return fallback;
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
  if (type === "reasoning_delta") return <Clock3 size={15} />;
  return null;
}

function stepIcon(kind: NarrativeStep["kind"]) {
  if (kind === "goal") return <CircleDot size={15} />;
  if (kind === "thinking") return <Clock3 size={15} />;
  if (kind === "plan") return <GitBranch size={15} />;
  if (kind === "tool") return <Terminal size={15} />;
  if (kind === "result") return <FileText size={15} />;
  if (kind === "repair") return <RefreshCw size={15} />;
  if (kind === "verification") return <ShieldAlert size={15} />;
  if (kind === "final") return <CheckCircle2 size={15} />;
  return <XCircle size={15} />;
}

function gateStage(overview: OverviewPayload | null) {
  const gate = overview?.gateStatus ?? {};
  return String(gate.stage ?? gate.rollout_state ?? "unknown");
}

function readinessTone(overview: OverviewPayload | null) {
  const gate = overview?.gateStatus ?? {};
  if (gate.release_ready || /ready/i.test(String(gate.stage ?? gate.rollout_state ?? ""))) return "good";
  if (/blocked|failed|missing/i.test(String(gate.stage ?? gate.rollout_state ?? gate.status ?? ""))) return "bad";
  return "warn";
}

function routeDecision(overview: OverviewPayload | null) {
  const strategy = overview?.gateStatus?.route_guidance?.provider_route_strategy;
  return String(strategy?.decision ?? overview?.gateStatus?.route_guidance?.status ?? "route unknown");
}

function routeTone(overview: OverviewPayload | null) {
  const value = routeDecision(overview);
  if (/continue|healthy|allow/i.test(value)) return "good";
  if (/block|failed|missing/i.test(value)) return "bad";
  return "warn";
}

function routeDetail(overview: OverviewPayload | null) {
  const guidance = overview?.gateStatus?.route_guidance ?? {};
  const strategy = guidance.provider_route_strategy ?? {};
  return firstText(strategy.primary_model, guidance.status, strategy.recommended_action, guidance.blocking_reason);
}

function healthValue(doctor: AnyRecord, packageCheck: AnyRecord) {
  if (doctor.ok === false || packageCheck.ok === false) return "needs attention";
  if (doctor.ok === true && packageCheck.ok === true) return "checks pass";
  return "checking";
}

function healthDetail(doctor: AnyRecord, packageCheck: AnyRecord) {
  return firstText(doctor.status, packageCheck.status, `${Object.keys(doctor.checks ?? {}).length + Object.keys(packageCheck.checks ?? {}).length} checks`);
}

function healthTone(doctor: AnyRecord, packageCheck: AnyRecord) {
  if (doctor.ok === false || packageCheck.ok === false) return "bad";
  if (doctor.ok === true && packageCheck.ok === true) return "good";
  return "warn";
}

function latestRunDetail(run?: AnyRecord) {
  if (!run) return "No local run evidence";
  return firstText(run.status, run.cost_report?.model_calls != null ? `${run.cost_report.model_calls} model calls` : "", run.created_at);
}

function latestRunTone(run?: AnyRecord) {
  if (!run) return "warn";
  if (/failed|blocked/i.test(String(run.status ?? ""))) return "bad";
  if (/complete|success|ready/i.test(String(run.status ?? ""))) return "good";
  return "warn";
}

function readinessActions(overview: OverviewPayload | null, settings: SettingsPayload | null) {
  const gate = overview?.gateStatus ?? {};
  const routeGuidance = gate.route_guidance ?? {};
  const routeStrategy = routeGuidance.provider_route_strategy ?? {};
  const validation = gate.validation_recommendation ?? {};
  const risks = gate.promotion_release_risks ?? {};
  const root = settings?.workspace ?? overview?.workspace ?? ".";
  const actions: { source: string; text: string; command?: string; tone: string }[] = [];
  for (const action of gate.next_actions ?? []) {
    actions.push({ source: "Gate", text: String(action), tone: readinessActionTone(action) });
  }
  for (const action of routeGuidance.recommended_actions ?? []) {
    actions.push({ source: "Route", text: String(action), tone: routeGuidance.status === "blocked" ? "bad" : "warn" });
  }
  if (routeStrategy.recommended_action) {
    actions.push({ source: "Provider", text: String(routeStrategy.recommended_action), tone: routeTone(overview) });
  }
  if (validation.command || validation.level) {
    actions.push({
      source: "Validation",
      text: String(validation.reason ?? validation.level ?? "Run the recommended validation scope."),
      command: String(validation.command ?? `python -m asteria_runtime gate-status --root ${root} --json`),
      tone: "warn"
    });
  }
  if (Number(risks.pending ?? 0) > 0 || Number(risks.blocked ?? 0) > 0) {
    actions.push({
      source: "Promotion",
      text: "Resolve candidate promotion queue before widening gray or release.",
      command: `python -m asteria_runtime gate-status --root ${root} --json`,
      tone: "bad"
    });
  }
  return dedupeActions(actions);
}

function dedupeActions(actions: { source: string; text: string; command?: string; tone: string }[]) {
  const seen = new Set<string>();
  return actions.filter((action) => {
    const key = `${action.source}:${action.text}:${action.command ?? ""}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return action.text.trim().length > 0;
  });
}

function readinessActionTone(value: unknown) {
  const text = String(value ?? "");
  if (/block|fail|missing|resolve|approval|risk/i.test(text)) return "bad";
  if (/run|gray|acceptance|review|inspect/i.test(text)) return "warn";
  return "good";
}

function summaryLine(item: AnyRecord) {
  return firstText(item.run_id, item.goal, item.title, item.status, item.schema_version, `${Object.keys(item).length} fields`);
}

function modelCallLine(item: AnyRecord) {
  const route = [item.model_provider, item.model_name, item.purpose].filter(Boolean).join("/");
  return firstText(`${route || "model"} ${item.status ?? ""} ${formatMs(item.duration_ms ?? item.streaming?.duration_ms)}`, item.error, item.id);
}

function validationLine(item: AnyRecord) {
  return firstText(`${item.name ?? item.command ?? "validation"} ${item.status ?? item.outcome ?? ""}`, item.summary, item.error);
}

function workerLine(item: AnyRecord) {
  return firstText(`${item.task_id ?? item.worker_id ?? "worker"} ${item.status ?? item.outcome ?? ""}`, item.summary, item.error);
}

function evidenceLine(item: AnyRecord) {
  return firstText(`${item.task_id ?? item.kind ?? "evidence"} ${item.status ?? item.outcome ?? ""}`, item.summary, item.path);
}

type InspectorSection = {
  id: string;
  title: string;
  count: number;
  empty: string;
  content: React.ReactNode;
};

function InspectorTabs({ sections }: { sections: InspectorSection[] }) {
  const [active, setActive] = useState(sections.find((section) => section.count > 0)?.id ?? sections[0]?.id ?? "shell");
  useEffect(() => {
    if (!sections.some((section) => section.id === active && section.count > 0)) {
      setActive(sections.find((section) => section.count > 0)?.id ?? sections[0]?.id ?? "shell");
    }
  }, [sections, active]);
  const selected = sections.find((section) => section.id === active) ?? sections[0];
  return (
    <div className="inspectorTabs">
      <div className="inspectorTabList">
        {sections.map((section) => (
          <button className={section.id === active ? "active" : ""} key={section.id} onClick={() => setActive(section.id)}>
            {section.title}
            <span>{section.count}</span>
          </button>
        ))}
      </div>
      <div className="inspectorTabPanel">
        {selected?.count ? selected.content : <p className="muted">{selected?.empty}</p>}
      </div>
    </div>
  );
}

function buildInspectorSections(event: StudioEvent | null): InspectorSection[] {
  if (!event) return [];
  const shellItems = [
    ...(event.command?.length ? [{ label: "Command", value: event.command.join(" ") }] : []),
    ...(event.content_delta && (event.type.startsWith("tool_") || event.runtime_channel === "tool")
      ? [{ label: "Output", value: event.content_delta }]
      : []),
  ];
  const fileChanges = event.file_changes ?? [];
  const artifacts = event.artifact_refs ?? [];
  const evidence = event.evidence_refs ?? [];
  const diagnostics = compactRecords(
    event.model_provider ? { provider: event.model_provider, model: event.model_name } : undefined,
    event.telemetry,
    event.source ? { source: event.source, channel: event.runtime_channel, event_type: event.runtime_event_type, run_id: event.run_id } : undefined,
    event.content_delta && !event.type.startsWith("tool_") ? { content: event.content_delta } : undefined
  );
  return [
    {
      id: "shell",
      title: "Shell",
      count: shellItems.length,
      empty: "No shell command or tool output on this event.",
      content: <KeyValueList items={shellItems} />,
    },
    {
      id: "diff",
      title: "Diff",
      count: fileChanges.length,
      empty: "No file changes attached to this event.",
      content: <RecordList items={fileChanges} render={fileChangeLine} />,
    },
    {
      id: "artifact",
      title: "Artifacts",
      count: artifacts.length + evidence.length,
      empty: "No artifact or evidence refs attached.",
      content: (
        <>
          {!!artifacts.length && <RefList title="Artifacts" items={artifacts} />}
          {!!evidence.length && <RefList title="Evidence" items={evidence} />}
        </>
      ),
    },
    {
      id: "diagnostic",
      title: "Diagnostic",
      count: diagnostics.length,
      empty: "No diagnostic telemetry attached.",
      content: <RecordList items={diagnostics} render={diagnosticLine} />,
    },
  ];
}

function KeyValueList({ items }: { items: { label: string; value: string }[] }) {
  return (
    <div className="keyValueList">
      {items.map((item) => (
        <div key={item.label}>
          <small>{item.label}</small>
          <pre>{item.value}</pre>
        </div>
      ))}
    </div>
  );
}

function RecordList({ items, render }: { items: AnyRecord[]; render: (item: AnyRecord) => string }) {
  return (
    <div className="recordList">
      {items.map((item, index) => (
        <details key={`${render(item)}-${index}`}>
          <summary>{render(item)}</summary>
          <pre>{JSON.stringify(item, null, 2)}</pre>
        </details>
      ))}
    </div>
  );
}

function userProgressLine(item: AnyRecord) {
  return firstText(
    `${item.channel ?? "progress"}/${item.event_type ?? "message"} ${item.phase ?? ""} ${item.status ?? ""}`,
    item.summary,
    item.title
  );
}

function fileChangeLine(item: AnyRecord) {
  return firstText(`${item.operation ?? item.event_type ?? "change"} ${item.path ?? ""}`, item.summary);
}

function diagnosticLine(item: AnyRecord) {
  return firstText(item.provider ? `${item.provider}/${item.model ?? "unknown"}` : "", item.source ? `${item.source} ${item.channel ?? ""}/${item.event_type ?? ""}` : "", item.content, JSON.stringify(item));
}

function firstText(...items: unknown[]) {
  for (const item of items) {
    const text = String(item ?? "").trim();
    if (text) return text;
  }
  return "";
}

function percent(value: unknown) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "n/a";
  return `${Math.round(number * 100)}%`;
}

function formatMs(value: unknown) {
  if (value === null || value === undefined || value === "") return "n/a";
  const number = Number(value);
  if (!Number.isFinite(number)) return "n/a";
  return `${Math.round(number)}ms`;
}

async function requestJson(path: string, init?: RequestInit) {
  const response = await fetch(path, init);
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json();
}

createRoot(document.getElementById("root")!).render(<App />);
