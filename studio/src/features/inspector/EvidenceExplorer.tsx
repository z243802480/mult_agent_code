import React, { useState } from "react";
import { FileText } from "lucide-react";
import type { AnyRecord, OverviewPayload, RunDetailPayload, StudioEvent } from "../../types";
import { Metric, formatMs, percent, Status } from "../../components/Shared";
import { WorkflowMonitorPanel } from "../../components/WorkflowMonitorPanel";
import { firstText } from "../../narrative";
import { asArray, asRecord, contextSectionLabel, formatUsage, latestRoute, metricTone, rollingValidationFromOverview, runtimeProgressFromDetail, workerCountFromTree } from "./inspectorUtils";

type EvidenceSelection = {
  title: string;
  kind: string;
  summary: string;
  item: AnyRecord;
};

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

export function BackgroundRunPanel({ overview }: { overview: OverviewPayload | null }) {
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

export function LongHorizonPanel({ overview }: { overview: OverviewPayload | null }) {
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
      {preview.merge_preview_summary ? (
        <p className="promotionPreviewSummary">{String(preview.merge_preview_summary)}</p>
      ) : null}
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

function RunStatusPanel({ runDetail }: { runDetail: RunDetailPayload }) {
  const run = (runDetail.run ?? {}) as AnyRecord;
  const finalSummary = (runDetail.final_report_summary ?? {}) as AnyRecord;
  const runLoopSummary = (runDetail.run_loop_summary ?? {}) as AnyRecord;
  const agentLoopSummary = (runDetail.agent_loop_run_summary ?? {}) as AnyRecord;
  const mainAction = asRecord(runDetail.main_action);
  const routeArtifact = (runDetail.model_route_timeline ?? {}) as AnyRecord;
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
  // loop_quality_guard SLO (observe_then_warn): an auditable no-progress signal, NOT a hard stop
  // (ADR-0010). Surface it honestly — real values when recorded, "not recorded" for older runs.
  const loopQuality = asRecord(agentLoopSummary.loop_quality);
  const hasLoopQuality = Object.keys(loopQuality).length > 0;
  const loopWarn = Boolean(loopQuality.warn);
  const loopSeverity = firstText(String(loopQuality.severity ?? ""), loopWarn ? "warn" : "ok");
  const loopHealth = hasLoopQuality ? (loopWarn ? `warn (${loopSeverity})` : "ok") : "not recorded";

  return (
    <div className="evidenceBlock runStatusPanel">
      <small>Long-task loop</small>
      <div className="evidenceStats">
        <Metric label="State" value={workflowState} tone={/blocked|fail|need/i.test(workflowState) ? "bad" : "good"} />
        <Metric label="Next" value={nextLabel} tone={nextCommand === "none" ? "good" : "warn"} />
        <Metric label="Loop exit" value={loopExit} tone={/blocked|fail|limit/i.test(loopExit) ? "warn" : "good"} />
        <Metric label="Loop health" value={loopHealth} tone={loopWarn ? "bad" : hasLoopQuality ? "good" : "warn"} />
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
        <div><small>Run loop summary</small><pre>{`exit=${loopExit}
rounds=${String(agentLoopSummary.rounds_completed ?? runLoopSummary.iteration_count ?? "n/a")}/${String(agentLoopSummary.max_rounds ?? "n/a")}`}</pre></div>
        <div><small>Loop quality (SLO · observe_then_warn)</small><pre>{hasLoopQuality
          ? `mode=${String(loopQuality.mode ?? "n/a")}  warn=${String(loopQuality.warn ?? false)}  severity=${loopSeverity}
identical=${String(loopQuality.repeated_identical_observations ?? 0)}/${String(loopQuality.repeated_identical_window ?? "n/a")}  failed_verify=${String(loopQuality.repeated_failed_verifications ?? 0)}/${String(loopQuality.repeated_failed_window ?? "n/a")}  hard_block=${String(loopQuality.hard_block ?? false)}
reason=${String(loopQuality.reason ?? "none")}`
          : "not recorded (run predates loop_quality_guard)"}</pre></div>
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

export function EvidenceExplorer({
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
          <WorkflowMonitorPanel
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

