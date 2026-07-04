import React, { useEffect, useMemo, useState } from "react";
import { ArrowUpRight, FileText } from "lucide-react";
import type { AnyRecord, StudioEvent } from "../../types";
import { Metric, formatMs } from "../../components/Shared";
import { CopyablePre } from "../../components/CopyablePre";
import { firstText } from "../../narrative";
import { asArray, asRecord, formatUsage } from "./inspectorUtils";

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
  const text = String(value || "").trim().replace(/\\/g, "/");
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

function RecordList({ items, render }: { items: AnyRecord[]; render: (item: AnyRecord) => string }) {
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
  onOpenFile?: (path: string) => Promise<void>
): InspectorSection[] {
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
    ...(event.source
      ? [{ source: event.source, channel: event.runtime_channel, event_type: event.runtime_event_type, run_id: event.run_id }]
      : []),
    ...(event.content_delta && !event.type.startsWith("tool_") ? [{ content: event.content_delta }] : []),
  ].filter(Boolean);
  // Per-step telemetry gets its own scannable metric view (latency + token breakdown) instead of
  // being dumped as raw JSON inside Diagnostics.
  const telemetry = asRecord(event.telemetry);

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
          {artifacts.length > 0 && <RefList title="Artifacts" items={artifacts} runId={event.run_id} onOpenFile={onOpenFile} />}
          {evidence.length > 0 && <RefList title="Evidence" items={evidence} runId={event.run_id} onOpenFile={onOpenFile} />}
        </>
      ),
    },
    {
      id: "telemetry",
      title: "Telemetry",
      count: Object.keys(telemetry).length,
      empty: "This event has no token or latency telemetry.",
      content: <TelemetryView telemetry={telemetry} />,
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
    latency != null && { label: "Latency", value: formatMs(latency) },
    input != null && { label: "Input tokens", value: formatUsage(input) },
    output != null && { label: "Output tokens", value: formatUsage(output) },
    total != null && { label: "Total tokens", value: formatUsage(total) },
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
        <summary>Raw telemetry</summary>
        <CopyablePre text={JSON.stringify(telemetry, null, 2)} />
      </details>
    </div>
  );
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
        <div><small>Raw metadata</small><CopyablePre text={JSON.stringify(items, null, 2)} /></div>
      </div>
    </div>
  );
}

export function InspectorTabs({ sections }: { sections: InspectorSection[] }) {
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

