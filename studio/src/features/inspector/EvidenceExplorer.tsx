import React, { useState } from "react";
import { FileText, ShieldAlert } from "lucide-react";
import type { AnyRecord, OverviewPayload, RunDetailPayload, StudioEvent } from "../../types";
import { Metric, formatMs, Status } from "../../components/Shared";
import { WorkflowMonitorPanel } from "../../components/WorkflowMonitorPanel";
import { CopyablePre } from "../../components/CopyablePre";
import { VerificationMatrix, LoopQualityMatrix } from "./VerificationMatrix";
import { firstText } from "../../narrative";
import {
  asArray,
  asRecord,
  formatUsage,
  metricTone,
  rollingValidationFromOverview,
  workerCountFromTree,
} from "./inspectorUtils";

type EvidenceSelection = {
  title: string;
  kind: string;
  summary: string;
  item: AnyRecord;
};

// (INS-2) ContextBreakdownPanel removed — the context-window breakdown now lives solely in the
// dedicated Context tab (ContextPanel), so the Evidence tab no longer duplicates it.

function RunUsagePanel({ runDetail }: { runDetail: RunDetailPayload | null }) {
  const cost = asRecord(runDetail?.cost_report);
  if (!cost || Object.keys(cost).length === 0) return null;
  // Token/call aggregates only. There is no monetary cost in cost_report (no per-model pricing in
  // the runtime), so this panel deliberately reports usage, not USD — do not label it "cost".
  const inputTokens = cost.estimated_input_tokens;
  const outputTokens = cost.estimated_output_tokens;
  const strong = Number(cost.strong_model_calls ?? 0);
  const cheap = Number(cost.cheap_model_calls ?? 0);
  const repairs = Number(cost.repair_attempts ?? 0);
  // S78: surface the auto-repair budget as "used/cap" when the run recorded a per-task cap, so the
  // number reads as bounded ("2/4") rather than an unbounded count. auto_repair_enabled distinguishes
  // an active auto-repair loop from the (default) human-gated repair path.
  const loopBudget = asRecord(asRecord(runDetail?.agent_loop_run_summary).budget);
  const repairCap = Number(loopBudget.repair_attempts_limit ?? 0);
  const autoRepair = loopBudget.auto_repair_enabled === true;
  const repairValue =
    repairCap > 0 ? `${repairs}/${repairCap}${autoRepair ? " auto" : ""}` : String(repairs);
  const repairTone = repairCap > 0 && repairs >= repairCap ? "bad" : repairs ? "warn" : "good";
  // S79 auto-replan: the replan loop is bounded by a per-task cap but is deliberately NOT counted in
  // cost_report (no fabricated budget ledger), so we surface the bounded cap ("≤N auto") only when
  // auto-replan is active — honest about the budget without inventing a used count. Exhaustion shows
  // up in the run's exit_reason ("replan_budget_exhausted"), rendered by the thread guidance text.
  const replanCap = Number(loopBudget.replan_attempts_limit ?? 0);
  const autoReplan = loopBudget.auto_replan_enabled === true;
  const tokenValue = (value: unknown) => (value == null ? "未知" : formatUsage(Number(value)));
  return (
    <div className="evidenceBlock runUsagePanel">
      <small>运行用量</small>
      <div className="evidenceStats">
        <Metric label="模型调用" value={String(Number(cost.model_calls ?? 0))} tone="good" />
        <Metric label="工具调用" value={String(Number(cost.tool_calls ?? 0))} tone="good" />
        <Metric label="输入 token" value={tokenValue(inputTokens)} tone="warn" />
        <Metric label="输出 token" value={tokenValue(outputTokens)} tone="warn" />
      </div>
      <div className="evidenceStats">
        <Metric label="强模型调用" value={String(strong)} tone={strong ? "warn" : "good"} />
        <Metric label="廉价模型调用" value={String(cheap)} tone="good" />
        <Metric label="修复次数" value={repairValue} tone={repairTone} />
        {autoReplan && replanCap > 0 && (
          <Metric label="重规划" value={`≤${replanCap} auto`} tone="warn" />
        )}
      </div>
      {inputTokens == null && outputTokens == null && (
        <p className="muted">本次运行的 token 用量未知(供应商未报告用量)。</p>
      )}
    </div>
  );
}

export function BackgroundRunPanel({ overview }: { overview: OverviewPayload | null }) {
  const background = asRecord(overview?.background_runs);
  if (!background || background.enabled === false) return null;
  const runningCount = Number(background.running_count ?? 0);
  const totalCount = Number(background.total_count ?? 0);
  const badgeStatus = firstText(String(background.badge_status ?? ""), "空闲");
  const summary = firstText(String(background.badge_summary ?? ""), "暂无后台运行状态记录。");
  const latest = asRecord(background.latest);

  return (
    <div className="evidenceBlock backgroundRunPanel">
      <small>本地后台运行</small>
      <div className="workerSchedulingBadge" data-fake-path="false">
        {runningCount > 0 ? `本地子进程 · ${runningCount} 个运行中` : "本地子进程 · 空闲"}
      </div>
      <div className="evidenceStats">
        <Metric label="标记" value={badgeStatus} tone={runningCount ? "warn" : "good"} />
        <Metric
          label="运行中"
          value={`${runningCount}/${totalCount}`}
          tone={runningCount ? "warn" : "good"}
        />
        <Metric label="云端 VM" value="暂缓" tone="good" />
      </div>
      <div className="keyValueList">
        <div>
          <small>摘要</small>
          <pre>{summary}</pre>
        </div>
        {latest && Object.keys(latest).length > 0 && (
          <div>
            <small>最新</small>
            <pre>{`${String(latest.background_run_id ?? "n/a")} · ${String(latest.status ?? "unknown")}\n${String(latest.goal ?? "")}`}</pre>
          </div>
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
  const status = firstText(String(longHorizon.status ?? ""), "未知");
  const summary = firstText(String(longHorizon.summary ?? ""), "暂无长程摘要记录。");
  const configured = longHorizon.north_star_configured === true;
  const ready = longHorizon.ready_for_implementation === true;

  return (
    <div className="evidenceBlock longHorizonPanel">
      <small>长程规划(检查器)</small>
      <div className="evidenceStats">
        <Metric label="状态" value={status} tone={configured ? "good" : ready ? "warn" : "warn"} />
        <Metric
          label="里程碑"
          value={
            configured
              ? `${String(northStar.completed_milestones ?? 0)}/${String(northStar.milestone_count ?? 0)}`
              : "n/a"
          }
          tone={configured ? "good" : "warn"}
        />
        <Metric label="就绪" value={ready ? "是" : "否"} tone={ready ? "good" : "warn"} />
      </div>
      <div className="keyValueList">
        <div>
          <small>摘要</small>
          <pre>{summary}</pre>
        </div>
        {configured && (
          <>
            <div>
              <small>标题</small>
              <pre>{String(northStar.title ?? "")}</pre>
            </div>
            <div>
              <small>当前里程碑</small>
              <pre>{String(northStar.active_milestone ?? "none")}</pre>
            </div>
            <div>
              <small>陈述</small>
              <pre>{String(northStar.statement ?? "")}</pre>
            </div>
          </>
        )}
        {handoffCompact.available === true && (
          <>
            <div>
              <small>交接摘要</small>
              <pre>{String(handoffCompact.narrative ?? "")}</pre>
            </div>
            {handoffCompact.recommended_next_command ? (
              <div>
                <small>继续</small>
                <pre>{String(handoffCompact.recommended_next_command)}</pre>
              </div>
            ) : null}
          </>
        )}
      </div>
    </div>
  );
}

function V02ReadinessPanel({
  overview,
  runDetail,
}: {
  overview: OverviewPayload | null;
  runDetail: RunDetailPayload | null;
}) {
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
  const loopExit = firstText(
    String(agentLoopSummary.exit_reason ?? ""),
    String(legacyLoopSummary.stop_reason ?? ""),
    "unknown",
  );
  const loopRounds = firstText(
    `${String(agentLoopSummary.rounds_completed ?? "n/a")}/${String(agentLoopSummary.max_rounds ?? "n/a")}`,
    String(legacyLoopSummary.iteration_count ?? ""),
  );
  const nextAction = firstText(
    String(asArray(rolling.next_actions)[0] ?? ""),
    String(legacyLoopSummary.recommended_next_command ?? ""),
    "未记录动作",
  );
  const coverageLine = ["route", "context", "capability", "loop", "worker"]
    .map((key) => `${key}=${coverage[key] === true ? "yes" : "no"}`)
    .join(", ");

  return (
    <div className="evidenceBlock v02ReadinessPanel">
      <small>v0.2 就绪度</small>
      <div className="evidenceStats">
        <Metric
          label="证据包"
          value={`${rollingStatus} (${sampleCount})`}
          tone={metricTone(rollingStatus)}
        />
        <Metric
          label="循环退出"
          value={loopExit}
          tone={metricTone(
            String(agentLoopSummary.status ?? legacyLoopSummary.workflow_state ?? loopExit),
          )}
        />
        <Metric
          label="工作者"
          value={`${String(workerTree.successful_workers ?? 0)}/${String(workerTotal)}`}
          tone={Number(workerTree.failed_workers ?? 0) ? "bad" : workerTotal ? "good" : "warn"}
        />
      </div>
      <div className="keyValueList">
        <div>
          <small>证据覆盖</small>
          <pre>{coverageLine || "未找到 v0.2 滚动验证证据包。"}</pre>
        </div>
        <div>
          <small>缺失证据</small>
          <pre>{missing.length ? missing.join(", ") : "无"}</pre>
        </div>
        <div>
          <small>循环摘要</small>
          <pre>{`exit=${loopExit}
rounds=${loopRounds}
latest_action=${String(agentLoopSummary.latest_action ?? "n/a")}`}</pre>
        </div>
        <div>
          <small>工作者树</small>
          <pre>{`roots=${asArray(workerTree.roots).length}
orphans=${asArray(workerTree.orphan_workers).length}
graph=${String(agentRunGraph.status ?? "unknown")}
parallel_batches=${String(workerTree.parallel_batches ?? 0)}`}</pre>
        </div>
        <div>
          <small>下一步动作</small>
          <pre>{nextAction}</pre>
        </div>
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
      <small>证据详情</small>
      {!selection ? (
        <p className="muted">选择一个工作者、进度条目、路由、验证或运行文件,以查看其证据。</p>
      ) : (
        <>
          <div className="evidenceDetailHeader">
            <strong>{selection.title}</strong>
            <span>{selection.kind}</span>
          </div>
          <p>{selection.summary}</p>
          <CopyablePre text={JSON.stringify(selection.item, null, 2)} />
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
      <small>候选合并预览</small>
      <div className="evidenceStats">
        <Metric
          label="导出"
          value={String(preview.export_count ?? 0)}
          tone={Number(preview.export_count ?? 0) ? "good" : "warn"}
        />
        <Metric
          label="预览"
          value={mergeStatus === "ready" ? "就绪" : mergeStatus === "needs_review" ? "待查看" : "—"}
          tone={mergeStatus === "ready" ? "good" : mergeStatus === "needs_review" ? "bad" : "warn"}
        />
        <Metric
          label="待处理"
          value={String(preview.pending_promotions ?? 0)}
          tone={Number(preview.pending_promotions ?? 0) ? "warn" : "good"}
        />
      </div>
      {preview.merge_preview_summary ? (
        <p className="promotionPreviewSummary">{String(preview.merge_preview_summary)}</p>
      ) : null}
      {asArray(preview.lineages).length > 0 && (
        <div className="lineageList">
          <p className="sideTitle">隔离 → 验证 → 合并</p>
          {(asArray(preview.lineages) as AnyRecord[]).map((lin, i) => {
            const isolated = asRecord(lin.isolated);
            const verified = asRecord(lin.verified);
            const merged = asRecord(lin.merged);
            const riskyFiles = asArray(merged.risky_files).map(String);
            const mergedStatus = String(merged.status ?? "");
            const mergeLabel =
              mergedStatus === "promoted"
                ? "已合并"
                : mergedStatus === "pending_manual_approval"
                  ? "待人工查看"
                  : mergedStatus
                    ? mergedStatus.replace(/_/g, " ")
                    : "—";
            const isoFiles = Number(isolated.files ?? 0);
            const mergedFiles = Number(merged.files ?? 0);
            return (
              <div className="lineageRow" key={String(lin.task_id ?? i)}>
                <span className="lineageStage">
                  <small>隔离</small>
                  <strong>
                    {isoFiles ? `${isoFiles} 个文件` : String(isolated.status ?? "—")}
                  </strong>
                </span>
                <span className="lineageArrow">→</span>
                <span className="lineageStage">
                  <small>验证{verified.batch ? "(批量)" : ""}</small>
                  <strong>
                    {verified.ok === true ? "通过" : verified.ok === false ? "待查看" : "—"}
                  </strong>
                </span>
                <span className="lineageArrow">→</span>
                <span
                  className={
                    mergedStatus === "pending_manual_approval"
                      ? "lineageStage held"
                      : "lineageStage"
                  }
                >
                  <small>合并</small>
                  <strong>
                    {mergeLabel}
                    {mergedFiles ? ` · ${mergedFiles}` : ""}
                  </strong>
                </span>
                {riskyFiles.length > 0 && (
                  <span className="lineageRisk" title={riskyFiles.join(", ")}>
                    <ShieldAlert size={11} /> {riskyFiles.length}
                  </span>
                )}
              </div>
            );
          })}
        </div>
      )}
      <div className="promotionPreviewList">
        {items.slice(0, 8).map((item, index) => {
          const kind = String(item.kind ?? "item");
          const id = String(item.id ?? `item-${index + 1}`);
          const key = `${kind}:${id}`;
          const files = asArray(item.files).map(String).join(", ");
          // Honest: only when THIS held promotion's own merge_gate flagged files. No risk list for
          // empty risky_files (cause may be a deletion, which isn't recorded here).
          const riskyFiles = asArray(item.risky_files).map(String);
          const heldForReview =
            String(item.status ?? "") === "pending_manual_approval" && riskyFiles.length > 0;
          return (
            <button
              key={key}
              className={`promotionPreviewItem ${selectedKey === key ? "active" : ""}`}
              onClick={() =>
                onSelectEvidence({
                  title: id,
                  kind,
                  summary: files || String(item.summary ?? item.status ?? kind),
                  item,
                })
              }
            >
              <span className="promotionPreviewItemHead">
                <span>{kind.replace(/_/g, " ")}</span>
                <Status
                  status={
                    (item.ok === false || item.status === "blocked"
                      ? "blocked"
                      : item.status === "ready"
                        ? "completed"
                        : "running") as StudioEvent["status"]
                  }
                />
              </span>
              <pre>
                {[
                  item.task_id ? `task=${String(item.task_id)}` : "",
                  files ? `files=${files}` : "",
                  item.execution_profile_id ? `profile=${String(item.execution_profile_id)}` : "",
                ]
                  .filter(Boolean)
                  .join("\n")}
              </pre>
              {heldForReview && (
                <span className="promotionPreviewItemRisk">
                  <ShieldAlert size={12} />
                  <span>已扣留待你查看 — 被标记为敏感: {riskyFiles.join(", ")}</span>
                </span>
              )}
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
      <small>工作者拓扑</small>
      <div className="workerTopologyStats">
        <Metric label="根节点" value={String(asArray(workerTree.roots).length)} tone="warn" />
        <Metric
          label="并行"
          value={String(workerTree.parallel_batches ?? 0)}
          tone={Number(workerTree.parallel_batches ?? 0) ? "good" : "warn"}
        />
        <Metric
          label="失败"
          value={String(workerTree.failed_workers ?? 0)}
          tone={Number(workerTree.failed_workers ?? 0) ? "bad" : "good"}
        />
      </div>
      <div className="workerTopologyList">
        {workers.slice(0, 12).map((worker, index) => {
          const workerId = firstText(
            worker.worker_invocation_id,
            worker.worker_id,
            worker.agent_id,
            `worker-${index + 1}`,
          );
          const status = String(worker.status ?? worker.outcome ?? "unknown");
          const profile = firstText(
            worker.execution_profile_id,
            worker.runtime_profile_id,
            worker.profile_id,
            worker.worker_kind,
            "profile unknown",
          );
          const safety = firstText(
            worker.parallel_safety,
            worker.sandbox_profile_id,
            worker.spawn_kind,
            "safety unknown",
          );
          const workspaceRef = firstText(
            worker.candidate_workspace,
            worker.workspace,
            worker.workspace_path,
            "",
          );
          const key = `worker:${workerId}`;
          return (
            <button
              key={`${workerId}-${index}`}
              className={`workerTopologyItem ${selectedKey === key ? "active" : ""}`}
              onClick={() =>
                onSelectEvidence({
                  title: workerId,
                  kind: "worker",
                  summary: `${status} · ${String(worker.task_id ?? "no task")}`,
                  item: worker,
                })
              }
            >
              <span className="workerTopologySummary">
                <span style={{ paddingLeft: `${Math.min(Number(worker.depth ?? 0), 4) * 10}px` }}>
                  {workerId}
                </span>
                <Status status={status as StudioEvent["status"]} />
              </span>
              <pre>
                {[
                  `task=${String(worker.task_id ?? "n/a")}`,
                  `parent=${String(worker.parent_worker_invocation_id ?? worker.parent_task_id ?? "root")}`,
                  `profile=${profile}`,
                  `safety=${safety}`,
                  workspaceRef ? `workspace=${workspaceRef}` : "",
                ]
                  .filter(Boolean)
                  .join("\n")}
              </pre>
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
  const workflowState = firstText(
    String(finalSummary.workflow_state ?? ""),
    String(runLoopSummary.workflow_state ?? ""),
    String(run.current_phase ?? "unknown"),
  );
  const nextCommand = firstText(
    String(mainAction.next_command ?? ""),
    String(finalSummary.recommended_next_command ?? ""),
    String(runLoopSummary.recommended_next_command ?? ""),
    "none",
  );
  const nextLabel = firstText(String(mainAction.label ?? ""), nextCommand);
  const commandDisplay =
    nextCommand === "none"
      ? "无需操作"
      : /^asteria\b/i.test(nextCommand)
        ? nextCommand
        : `asteria ${nextCommand}`;
  const blocker = firstText(
    String(finalSummary.current_blocker ?? ""),
    String(runLoopSummary.current_blocker ?? ""),
    "none",
  );
  const loopExit = firstText(
    String(agentLoopSummary.exit_reason ?? ""),
    String(runLoopSummary.stop_reason ?? ""),
    "n/a",
  );
  // loop_quality_guard SLO (observe_then_warn): an auditable no-progress signal, NOT a hard stop
  // (ADR-0010). Surface it honestly — real values when recorded, "not recorded" for older runs.
  const loopQuality = asRecord(agentLoopSummary.loop_quality);
  const hasLoopQuality = Object.keys(loopQuality).length > 0;
  const loopWarn = Boolean(loopQuality.warn);
  const loopSeverity = firstText(String(loopQuality.severity ?? ""), loopWarn ? "warn" : "ok");
  const loopHealth = hasLoopQuality ? (loopWarn ? `warn (${loopSeverity})` : "ok") : "未记录";

  return (
    <div className="evidenceBlock runStatusPanel">
      <small>长任务循环</small>
      <div className="evidenceStats">
        <Metric
          label="状态"
          value={workflowState}
          tone={/blocked|fail|need/i.test(workflowState) ? "bad" : "good"}
        />
        <Metric label="下一步" value={nextLabel} tone={nextCommand === "none" ? "good" : "warn"} />
        <Metric
          label="循环退出"
          value={loopExit}
          tone={/blocked|fail|limit/i.test(loopExit) ? "warn" : "good"}
        />
        <Metric
          label="循环健康"
          value={loopHealth}
          tone={loopWarn ? "bad" : hasLoopQuality ? "good" : "warn"}
        />
      </div>
      <div className="keyValueList">
        <div>
          <small>当前状态</small>
          <pre>{`${String(run.status ?? "unknown")} / ${String(run.current_phase ?? "unknown")}`}</pre>
        </div>
        <div>
          <small>当前阻塞项</small>
          <pre>{blocker}</pre>
        </div>
        <div>
          <small>建议命令</small>
          <pre>{commandDisplay}</pre>
        </div>
        <div>
          <small>主动作来源</small>
          <pre>{`kind=${String(mainAction.kind ?? "unknown")}
status=${String(mainAction.status ?? "unknown")}
requires_permission=${String(mainAction.requires_permission ?? "unknown")}
source=${String(mainAction.source ?? "unknown")}
evidence=${asArray(mainAction.evidence_refs).join(", ") || "none"}`}</pre>
        </div>
        <div>
          <small>运行循环摘要</small>
          <pre>{`exit=${loopExit}
rounds=${String(agentLoopSummary.rounds_completed ?? runLoopSummary.iteration_count ?? "n/a")}/${String(agentLoopSummary.max_rounds ?? "n/a")}`}</pre>
        </div>
        <div>
          <small>模型路由依据</small>
          <pre>{`${String(latestRoute.purpose ?? "unknown")} -> ${String(latestRoute.selected_tier ?? "unknown")}
reason=${String(latestRoute.reason ?? "未记录路由原因。")}`}</pre>
        </div>
      </div>
      <LoopQualityMatrix loopQuality={loopQuality} />
    </div>
  );
}

function progressToStudioEvent(item: AnyRecord, runId: unknown): StudioEvent {
  // A progress row with no recorded status is unknown, not "completed" — defaulting to completed
  // renders an in-flight/unknown step with a green finished badge in the Inspector.
  const status = String(item.status ?? "running") as StudioEvent["status"];
  const phase = String(item.phase ?? item.channel ?? "execute");
  return {
    event_id: String(item.event_id ?? `runtime-progress-${Date.now()}`),
    session_id: "runtime-progress",
    type: "assistant_delta",
    status,
    title: firstText(String(item.title ?? ""), String(item.event_type ?? ""), "运行时进度"),
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
  const [evidenceFilter, setEvidenceFilter] = useState("");
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
  // Already assembled server-side (payload.mcp_invocations / skill_invocations) but previously
  // rendered nowhere despite inspector_raw_evidence_source promising raw evidence.
  const mcpInvocations = (runDetail?.mcp_invocations ?? []) as AnyRecord[];
  const skillInvocations = (runDetail?.skill_invocations ?? []) as AnyRecord[];
  const capabilityDecisions = (runDetail?.capability_decisions ?? []) as AnyRecord[];
  const runtimeHooks = (runDetail?.runtime_hooks ?? []) as AnyRecord[];
  const files = runDetail?.files ?? [];
  const selectedKey = selectedEvidence ? `${selectedEvidence.kind}:${selectedEvidence.title}` : "";

  function selectEvidence(selection: EvidenceSelection) {
    setSelectedEvidence(selection);
  }

  function selectProgress(item: AnyRecord, index: number) {
    const title = firstText(
      String(item.title ?? ""),
      String(item.event_type ?? ""),
      `progress-${index + 1}`,
    );
    selectEvidence({
      title,
      kind: "progress",
      summary: firstText(String(item.summary ?? ""), String(item.phase ?? ""), "未记录摘要。"),
      item,
    });
    onSelectRunEvent(progressToStudioEvent(item, runDetail?.run_id));
  }

  function renderLine(item: AnyRecord, kind: string): string {
    if (kind === "progress")
      return firstText(
        `${String(item.channel ?? "progress")}/${String(item.event_type ?? "message")} ${String(item.phase ?? "")} ${String(item.status ?? "")}`,
        String(item.summary ?? ""),
        String(item.title ?? ""),
      );
    if (kind === "model") {
      const route = [item.model_provider, item.model_name, item.purpose].filter(Boolean).join("/");
      return firstText(
        `${route || "model"} ${String(item.status ?? "")} ${formatMs(item.duration_ms)}`,
        String(item.error ?? ""),
      );
    }
    if (kind === "validation")
      return firstText(
        `${String(item.name ?? item.command ?? "validation")} ${String(item.status ?? item.outcome ?? "")}`,
        String(item.summary ?? ""),
      );
    if (kind === "worker")
      return firstText(
        `${String(item.task_id ?? item.worker_id ?? "worker")} ${String(item.status ?? item.outcome ?? "")}`,
        String(item.summary ?? ""),
      );
    if (kind === "evidence")
      return firstText(
        `${String(item.task_id ?? item.kind ?? "evidence")} ${String(item.status ?? item.outcome ?? "")}`,
        String(item.path ?? ""),
      );
    // A hook row reads as "which hook fired, on which task" — the summary carries what it did.
    if (kind === "hook")
      return firstText(
        `${String(item.hook_name ?? "hook")} ${String(item.task_id ?? "")}`.trim(),
        String(item.summary ?? ""),
      );
    if (kind === "route")
      return firstText(
        `${String(item.task_id ?? item.purpose ?? "route")} ${String(item.purpose ?? "")} -> ${String(item.selected_tier ?? "unknown")}`,
        String(item.reason ?? ""),
      );
    if (kind === "mcp")
      return firstText(
        `${String(item.server_name ?? "mcp")}/${String(item.tool_name ?? "")} ${String(item.status ?? "")}`,
        String(item.summary ?? ""),
      );
    if (kind === "skill")
      return firstText(
        `${String(item.skill_name ?? item.name ?? "skill")} ${String(item.status ?? "")}`,
        String(item.summary ?? ""),
      );
    if (kind === "capability") {
      const decision = asRecord(item.decision);
      return firstText(
        `${String(item.capability_type ?? "cap")}:${String(item.capability ?? "")} -> ${String(decision.decision ?? decision.effect ?? "")}`,
        String(decision.reason ?? ""),
      );
    }
    return JSON.stringify(item).slice(0, 80);
  }

  function EvidenceBlock({
    title,
    items,
    kind,
  }: {
    title: string;
    items: AnyRecord[];
    kind: string;
  }) {
    const query = evidenceFilter.trim().toLowerCase();
    // Preserve the original index (selectProgress uses it for a stable "progress-N" fallback label).
    const shown = items
      .map((item, index) => ({ item, index, line: renderLine(item, kind) }))
      .filter(({ line }) => !query || line.toLowerCase().includes(query));
    // While filtering, hide blocks with no match so the search declutters instead of showing a
    // wall of empty sections.
    if (query && !shown.length) return null;
    return (
      <div className="evidenceBlock">
        <small>
          {title}
          {query && shown.length !== items.length ? ` (${shown.length}/${items.length})` : ""}
        </small>
        {!shown.length && <p className="muted">暂无记录。</p>}
        <div className="evidenceSelectableList">
          {shown.map(({ item, index, line }) => {
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
                  selectEvidence({
                    title: line,
                    kind,
                    summary: firstText(String(item.summary ?? ""), String(item.reason ?? ""), line),
                    item,
                  });
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
      <h2>证据浏览器</h2>
      <div className="runPicker">
        {runs.length === 0 && <p className="muted">暂无本地运行证据。</p>}
        {runs.slice(0, 6).map((run) => {
          const runId = String(run.run_id ?? "");
          return (
            <button
              className={selectedRunId === runId ? "active" : ""}
              key={runId}
              onClick={() => void onOpenRun(runId)}
            >
              {runId}
            </button>
          );
        })}
      </div>
      {runDetail?.error && <p className="muted">{runDetail.error}</p>}
      {runDetail?.ok && (
        <>
          <div className="evidenceSearch">
            <input
              type="search"
              value={evidenceFilter}
              onChange={(event) => setEvidenceFilter(event.target.value)}
              placeholder="过滤证据(名称、状态、路由…)"
              aria-label="过滤证据"
            />
            {evidenceFilter && (
              <button
                type="button"
                className="evidenceSearchClear"
                onClick={() => setEvidenceFilter("")}
                aria-label="清除过滤"
              >
                ×
              </button>
            )}
          </div>
          <V02ReadinessPanel overview={overview} runDetail={runDetail} />
          <RunStatusPanel runDetail={runDetail} />
          <RunUsagePanel runDetail={runDetail} />
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
            <Metric
              label="模型调用"
              value={String(modelCalls.length)}
              tone={modelCalls.some((m) => m.status === "failure") ? "bad" : "good"}
            />
            <Metric
              label="验证"
              value={String(validations.length)}
              tone={
                validations.some((v) => /fail|error/i.test(String(v.status ?? v.outcome ?? "")))
                  ? "bad"
                  : "warn"
              }
            />
            <Metric
              label="进度"
              value={String(userProgress.length)}
              tone={userProgress.length ? "good" : "warn"}
            />
          </div>
          <EvidenceBlock title="模型路由时间线" items={routeTimeline.slice(-8)} kind="route" />
          <EvidenceBlock title="用户进度" items={userProgress.slice(-8)} kind="progress" />
          <EvidenceBlock title="模型调用" items={modelCalls.slice(-5)} kind="model" />
          <VerificationMatrix
            validations={validations.slice(-8)}
            selectedKey={selectedKey}
            onSelect={(item, label) =>
              selectEvidence({
                title: label,
                kind: "validation",
                summary: firstText(String(item.summary ?? ""), String(item.reason ?? ""), label),
                item,
              })
            }
          />
          <EvidenceBlock title="工作者结果" items={workers.slice(-4)} kind="worker" />
          <EvidenceBlock title="任务证据" items={evidence.slice(-4)} kind="evidence" />
          <EvidenceBlock title="MCP 调用" items={mcpInvocations.slice(-8)} kind="mcp" />
          <EvidenceBlock title="技能调用" items={skillInvocations.slice(-8)} kind="skill" />
          <EvidenceBlock title="能力决策" items={capabilityDecisions.slice(-8)} kind="capability" />
          <EvidenceBlock title="运行时 Hook" items={runtimeHooks.slice(-8)} kind="hook" />
          {files.length > 0 && (
            <div className="runFiles">
              <small>运行文件 ({files.length})</small>
              {files.map((file) => (
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
