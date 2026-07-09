import React, { useEffect, useState } from "react";
import { FileText } from "lucide-react";
import type { AnyRecord, StudioEvent } from "../../types";
import { Metric, formatMs } from "../../components/Shared";
import { CopyablePre } from "../../components/CopyablePre";
import { firstText } from "../../narrative";
import { asRecord, formatUsage } from "./inspectorUtils";

type InspectorSection = {
  id: string;
  title: string;
  count: number;
  empty: string;
  content: React.ReactNode;
};

function RefList({
  title,
  items,
  runId,
  onOpenFile,
}: {
  title: string;
  items: string[];
  runId?: string;
  onOpenFile?: (path: string) => Promise<void>;
}) {
  return (
    <div className="refList">
      <small>{title}</small>
      {items.map((item) => {
        const path = evidenceRefToPath(item, runId);
        if (path && onOpenFile) {
          return (
            <button key={item} type="button" onClick={() => void onOpenFile(path)}>
              <FileText size={12} />
              <span>{item}</span>
            </button>
          );
        }
        return <code key={item}>{item}</code>;
      })}
    </div>
  );
}

function evidenceRefToPath(value: string, runId?: string): string {
  const text = String(value || "")
    .trim()
    .replace(/\\/g, "/");
  if (!text) return "";
  if (text.startsWith(".asteria/runs/")) return text;
  if (runId && /^[A-Za-z0-9_.-]+\.(json|jsonl|md|txt|log)$/i.test(text)) {
    return `.asteria/runs/${runId}/${text}`;
  }
  return "";
}

function KeyValueList({ items }: { items: { label: string; value: string }[] }) {
  return (
    <div className="keyValueList">
      {items.map((item) => (
        <div key={item.label}>
          <small>{item.label}</small>
          <CopyablePre text={item.value} />
        </div>
      ))}
    </div>
  );
}

function RecordList({
  items,
  render,
}: {
  items: AnyRecord[];
  render: (item: AnyRecord) => string;
}) {
  return (
    <div className="recordList">
      {items.map((item, index) => (
        <details key={`${render(item)}-${index}`}>
          <summary>{render(item)}</summary>
          <CopyablePre text={JSON.stringify(item, null, 2)} />
        </details>
      ))}
    </div>
  );
}

export function buildInspectorSections(
  event: StudioEvent | null,
  onOpenFile?: (path: string) => Promise<void>,
): InspectorSection[] {
  if (!event) return [];
  const shellItems = [
    ...(event.command?.length ? [{ label: "命令", value: event.command.join(" ") }] : []),
    ...(event.content_delta && (event.type.startsWith("tool_") || event.runtime_channel === "tool")
      ? [{ label: "输出", value: event.content_delta }]
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
    ...(event.source
      ? [
          {
            source: event.source,
            channel: event.runtime_channel,
            event_type: event.runtime_event_type,
            run_id: event.run_id,
          },
        ]
      : []),
    ...(event.content_delta && !event.type.startsWith("tool_")
      ? [{ content: event.content_delta }]
      : []),
  ].filter(Boolean);
  // Per-step telemetry gets its own scannable metric view (latency + token breakdown) instead of
  // being dumped as raw JSON inside Diagnostics.
  const telemetry = asRecord(event.telemetry);

  return [
    {
      id: "intent",
      title: "意图",
      count: intentDiagnostics.length,
      empty: "该事件没有意图路由元数据。",
      content: <IntentAuditView items={intentDiagnostics} />,
    },
    {
      id: "shell",
      title: "Shell",
      count: shellItems.length,
      empty: "该事件没有 Shell 命令或工具输出。",
      content: <KeyValueList items={shellItems} />,
    },
    {
      id: "diff",
      title: "改动",
      count: fileChanges.length,
      empty: "该事件没有文件改动。",
      content: (
        <RecordList
          items={fileChanges}
          render={(item) =>
            firstText(
              `${String(item.operation ?? item.event_type ?? "change")} ${String(item.path ?? "")}`,
            )
          }
        />
      ),
    },
    {
      id: "artifact",
      title: "产物",
      count: artifacts.length + evidence.length,
      empty: "该事件没有产物或证据引用。",
      content: (
        <>
          {artifacts.length > 0 && (
            <RefList title="产物" items={artifacts} runId={event.run_id} onOpenFile={onOpenFile} />
          )}
          {evidence.length > 0 && (
            <RefList title="证据" items={evidence} runId={event.run_id} onOpenFile={onOpenFile} />
          )}
        </>
      ),
    },
    {
      id: "telemetry",
      title: "遥测",
      count: Object.keys(telemetry).length,
      empty: "该事件没有 token 或延迟遥测数据。",
      content: <TelemetryView telemetry={telemetry} />,
    },
    {
      id: "diagnostic",
      title: "诊断",
      count: diagnostics.length,
      empty: "该事件没有诊断信息。",
      content: (
        <RecordList
          items={diagnostics}
          render={(item) =>
            firstText(
              item.provider ? `${String(item.provider)}/${String(item.model ?? "unknown")}` : "",
              item.source
                ? `${String(item.source)} ${String(item.channel ?? "")}/${String(item.event_type ?? "")}`
                : "",
              String(item.content ?? ""),
              JSON.stringify(item),
            )
          }
        />
      ),
    },
  ];
}

function TelemetryView({ telemetry }: { telemetry: AnyRecord }) {
  // Token/latency field names vary by provider path; probe the known aliases and show whatever the
  // event actually recorded (no fabricated zeros). Raw payload stays available below for the rest.
  const num = (keys: string[]): number | null => {
    for (const key of keys) {
      const value = telemetry[key];
      if (typeof value === "number" && Number.isFinite(value)) return value;
    }
    return null;
  };
  const latency = num(["duration_ms", "latency_ms", "elapsed_ms"]);
  const input = num(["input_tokens", "estimated_input_tokens", "prompt_tokens"]);
  const output = num(["output_tokens", "estimated_output_tokens", "completion_tokens"]);
  const total = num(["total_tokens", "token_count", "num_tokens", "n_tokens"]);
  const metrics = [
    latency != null && { label: "延迟", value: formatMs(latency) },
    input != null && { label: "输入 token", value: formatUsage(input) },
    output != null && { label: "输出 token", value: formatUsage(output) },
    total != null && { label: "总 token", value: formatUsage(total) },
  ].filter(Boolean) as { label: string; value: string }[];
  return (
    <div className="telemetryView">
      {metrics.length > 0 && (
        <div className="evidenceStats">
          {metrics.map((metric) => (
            <Metric key={metric.label} label={metric.label} value={metric.value} tone="good" />
          ))}
        </div>
      )}
      <details>
        <summary>原始遥测</summary>
        <CopyablePre text={JSON.stringify(telemetry, null, 2)} />
      </details>
    </div>
  );
}

function IntentAuditView({ items }: { items: AnyRecord[] }) {
  const audit = (items.find((item) => item.intent_kind || item.route || item.permission_effect) ??
    {}) as AnyRecord;
  if (!items.length) return null;
  return (
    <div className="intentAudit">
      <div className="intentAuditGrid">
        <Metric
          label="路由"
          value={String(audit.route ?? audit.selected_mode ?? "unknown")}
          tone="good"
        />
        <Metric label="意图" value={String(audit.intent_kind ?? "unknown")} tone="warn" />
        <Metric
          label="权限"
          value={String(audit.permission_effect ?? "unknown")}
          tone={String(audit.permission_effect ?? "").includes("execute") ? "warn" : "good"}
        />
      </div>
      <div className="keyValueList">
        <div>
          <small>原因</small>
          <pre>{String(audit.reason ?? "未记录路由原因。")}</pre>
        </div>
        <div>
          <small>Prompt 增强</small>
          <pre>{String(audit.prompt_enrichment ?? "none")}</pre>
        </div>
        <div>
          <small>原始元数据</small>
          <CopyablePre text={JSON.stringify(items, null, 2)} />
        </div>
      </div>
    </div>
  );
}

export function InspectorTabs({ sections }: { sections: InspectorSection[] }) {
  const [active, setActive] = useState(
    sections.find((section) => section.count > 0)?.id ?? sections[0]?.id ?? "shell",
  );
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
          <button
            className={section.id === active ? "active" : ""}
            key={section.id}
            onClick={() => setActive(section.id)}
          >
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
