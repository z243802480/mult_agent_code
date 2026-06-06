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

type EvidenceSelection = {
  title: string;
  kind: string;
  summary: string;
  item: AnyRecord;
};

function AiDebugAgentCard({ runDetail, selectedRunId }: { runDetail: RunDetailPayload | null; selectedRunId: string | null }) {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
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
          setAnswer(debugAnswerFor(question, runDetail, latestRunId));
          setQuestion("");
        }}
      >
        <textarea
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="Ask an Ops question, e.g. why is this run blocked?"
          rows={2}
        />
        <button type="submit" title="Ask Debug Agent">
          <SendHorizontal size={14} />
        </button>
      </form>
      {answer ? <pre className="debugAgentAnswer">{answer}</pre> : (
        <p className="debugAgentNote">
          Read-only answers use the selected run context{latestRunId ? ` (${latestRunId})` : ""}; they do not execute commands or modify files.
        </p>
      )}
    </section>
  );
}

function debugAnswerFor(question: string, runDetail: RunDetailPayload | null, runId: string): string {
  const lower = question.toLowerCase();
  const progress = runtimeProgressFromDetail(runDetail);
  const loop = asRecord(progress.loop);
  const blocker = firstText(progress.current_blocker, loop.current_blocker, runDetail?.run_loop_summary?.current_blocker, "No blocker is recorded.");
  const next = firstText(progress.next_command, runDetail?.main_action?.next_command, "No next action is recorded.");
  const route = latestRoute(runDetail);
  const routeLine = route
    ? `${firstText(route.purpose, "task")} -> ${firstText(route.selected_tier, route.tier, "unknown")}: ${firstText(route.reason, route.model_selection_reason, "No route reason recorded.")}`
    : "No model route evidence is recorded for this run.";
  if (lower.includes("route") || lower.includes("model")) {
    return [`Run: ${runId || "latest"}`, "Model route:", routeLine].join("\n");
  }
  if (lower.includes("next") || lower.includes("action")) {
    return [`Run: ${runId || "latest"}`, `Recommended next action: ${next}`, `Current blocker: ${blocker}`].join("\n");
  }
  return [`Run: ${runId || "latest"}`, `Current blocker: ${blocker}`, `Recommended next action: ${next}`, `Route: ${routeLine}`].join("\n");
}

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

function buildInspectorSections(
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
          {artifacts.length > 0 && <RefList title="Artifacts" items={artifacts} runId={event.run_id} onOpenFile={onOpenFile} />}
          {evidence.length > 0 && <RefList title="Evidence" items={evidence} runId={event.run_id} onOpenFile={onOpenFile} />}
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

function asRecord(value: unknown): AnyRecord {
  return value && typeof value === "object" && !Array.isArray(value) ? value as AnyRecord : {};
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function runtimeProgressFromDetail(runDetail: RunDetailPayload | null): AnyRecord {
  const direct = asRecord(runDetail?.runtime_progress);
  if (Object.keys(direct).length) return direct;
  const finalSummary = asRecord(runDetail?.final_report_summary);
  const loopSummary = asRecord(runDetail?.run_loop_summary);
  return asRecord(finalSummary.runtime_progress ?? loopSummary.runtime_progress);
}

function latestRoute(runDetail: RunDetailPayload | null): AnyRecord | null {
  const routeArtifact = asRecord(runDetail?.model_route_timeline);
  const finalSummary = asRecord(runDetail?.final_report_summary);
  const timeline = (
    Array.isArray(routeArtifact.timeline)
      ? routeArtifact.timeline
      : Array.isArray(routeArtifact.route_timeline)
        ? routeArtifact.route_timeline
        : Array.isArray(finalSummary.model_route_timeline)
          ? finalSummary.model_route_timeline
          : []
  ) as AnyRecord[];
  return timeline.length ? timeline.at(-1) ?? null : null;
}

function metricTone(value: string): string {
  if (/ready|completed|succeeded|pass|healthy/i.test(value)) return "good";
  if (/blocked|failed|missing|error/i.test(value)) return "bad";
  return "warn";
}

function formatUsage(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return "0";
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}k`;
  return String(Math.round(value));
}

function contextSectionLabel(value: string): string {
  const normalized = value.toLowerCase();
  if (normalized.includes("message") || normalized.includes("conversation")) return "Messages";
  if (normalized.includes("tool") || normalized.includes("shell")) return "Tool output";
  if (normalized.includes("skill")) return "Skills";
  if (normalized.includes("system")) return "System";
  if (normalized.includes("prompt") || normalized.includes("instruction")) return "Project rules";
  if (normalized.includes("memory") || normalized.includes("durable")) return "Memory";
  if (normalized.includes("file") || normalized.includes("context")) return "Files";
  return value.replace(/[_-]+/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

function ContextBreakdownPanel({ runDetail }: { runDetail: RunDetailPayload | null }) {
  const cost = asRecord(runDetail?.cost_report);
  const used = Number(cost.latest_context_estimated_tokens ?? cost.max_context_estimated_tokens ?? 0);
  const capacity = Number(cost.context_window_tokens ?? 0);
  const ratio = Number(cost.context_window_ratio ?? (capacity > 0 ? used / capacity : 0));
  const sections = Object.entries(asRecord(cost.latest_context_sections ?? cost.max_context_sections))
    .map(([id, value]) => ({ id, label: contextSectionLabel(id), value: Number(value ?? 0) }))
    .filter((item) => Number.isFinite(item.value) && item.value > 0)
    .sort((a, b) => b.value - a.value);
  if (!used && !capacity && !sections.length) return null;
  const total = sections.reduce((sum, item) => sum + item.value, 0);
  return (
    <div className="evidenceBlock contextBreakdownPanel">
      <small>Context window</small>
      <div className="evidenceStats">
        <Metric label="Usage" value={percent(ratio)} tone={ratio >= 0.9 ? "bad" : ratio >= 0.75 ? "warn" : "good"} />
        <Metric label="Used" value={formatUsage(used || total)} tone="warn" />
        <Metric label="Capacity" value={capacity ? formatUsage(capacity) : "unknown"} tone="warn" />
      </div>
      <div className="contextInspectorRows">
        {sections.slice(0, 8).map((section) => (
          <div key={section.id} className="contextInspectorRow">
            <span>{section.label}</span>
            <strong>{formatUsage(section.value)}</strong>
            <em>{percent(total ? section.value / total : 0)}</em>
          </div>
        ))}
      </div>
    </div>
  );
}

function rollingValidationFromOverview(overview: OverviewPayload | null): AnyRecord {
  const gateStatus = asRecord(overview?.gateStatus);
  return asRecord(overview?.v0_2_rolling_validation ?? gateStatus.v0_2_rolling_validation);
}

function workerCountFromTree(workerTree: AnyRecord): number {
  const direct = Number(workerTree.total_workers);
  if (Number.isFinite(direct)) return direct;
  const roots = asArray(workerTree.roots) as AnyRecord[];
  const countNodes = (items: AnyRecord[]): number =>
    items.reduce((total, item) => total + 1 + countNodes(asArray(item.children) as AnyRecord[]), 0);
  return countNodes(roots);
}

function BackgroundRunPanel({ overview }: { overview: OverviewPayload | null }) {
  const background = asRecord(overview?.background_runs);
  if (!background || background.enabled === false) return null;
  const runningCount = Number(background.running_count ?? 0);
  const totalCount = Number(background.total_count ?? 0);
  const badgeStatus = firstText(String(background.badge_status ?? ""), "idle");
  const summary = firstText(String(background.badge_summary ?? ""), "No background run status recorded.");
  const latest = asRecord(background.latest);

  return (
    <div className="evidenceBlock backgroundRunPanel">
      <small>Local background runs</small>
      <div className="workerSchedulingBadge" data-fake-path="false">
        {runningCount > 0 ? `local subprocess · ${runningCount} running` : "local subprocess · idle"}
      </div>
      <div className="evidenceStats">
        <Metric label="Badge" value={badgeStatus} tone={runningCount ? "warn" : "good"} />
        <Metric label="Running" value={`${runningCount}/${totalCount}`} tone={runningCount ? "warn" : "good"} />
        <Metric label="Cloud VM" value="defer" tone="good" />
      </div>
      <div className="keyValueList">
        <div><small>Summary</small><pre>{summary}</pre></div>
        {latest && Object.keys(latest).length > 0 && (
          <div><small>Latest</small><pre>{`${String(latest.background_run_id ?? "n/a")} · ${String(latest.status ?? "unknown")}\n${String(latest.goal ?? "")}`}</pre></div>
        )}
      </div>
    </div>
  );
}

function LongHorizonPanel({ overview }: { overview: OverviewPayload | null }) {
  const longHorizon = asRecord(overview?.long_horizon);
  if (!longHorizon || !Object.keys(longHorizon).length) return null;
  const northStar = asRecord(longHorizon.north_star);
  const handoffCompact = asRecord(longHorizon.handoff_compact);
  const status = firstText(String(longHorizon.status ?? ""), "unknown");
  const summary = firstText(String(longHorizon.summary ?? ""), "No long-horizon summary recorded.");
  const configured = longHorizon.north_star_configured === true;
  const ready = longHorizon.ready_for_implementation === true;

  return (
    <div className="evidenceBlock longHorizonPanel">
      <small>Long horizon (Inspector)</small>
      <div className="evidenceStats">
        <Metric label="Status" value={status} tone={configured ? "good" : ready ? "warn" : "warn"} />
        <Metric
          label="Milestones"
          value={configured ? `${String(northStar.completed_milestones ?? 0)}/${String(northStar.milestone_count ?? 0)}` : "n/a"}
          tone={configured ? "good" : "warn"}
        />
        <Metric label="Ready" value={ready ? "yes" : "no"} tone={ready ? "good" : "warn"} />
      </div>
      <div className="keyValueList">
        <div><small>Summary</small><pre>{summary}</pre></div>
        {configured && (
          <>
            <div><small>Title</small><pre>{String(northStar.title ?? "")}</pre></div>
            <div><small>Active milestone</small><pre>{String(northStar.active_milestone ?? "none")}</pre></div>
            <div><small>Statement</small><pre>{String(northStar.statement ?? "")}</pre></div>
          </>
        )}
        {handoffCompact.available === true && (
          <>
            <div><small>Handoff compact</small><pre>{String(handoffCompact.narrative ?? "")}</pre></div>
            {handoffCompact.recommended_next_command ? (
              <div><small>Continue</small><pre>{String(handoffCompact.recommended_next_command)}</pre></div>
            ) : null}
          </>
        )}
      </div>
    </div>
  );
}

function V02ReadinessPanel({ overview, runDetail }: { overview: OverviewPayload | null; runDetail: RunDetailPayload | null }) {
  const rolling = rollingValidationFromOverview(overview);
  const coverage = asRecord(rolling.coverage);
  const missing = asArray(rolling.missing_evidence_categories).map(String);
  const rollingStatus = firstText(String(rolling.status ?? ""), "unknown");
  const sampleCount = Number(rolling.sample_count ?? 0);
  const agentLoopSummary = asRecord(runDetail?.agent_loop_run_summary);
  const legacyLoopSummary = asRecord(runDetail?.run_loop_summary);
  const workerTree = asRecord(runDetail?.worker_tree);
  const agentRunGraph = asRecord(workerTree.agent_run_graph ?? runDetail?.agent_run_graph);
  const workerTotal = workerCountFromTree(workerTree);
  const loopExit = firstText(String(agentLoopSummary.exit_reason ?? ""), String(legacyLoopSummary.stop_reason ?? ""), "unknown");
  const loopRounds = firstText(
    `${String(agentLoopSummary.rounds_completed ?? "n/a")}/${String(agentLoopSummary.max_rounds ?? "n/a")}`,
    String(legacyLoopSummary.iteration_count ?? "")
  );
  const nextAction = firstText(
    String(asArray(rolling.next_actions)[0] ?? ""),
    String(agentLoopSummary.recommended_command ?? ""),
    String(legacyLoopSummary.recommended_next_command ?? ""),
    "No action recorded"
  );
  const coverageLine = ["route", "context", "capability", "loop", "worker"]
    .map((key) => `${key}=${coverage[key] === true ? "yes" : "no"}`)
    .join(", ");

  return (
    <div className="evidenceBlock v02ReadinessPanel">
      <small>v0.2 Readiness</small>
      <div className="evidenceStats">
        <Metric label="Bundle" value={`${rollingStatus} (${sampleCount})`} tone={metricTone(rollingStatus)} />
        <Metric label="Loop exit" value={loopExit} tone={metricTone(String(agentLoopSummary.status ?? legacyLoopSummary.workflow_state ?? loopExit))} />
        <Metric label="Workers" value={`${String(workerTree.successful_workers ?? 0)}/${String(workerTotal)}`} tone={Number(workerTree.failed_workers ?? 0) ? "bad" : workerTotal ? "good" : "warn"} />
      </div>
      <div className="keyValueList">
        <div><small>Evidence coverage</small><pre>{coverageLine || "No v0.2 rolling validation bundle found."}</pre></div>
        <div><small>Missing evidence</small><pre>{missing.length ? missing.join(", ") : "none"}</pre></div>
        <div><small>Loop summary</small><pre>{`exit=${loopExit}
rounds=${loopRounds}
latest_action=${String(agentLoopSummary.latest_action ?? "n/a")}`}</pre></div>
        <div><small>Worker tree</small><pre>{`roots=${asArray(workerTree.roots).length}
orphans=${asArray(workerTree.orphan_workers).length}
graph=${String(agentRunGraph.status ?? "unknown")}
parallel_batches=${String(workerTree.parallel_batches ?? 0)}`}</pre></div>
        <div><small>Next action</small><pre>{nextAction}</pre></div>
      </div>
    </div>
  );
}

function flattenWorkerTree(workerTree: AnyRecord): AnyRecord[] {
  const result: AnyRecord[] = [];
  const visit = (node: AnyRecord, depth: number) => {
    result.push({ ...node, depth });
    for (const child of asArray(node.children) as AnyRecord[]) visit(child, depth + 1);
  };
  for (const root of asArray(workerTree.roots) as AnyRecord[]) visit(root, 0);
  for (const orphan of asArray(workerTree.orphan_workers) as AnyRecord[]) visit(orphan, 0);
  return result;
}

function EvidenceDetailPanel({ selection }: { selection: EvidenceSelection | null }) {
  return (
    <div className="evidenceDetailPanel">
      <small>Evidence detail</small>
      {!selection ? (
        <p className="muted">Select a worker, progress entry, route, validation, or run file to inspect its evidence.</p>
      ) : (
        <>
          <div className="evidenceDetailHeader">
            <strong>{selection.title}</strong>
            <span>{selection.kind}</span>
          </div>
          <p>{selection.summary}</p>
          <pre>{JSON.stringify(selection.item, null, 2)}</pre>
        </>
      )}
    </div>
  );
}

function PromotionPreviewPanel({
  runDetail,
  selectedKey,
  onSelectEvidence,
}: {
  runDetail: RunDetailPayload;
  selectedKey: string;
  onSelectEvidence: (selection: EvidenceSelection) => void;
}) {
  const preview = asRecord(runDetail.promotion_preview);
  const items = asArray(preview.items) as AnyRecord[];
  if (!items.length && !preview.export_count) return null;
  const mergeStatus = String(preview.merge_preview_status ?? "none");
  return (
    <div className="evidenceBlock promotionPreviewPanel">
      <small>Candidate merge preview</small>
      <div className="evidenceStats">
        <Metric label="Exports" value={String(preview.export_count ?? 0)} tone={Number(preview.export_count ?? 0) ? "good" : "warn"} />
        <Metric label="Preview" value={mergeStatus === "ready" ? "ready" : mergeStatus === "needs_review" ? "review" : "—"} tone={mergeStatus === "ready" ? "good" : mergeStatus === "needs_review" ? "bad" : "warn"} />
        <Metric label="Pending" value={String(preview.pending_promotions ?? 0)} tone={Number(preview.pending_promotions ?? 0) ? "warn" : "good"} />
      </div>
      {preview.merge_preview_summary && <p className="promotionPreviewSummary">{String(preview.merge_preview_summary)}</p>}
      <div className="promotionPreviewList">
        {items.slice(0, 8).map((item, index) => {
          const kind = String(item.kind ?? "item");
          const id = String(item.id ?? `item-${index + 1}`);
          const key = `${kind}:${id}`;
          const files = asArray(item.files).map(String).join(", ");
          return (
            <button
              key={key}
              className={`promotionPreviewItem ${selectedKey === key ? "active" : ""}`}
              onClick={() => onSelectEvidence({
                title: id,
                kind,
                summary: files || String(item.summary ?? item.status ?? kind),
                item,
              })}
            >
              <span className="promotionPreviewItemHead">
                <span>{kind.replace(/_/g, " ")}</span>
                <Status status={(item.ok === false || item.status === "blocked" ? "blocked" : item.status === "ready" ? "completed" : "running") as StudioEvent["status"]} />
              </span>
              <pre>{[
                item.task_id ? `task=${String(item.task_id)}` : "",
                files ? `files=${files}` : "",
                item.execution_profile_id ? `profile=${String(item.execution_profile_id)}` : "",
              ].filter(Boolean).join("\n")}</pre>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function WorkerTopologyPanel({
  runDetail,
  selectedKey,
  onSelectEvidence,
}: {
  runDetail: RunDetailPayload;
  selectedKey: string;
  onSelectEvidence: (selection: EvidenceSelection) => void;
}) {
  const workerTree = asRecord(runDetail.worker_tree);
  const workers = flattenWorkerTree(workerTree);
  if (!workers.length) return null;
  return (
    <div className="evidenceBlock workerTopologyPanel">
      <small>Worker topology</small>
      <div className="workerTopologyStats">
        <Metric label="Roots" value={String(asArray(workerTree.roots).length)} tone="warn" />
        <Metric label="Parallel" value={String(workerTree.parallel_batches ?? 0)} tone={Number(workerTree.parallel_batches ?? 0) ? "good" : "warn"} />
        <Metric label="Failed" value={String(workerTree.failed_workers ?? 0)} tone={Number(workerTree.failed_workers ?? 0) ? "bad" : "good"} />
      </div>
      <div className="workerTopologyList">
        {workers.slice(0, 12).map((worker, index) => {
          const workerId = firstText(worker.worker_invocation_id, worker.worker_id, worker.agent_id, `worker-${index + 1}`);
          const status = String(worker.status ?? worker.outcome ?? "unknown");
          const profile = firstText(worker.execution_profile_id, worker.runtime_profile_id, worker.profile_id, worker.worker_kind, "profile unknown");
          const safety = firstText(worker.parallel_safety, worker.sandbox_profile_id, worker.spawn_kind, "safety unknown");
          const workspaceRef = firstText(worker.candidate_workspace, worker.workspace, worker.workspace_path, "");
          const key = `worker:${workerId}`;
          return (
            <button
              key={`${workerId}-${index}`}
              className={`workerTopologyItem ${selectedKey === key ? "active" : ""}`}
              onClick={() => onSelectEvidence({
                title: workerId,
                kind: "worker",
                summary: `${status} · ${String(worker.task_id ?? "no task")}`,
                item: worker,
              })}
            >
              <span className="workerTopologySummary">
                <span style={{ paddingLeft: `${Math.min(Number(worker.depth ?? 0), 4) * 10}px` }}>{workerId}</span>
                <Status status={status as StudioEvent["status"]} />
              </span>
              <pre>{[
                `task=${String(worker.task_id ?? "n/a")}`,
                `parent=${String(worker.parent_worker_invocation_id ?? worker.parent_task_id ?? "root")}`,
                `profile=${profile}`,
                `safety=${safety}`,
                workspaceRef ? `workspace=${workspaceRef}` : "",
              ].filter(Boolean).join("\n")}</pre>
            </button>
          );
        })}
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
  const agentLoopSummary = (runDetail.agent_loop_run_summary ?? {}) as AnyRecord;
  const mainAction = asRecord(runDetail.main_action);
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
  const nextCommand = firstText(String(mainAction.next_command ?? ""), String(finalSummary.recommended_next_command ?? ""), String(agentLoopSummary.recommended_command ?? ""), String(runLoopSummary.recommended_next_command ?? ""), "none");
  const nextLabel = firstText(String(mainAction.label ?? ""), nextCommand);
  const commandDisplay = nextCommand === "none"
    ? "No action needed"
    : /^asteria\b/i.test(nextCommand) ? nextCommand : `asteria ${nextCommand}`;
  const blocker = firstText(String(finalSummary.current_blocker ?? ""), String(runLoopSummary.current_blocker ?? ""), "none");
  const loopExit = firstText(String(agentLoopSummary.exit_reason ?? ""), String(runLoopSummary.stop_reason ?? ""), "n/a");

  return (
    <div className="evidenceBlock runStatusPanel">
      <small>Long-task loop</small>
      <div className="evidenceStats">
        <Metric label="State" value={workflowState} tone={/blocked|fail|need/i.test(workflowState) ? "bad" : "good"} />
        <Metric label="Next" value={nextLabel} tone={nextCommand === "none" ? "good" : "warn"} />
        <Metric label="Policy" value={String(goalPolicy.category ?? "none")} tone={String(goalPolicy.category ?? "none") === "none" ? "good" : "warn"} />
      </div>
      <div className="keyValueList">
        <div><small>Current status</small><pre>{`${String(run.status ?? "unknown")} / ${String(run.current_phase ?? "unknown")}`}</pre></div>
        <div><small>Current blocker</small><pre>{blocker}</pre></div>
        <div><small>Recommended command</small><pre>{commandDisplay}</pre></div>
        <div><small>Main action source</small><pre>{`kind=${String(mainAction.kind ?? "unknown")}
status=${String(mainAction.status ?? "unknown")}
requires_permission=${String(mainAction.requires_permission ?? "unknown")}
source=${String(mainAction.source ?? "unknown")}
evidence=${asArray(mainAction.evidence_refs).join(", ") || "none"}`}</pre></div>
        <div><small>Goal policy</small><pre>{`${String(goalPolicy.category ?? "none")} -> ${String(goalPolicy.recommended_command ?? goalPolicy.recommended_next_command ?? goalPolicy.recommended_action ?? nextCommand)}
${String(goalPolicy.reason ?? "No policy reason recorded.")}`}</pre></div>
        <div><small>Run loop summary</small><pre>{`exit=${loopExit}
rounds=${String(agentLoopSummary.rounds_completed ?? runLoopSummary.iteration_count ?? "n/a")}/${String(agentLoopSummary.max_rounds ?? "n/a")}`}</pre></div>
        <div><small>Model route rationale</small><pre>{`${String(latestRoute.purpose ?? "unknown")} -> ${String(latestRoute.selected_tier ?? "unknown")}
reason=${String(latestRoute.reason ?? "No route reason recorded.")}`}</pre></div>
      </div>
    </div>
  );
}

function progressToStudioEvent(item: AnyRecord, runId: unknown): StudioEvent {
  const status = String(item.status ?? "completed") as StudioEvent["status"];
  const phase = String(item.phase ?? item.channel ?? "execute");
  return {
    event_id: String(item.event_id ?? `runtime-progress-${Date.now()}`),
    session_id: "runtime-progress",
    type: "assistant_delta",
    status,
    title: firstText(String(item.title ?? ""), String(item.event_type ?? ""), "Runtime progress"),
    summary: firstText(String(item.summary ?? ""), phase),
    content_delta: String(item.content_delta ?? item.summary ?? ""),
    evidence_refs: asArray(item.evidence_refs).map(String),
    artifact_refs: asArray(item.artifact_refs).map(String),
    runtime_channel: String(item.channel ?? "progress"),
    runtime_event_type: String(item.event_type ?? "message"),
    source: "runtime_user_progress",
    run_id: String(runId ?? item.run_id ?? ""),
    phase,
    display_level: "main",
    created_at: String(item.created_at ?? new Date().toISOString()),
  };
}

function EvidenceExplorer({
  overview,
  runs,
  selectedRunId,
  runDetail,
  onOpenRun,
  onOpenFile,
  onSelectRunEvent,
}: {
  overview: OverviewPayload | null;
  runs: AnyRecord[];
  selectedRunId: string | null;
  runDetail: RunDetailPayload | null;
  onOpenRun: (runId: string) => Promise<void>;
  onOpenFile: (path: string) => Promise<void>;
  onSelectRunEvent: (event: StudioEvent) => void;
}) {
  const [selectedEvidence, setSelectedEvidence] = useState<EvidenceSelection | null>(null);
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
  const selectedKey = selectedEvidence ? `${selectedEvidence.kind}:${selectedEvidence.title}` : "";

  function selectEvidence(selection: EvidenceSelection) {
    setSelectedEvidence(selection);
  }

  function selectProgress(item: AnyRecord, index: number) {
    const title = firstText(String(item.title ?? ""), String(item.event_type ?? ""), `progress-${index + 1}`);
    selectEvidence({
      title,
      kind: "progress",
      summary: firstText(String(item.summary ?? ""), String(item.phase ?? ""), "No summary recorded."),
      item,
    });
    onSelectRunEvent(progressToStudioEvent(item, runDetail?.run_id));
  }

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
        <div className="evidenceSelectableList">
          {items.map((item, index) => {
            const line = renderLine(item, kind);
            const key = `${kind}:${line}`;
            return (
              <button
                key={`${title}-${index}`}
                className={selectedKey === key ? "active" : ""}
                onClick={() => {
                  if (kind === "progress") {
                    selectProgress(item, index);
                    return;
                  }
                  selectEvidence({ title: line, kind, summary: firstText(String(item.summary ?? ""), String(item.reason ?? ""), line), item });
                }}
              >
                <span>{line}</span>
              </button>
            );
          })}
        </div>
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
          <V02ReadinessPanel overview={overview} runDetail={runDetail} />
          <RunStatusPanel runDetail={runDetail} />
          <ContextBreakdownPanel runDetail={runDetail} />
          <PromotionPreviewPanel
            runDetail={runDetail}
            selectedKey={selectedKey}
            onSelectEvidence={selectEvidence}
          />
          <WorkerTopologyPanel
            runDetail={runDetail}
            selectedKey={selectedKey}
            onSelectEvidence={selectEvidence}
          />
          <EvidenceDetailPanel selection={selectedEvidence} />
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
                <button
                  key={file.path}
                  onClick={() => {
                    selectEvidence({
                      title: file.path.split("/").pop() || file.path,
                      kind: "run-file",
                      summary: file.path,
                      item: file as unknown as AnyRecord,
                    });
                    void onOpenFile(file.path);
                  }}
                >
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
  onSelectRunEvent,
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
  onSelectRunEvent: (event: StudioEvent) => void;
}) {
  const eventFiles = useMemo(() => files.slice(0, 12), [files]);
  const routes = (overview?.modelRoutes?.slice(0, 5) ?? []) as AnyRecord[];
  const inspectorSections = useMemo(() => buildInspectorSections(event, onOpenFile), [event, onOpenFile]);
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
      <BackgroundRunPanel overview={overview} />
      <LongHorizonPanel overview={overview} />
      {showRunOverviewFirst && (
        <EvidenceExplorer
          runs={(overview?.runs ?? []) as AnyRecord[]}
          overview={overview}
          selectedRunId={selectedRunId}
          runDetail={runDetail}
          onOpenRun={onOpenRun}
          onOpenFile={onOpenFile}
          onSelectRunEvent={onSelectRunEvent}
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
          overview={overview}
          selectedRunId={selectedRunId}
          runDetail={runDetail}
          onOpenRun={onOpenRun}
          onOpenFile={onOpenFile}
          onSelectRunEvent={onSelectRunEvent}
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

