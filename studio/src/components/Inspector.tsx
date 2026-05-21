import React, { useMemo, useState, useEffect } from "react";
import { ArrowUpRight, FileText } from "lucide-react";
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
      id: "shell",
      title: "Shell",
      count: shellItems.length,
      empty: "此事件没有 shell 命令或工具输出。",
      content: <KeyValueList items={shellItems} />,
    },
    {
      id: "diff",
      title: "Diff",
      count: fileChanges.length,
      empty: "此事件没有文件变化。",
      content: (
        <RecordList
          items={fileChanges}
          render={(item) => firstText(`${String(item.operation ?? item.event_type ?? "change")} ${String(item.path ?? "")}`)}
        />
      ),
    },
    {
      id: "artifact",
      title: "产物",
      count: artifacts.length + evidence.length,
      empty: "此事件没有产物或证据引用。",
      content: (
        <>
          {artifacts.length > 0 && <RefList title="Artifacts" items={artifacts} />}
          {evidence.length > 0 && <RefList title="Evidence" items={evidence} />}
        </>
      ),
    },
    {
      id: "diagnostic",
      title: "诊断",
      count: diagnostics.length,
      empty: "此事件没有诊断遥测。",
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
    return JSON.stringify(item).slice(0, 80);
  }

  function EvidenceBlock({ title, items, kind }: { title: string; items: AnyRecord[]; kind: string }) {
    return (
      <div className="evidenceBlock">
        <small>{title}</small>
        {!items.length && <p className="muted">暂无记录。</p>}
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
      <h2>证据浏览器</h2>
      <div className="runPicker">
        {runs.length === 0 && <p className="muted">暂无本地 run 证据。</p>}
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
            <Metric label="模型" value={String(modelCalls.length)} tone={modelCalls.some((m) => m.status === "failure") ? "bad" : "good"} />
            <Metric label="验证" value={String(validations.length)} tone={validations.some((v) => /fail|error/i.test(String(v.status ?? v.outcome ?? ""))) ? "bad" : "warn"} />
            <Metric label="进展" value={String(userProgress.length)} tone={userProgress.length ? "good" : "warn"} />
          </div>
          <EvidenceBlock title="用户进展" items={userProgress.slice(-8)} kind="progress" />
          <EvidenceBlock title="模型调用" items={modelCalls.slice(-5)} kind="model" />
          <EvidenceBlock title="验证" items={validations.slice(-5)} kind="validation" />
          <EvidenceBlock title="Worker 结果" items={workers.slice(-4)} kind="worker" />
          <EvidenceBlock title="任务证据" items={evidence.slice(-4)} kind="evidence" />
          {files.length > 0 && (
            <div className="runFiles">
              <small>Run 文件</small>
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

  return (
    <aside className="inspector">
      <section>
        <h2>选中事件</h2>
        {!event && <p className="muted">在时间线上选中一个事件，查看命令、证据、产物和遥测。</p>}
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
        <h2>模型路由</h2>
        <div className="routeList">
          {routes.length === 0 && <p className="muted">暂无路由遥测。</p>}
          {routes.map((route) => (
            <div className="routeItem" key={String(route.key ?? "")}>
              <strong>{String(route.provider ?? "")}/{String(route.model ?? "")}</strong>
              <small>{String(route.purpose ?? "")} · {String(route.tier ?? "")} · {percent(route.successRate)} 成功</small>
              <small>{String(route.total ?? 0)} 次调用 · p95 {formatMs(route.durationP95)}</small>
            </div>
          ))}
        </div>
      </section>
      <EvidenceExplorer
        runs={(overview?.runs ?? []) as AnyRecord[]}
        selectedRunId={selectedRunId}
        runDetail={runDetail}
        onOpenRun={onOpenRun}
        onOpenFile={onOpenFile}
      />
      <section>
        <h2>文件</h2>
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
            <strong>{preview.path ?? "预览"}</strong>
            {preview.ok ? <pre>{(preview.content ?? "").slice(0, 5000)}</pre> : <p>{preview.error}</p>}
          </div>
        )}
      </section>
      <section>
        <h2>Runtime</h2>
        <p className="muted">模式: {settings?.workMode ?? "unknown"}</p>
        <p className="muted">权限: {settings?.permissionMode ?? "unknown"}</p>
        <p className="muted">Shell: {settings?.shell ?? "unknown"}</p>
        <p className="muted">流式: {settings?.streamMode ?? "unknown"}</p>
      </section>
    </aside>
  );
}
