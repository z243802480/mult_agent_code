import React, { useMemo, useState, useEffect } from "react";
import { ArrowUpRight, Bug, FileText, SendHorizontal } from "lucide-react";
import type { StudioEvent, WorkspaceFile, FilePreview, SettingsPayload, OverviewPayload, RunDetailPayload, AnyRecord } from "../types";
import { Status, Metric, formatMs, percent } from "./Shared";
import { firstText } from "../narrative";

type InspectorSection = {
  id: string;
  title: string;
  count: number;
  empty: string;
  content: React.ReactNode;
};

function AiDebugAgentCard({ runDetail, selectedRunId }: { runDetail: RunDetailPayload | null; selectedRunId: string | null }) {
  const [question, setQuestion] = useState("");
  const latestRunId = selectedRunId || String(runDetail?.run_id ?? "");
  return (
    <section className="debugAgentCard">
      <div className="debugAgentHeader">
        <span className="debugAgentIcon"><Bug size={15} /></span>
        <div>
          <h2>AI Debug Agent</h2>
          <p>Ask backend questions about runs, blockers, evidence, model routes, costs, gates, and policies.</p>
        </div>
      </div>
      <div className="debugAgentHints">
        <button type="button" onClick={() => setQuestion("Why is the latest run blocked?")}>Why blocked?</button>
        <button type="button" onClick={() => setQuestion("Why did Asteria choose this model route?")}>Model route?</button>
        <button type="button" onClick={() => setQuestion("What backend action should I take next?")}>Next action?</button>
      </div>
      <form
        className="debugAgentComposer"
        onSubmit={(event) => {
          event.preventDefault();
          if (!question.trim()) return;
          setQuestion("");
        }}
      >
        <textarea
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="Ask an Ops question, e.g. why is this run blocked?"
          rows={2}
        />
        <button type="submit" title="Debug Agent response is coming next">
          <SendHorizontal size={14} />
        </button>
      </form>
      <p className="debugAgentNote">
        Skeleton only: the next step is to connect this to a read-only debug answer that uses current session/run context{latestRunId ? ` (${latestRunId})` : ""}.
      </p>
    </section>
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

function buildInspectorSections(event: StudioEvent | null): InspectorSection[] {
  if (!event) return [];
  const shellItems = [
    ...(event.command?.length ? [{ label: "Command", value: event.command.join(" ") }] : []),
    ...(event.content_delta && (event.type.startsWith("tool_") || event.runtime_channel === "tool")
      ? [{ label: "Output", value: event.content_delta }]
      : []),
  ];
  const fileChanges = (event.file_changes ?? []) as AnyRecord[];
  const artifacts = event.artifact_refs ?? [];
  const evidence = event.evidence_refs ?? [];
  const intentDiagnostics: AnyRecord[] = [
    ...(event.intent_audit ? [event.intent_audit] : []),
    ...(event.intent_route ? [{ intent_route: event.intent_route }] : []),
  ];
  const diagnostics: AnyRecord[] = [
    ...(event.model_provider ? [{ provider: event.model_provider, model: event.model_name }] : []),
    ...(event.telemetry ? [event.telemetry] : []),
    ...(event.source
      ? [{ source: event.source, channel: event.runtime_channel, event_type: event.runtime_event_type, run_id: event.run_id }]
      : []),
    ...(event.content_delta && !event.type.startsWith("tool_") ? [{ content: event.content_delta }] : []),
  ].filter(Boolean);

  return [
    {
      id: "intent",
      title: "Intent",
      count: intentDiagnostics.length,
      empty: "This event has no intent routing metadata.",
      content: <IntentAuditView items={intentDiagnostics} />,
    },
    {
      id: "shell",
      title: "Shell",
      count: shellItems.length,
      empty: "This event has no shell command or tool output.",
      content: <KeyValueList items={shellItems} />,
    },
    {
      id: "diff",
      title: "Diff",
      count: fileChanges.length,
      empty: "This event has no file changes.",
      content: (
        <RecordList
          items={fileChanges}
          render={(item) => firstText(`${String(item.operation ?? item.event_type ?? "change")} ${String(item.path ?? "")}`)}
        />
      ),
    },
    {
      id: "artifact",
      title: "Artifacts",
      count: artifacts.length + evidence.length,
      empty: "This event has no artifact or evidence references.",
      content: (
        <>
          {artifacts.length > 0 && <RefList title="Artifacts" items={artifacts} />}
          {evidence.length > 0 && <RefList title="Evidence" items={evidence} />}
        </>
      ),
    },
    {
      id: "diagnostic",
      title: "Diagnostics",
      count: diagnostics.length,
      empty: "This event has no diagnostics.",
      content: (
        <RecordList
          items={diagnostics}
          render={(item) =>
            firstText(
              item.provider ? `${String(item.provider)}/${String(item.model ?? "unknown")}` : "",
              item.source ? `${String(item.source)} ${String(item.channel ?? "")}/${String(item.event_type ?? "")}` : "",
              String(item.content ?? ""),
              JSON.stringify(item)
            )
          }
        />
      ),
    },
  ];
}

function IntentAuditView({ items }: { items: AnyRecord[] }) {
  const audit = (items.find((item) => item.intent_kind || item.route || item.permission_effect) ?? {}) as AnyRecord;
  if (!items.length) return null;
  return (
    <div className="intentAudit">
      <div className="intentAuditGrid">
        <Metric label="Route" value={String(audit.route ?? audit.selected_mode ?? "unknown")} tone="good" />
        <Metric label="Intent" value={String(audit.intent_kind ?? "unknown")} tone="warn" />
        <Metric label="Permission" value={String(audit.permission_effect ?? "unknown")} tone={String(audit.permission_effect ?? "").includes("execute") ? "warn" : "good"} />
      </div>
      <div className="keyValueList">
        <div><small>Reason</small><pre>{String(audit.reason ?? "No route reason recorded.")}</pre></div>
        <div><small>Prompt enrichment</small><pre>{String(audit.prompt_enrichment ?? "none")}</pre></div>
        <div><small>Raw metadata</small><pre>{JSON.stringify(items, null, 2)}</pre></div>
      </div>
    </div>
  );
}

function InspectorTabs({ sections }: { sections: InspectorSection[] }) {
  const [active, setActive] = useState(sections.find((s) => s.count > 0)?.id ?? sections[0]?.id ?? "shell");
  useEffect(() => {
    if (!sections.some((s) => s.id === active && s.count > 0)) {
      setActive(sections.find((s) => s.count > 0)?.id ?? sections[0]?.id ?? "shell");
    }
  }, [sections, active]);
  const selected = sections.find((s) => s.id === active) ?? sections[0];
  return (
    <div className="inspectorTabs">
      <div className="inspectorTabList">
        {sections.map((s) => (
          <button className={s.id === active ? "active" : ""} key={s.id} onClick={() => setActive(s.id)}>
            {s.title}
            <span>{s.count}</span>
          </button>
        ))}
      </div>
      <div className="inspectorTabPanel">
        {selected?.count ? selected.content : <p className="muted">{selected?.empty}</p>}
      </div>
    </div>
  );
}

function RunStatusPanel({ runDetail }: { runDetail: RunDetailPayload }) {
  const run = (runDetail.run ?? {}) as AnyRecord;
  const finalSummary = (runDetail.final_report_summary ?? {}) as AnyRecord;
  const runLoopSummary = (runDetail.run_loop_summary ?? {}) as AnyRecord;
  const routeArtifact = (runDetail.model_route_timeline ?? {}) as AnyRecord;
  const goalPolicy = (finalSummary.goal_policy ?? runDetail.goal_policy ?? {}) as AnyRecord;
  const timeline = (
    Array.isArray(routeArtifact.timeline)
      ? routeArtifact.timeline
      : Array.isArray(routeArtifact.route_timeline)
        ? routeArtifact.route_timeline
        : Array.isArray(finalSummary.model_route_timeline)
          ? finalSummary.model_route_timeline
          : []
  ) as AnyRecord[];
  const latestRoute = timeline.at(-1) ?? {};
  const workflowState = firstText(String(finalSummary.workflow_state ?? ""), String(runLoopSummary.workflow_state ?? ""), String(run.current_phase ?? "unknown"));
  const nextCommand = firstText(String(finalSummary.recommended_next_command ?? ""), String(runLoopSummary.recommended_next_command ?? ""), "none");
  const blocker = firstText(String(finalSummary.current_blocker ?? ""), String(runLoopSummary.current_blocker ?? ""), "none");

  return (
    <div className="evidenceBlock runStatusPanel">
      <small>Long-task loop</small>
      <div className="evidenceStats">
        <Metric label="State" value={workflowState} tone={/blocked|fail|need/i.test(workflowState) ? "bad" : "good"} />
        <Metric label="Next" value={nextCommand} tone={nextCommand === "none" ? "good" : "warn"} />
        <Metric label="Policy" value={String(goalPolicy.category ?? "none")} tone={String(goalPolicy.category ?? "none") === "none" ? "good" : "warn"} />
      </div>
      <div className="keyValueList">
        <div><small>Current status</small><pre>{`${String(run.status ?? "unknown")} / ${String(run.current_phase ?? "unknown")}`}</pre></div>
        <div><small>Current blocker</small><pre>{blocker}</pre></div>
        <div><small>Recommended command</small><pre>{nextCommand === "none" ? "No action needed" : `asteria ${nextCommand}`}</pre></div>
        <div><small>Goal policy</small><pre>{`${String(goalPolicy.category ?? "none")} -> ${String(goalPolicy.recommended_command ?? goalPolicy.recommended_next_command ?? goalPolicy.recommended_action ?? nextCommand)}
${String(goalPolicy.reason ?? "No policy reason recorded.")}`}</pre></div>
        <div><small>Run loop summary</small><pre>{`iterations=${String(runLoopSummary.iteration_count ?? "n/a")}
stop=${String(runLoopSummary.stop_reason ?? "n/a")}`}</pre></div>
        <div><small>Model route rationale</small><pre>{`${String(latestRoute.purpose ?? "unknown")} -> ${String(latestRoute.selected_tier ?? "unknown")}
reason=${String(latestRoute.reason ?? "No route reason recorded.")}`}</pre></div>
      </div>
    </div>
  );
}

function EvidenceExplorer({
  runs,
  selectedRunId,
  runDetail,
  onOpenRun,
  onOpenFile,
}: {
  runs: AnyRecord[];
  selectedRunId: string | null;
  runDetail: RunDetailPayload | null;
  onOpenRun: (runId: string) => Promise<void>;
  onOpenFile: (path: string) => Promise<void>;
}) {
  const modelCalls = (runDetail?.model_calls ?? []) as AnyRecord[];
  const validations = (runDetail?.validation_results ?? []) as AnyRecord[];
  const workers = (runDetail?.worker_results ?? []) as AnyRecord[];
  const evidence = (runDetail?.task_execution_evidence ?? []) as AnyRecord[];
  const finalSummary = (runDetail?.final_report_summary ?? {}) as AnyRecord;
  const routeArtifact = (runDetail?.model_route_timeline ?? {}) as AnyRecord;
  const routeTimeline = (
    Array.isArray(routeArtifact.timeline)
      ? routeArtifact.timeline
      : Array.isArray(routeArtifact.route_timeline)
        ? routeArtifact.route_timeline
        : Array.isArray(finalSummary.model_route_timeline)
          ? finalSummary.model_route_timeline
          : []
  ) as AnyRecord[];
  const userProgress = (runDetail?.user_progress ?? []) as AnyRecord[];
  const files = runDetail?.files ?? [];

  function renderLine(item: AnyRecord, kind: string): string {
    if (kind === "progress") return firstText(`${String(item.channel ?? "progress")}/${String(item.event_type ?? "message")} ${String(item.phase ?? "")} ${String(item.status ?? "")}`, String(item.summary ?? ""), String(item.title ?? ""));
    if (kind === "model") {
      const route = [item.model_provider, item.model_name, item.purpose].filter(Boolean).join("/");
      return firstText(`${route || "model"} ${String(item.status ?? "")} ${formatMs(item.duration_ms)}`, String(item.error ?? ""));
    }
    if (kind === "validation") return firstText(`${String(item.name ?? item.command ?? "validation")} ${String(item.status ?? item.outcome ?? "")}`, String(item.summary ?? ""));
    if (kind === "worker") return firstText(`${String(item.task_id ?? item.worker_id ?? "worker")} ${String(item.status ?? item.outcome ?? "")}`, String(item.summary ?? ""));
    if (kind === "evidence") return firstText(`${String(item.task_id ?? item.kind ?? "evidence")} ${String(item.status ?? item.outcome ?? "")}`, String(item.path ?? ""));
    if (kind === "route") return firstText(`${String(item.task_id ?? item.purpose ?? "route")} ${String(item.purpose ?? "")} -> ${String(item.selected_tier ?? "unknown")}`, String(item.reason ?? ""));
    return JSON.stringify(item).slice(0, 80);
  }

  function EvidenceBlock({ title, items, kind }: { title: string; items: AnyRecord[]; kind: string }) {
    return (
      <div className="evidenceBlock">
        <small>{title}</small>
        {!items.length && <p className="muted">No records yet.</p>}
        {items.map((item, index) => (
          <details key={`${title}-${index}`}>
            <summary>{renderLine(item, kind)}</summary>
            <pre>{JSON.stringify(item, null, 2)}</pre>
          </details>
        ))}
      </div>
    );
  }

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
          <RunStatusPanel runDetail={runDetail} />
          <div className="evidenceStats">
            <Metric label="Model calls" value={String(modelCalls.length)} tone={modelCalls.some((m) => m.status === "failure") ? "bad" : "good"} />
            <Metric label="Validation" value={String(validations.length)} tone={validations.some((v) => /fail|error/i.test(String(v.status ?? v.outcome ?? ""))) ? "bad" : "warn"} />
            <Metric label="Progress" value={String(userProgress.length)} tone={userProgress.length ? "good" : "warn"} />
          </div>
          <EvidenceBlock title="Model route timeline" items={routeTimeline.slice(-8)} kind="route" />
          <EvidenceBlock title="User progress" items={userProgress.slice(-8)} kind="progress" />
          <EvidenceBlock title="Model calls" items={modelCalls.slice(-5)} kind="model" />
          <EvidenceBlock title="Validation" items={validations.slice(-5)} kind="validation" />
          <EvidenceBlock title="Worker results" items={workers.slice(-4)} kind="worker" />
          <EvidenceBlock title="Task evidence" items={evidence.slice(-4)} kind="evidence" />
          {files.length > 0 && (
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

export function Inspector({
  event,
  files,
  preview,
  settings,
  overview,
  selectedRunId,
  runDetail,
  onOpenFile,
  onOpenRun,
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
  const routes = (overview?.modelRoutes?.slice(0, 5) ?? []) as AnyRecord[];
  const inspectorSections = useMemo(() => buildInspectorSections(event), [event]);
  const showRunOverviewFirst = !event && Boolean(runDetail?.ok);

  return (
    <aside className="inspector">
      <section className="opsIntro">
        <p className="eyebrow">Debug / Ops Console</p>
        <h2>Backend observability</h2>
        <p>
          This panel is for developers and dogfooding: inspect evidence, route decisions,
          runtime state, raw artifacts, and local files. Normal users should not need this view.
        </p>
      </section>
      <AiDebugAgentCard runDetail={runDetail} selectedRunId={selectedRunId} />
      {showRunOverviewFirst && (
        <EvidenceExplorer
          runs={(overview?.runs ?? []) as AnyRecord[]}
          selectedRunId={selectedRunId}
          runDetail={runDetail}
          onOpenRun={onOpenRun}
          onOpenFile={onOpenFile}
        />
      )}
      <section>
        <h2>Selected event</h2>
        {!event && <p className="muted">Select an event in the timeline to inspect commands, evidence, artifacts, and diagnostics.</p>}
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
        <h2>Model routes</h2>
        <div className="routeList">
          {routes.length === 0 && <p className="muted">No route telemetry yet.</p>}
          {routes.map((route) => (
            <div className="routeItem" key={String(route.key ?? "")}> 
              <strong>{String(route.provider ?? "")}/{String(route.model ?? "")}</strong>
              <small>{String(route.purpose ?? "")} ? {String(route.tier ?? "")} ? {percent(route.successRate)} success</small>
              <small>{String(route.total ?? 0)} calls ? p95 {formatMs(route.durationP95)}</small>
            </div>
          ))}
        </div>
      </section>
      {!showRunOverviewFirst && (
        <EvidenceExplorer
          runs={(overview?.runs ?? []) as AnyRecord[]}
          selectedRunId={selectedRunId}
          runDetail={runDetail}
          onOpenRun={onOpenRun}
          onOpenFile={onOpenFile}
        />
      )}
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
        <p className="muted">Streaming: {settings?.streamMode ?? "unknown"}</p>
      </section>
    </aside>
  );
}

