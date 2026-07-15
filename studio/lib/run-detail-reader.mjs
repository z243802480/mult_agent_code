// Run-evidence reader subsystem — the connected evidence subgraph (readRunDetail + its 14 helpers),
// extracted verbatim from server.mjs (see docs/zh/notes/server-mjs-split-plan.md Layer 2). These
// functions derive UI-facing run detail from the on-disk .asteria/runs evidence; the heavy pure leaf
// transforms they call already live in ./run-evidence-transforms.mjs and are imported directly here.
//
// Wiring: only `workspace` is live-injected (getWorkspace) because it is a mutable `let` in server.mjs
// reassigned on openWorkspace — readRunDetail and runtimeActionByKind read it. `python`/`moduleName`
// are stable consts, injected by value. Five functions (readRunDetail, runtimeActionFor,
// runtimeActionByKind, userProgressToStudioEvent, permissionPreview) are called from outside the
// subgraph (handleApi / runtime-job / permissionPreviewForMode) and are re-exported for server.mjs.
import { existsSync, promises as fs } from "node:fs";
import path from "node:path";
import { redact, firstRuntimeText } from "./text-utils.mjs";
import { readJson, readJsonlTail } from "./run-io.mjs";
import { isSafeId, isSafeWorkspacePath, isPreviewableFile } from "./workspace-paths.mjs";
import { buildOrchestrationWorkflowMonitor } from "./orchestration-workflow-monitor.mjs";
import {
  runtimeRequestDetailValues,
  scopeValueSummary,
  latestMainTranscriptEvent,
  latestMainToolEvent,
  latestMainFinalEvent,
  flattenWorkerNodes,
  promotionPreviewHint,
  latestDecisions,
} from "./run-evidence-transforms.mjs";

export function createRunDetailReader({ getWorkspace, python, moduleName }) {
  function runtimeActionFor(value) {
    const raw = String(value || "")
      .trim()
      .toLowerCase();
    if (!raw) return null;
    const normalized = raw
      .replace(/^asteria\s+/, "")
      .replace(/^python\s+-m\s+\S+\s+/, "")
      .replace(/\s+--latest\b/g, "")
      .trim();
    const first = normalized.split(/\s+/)[0];
    const kind = {
      review: "review",
      accept: "accept",
      resume: "continue",
      continue: "continue",
      run: "continue",
      replan: "continue",
      debug: "debug",
      repair: "debug",
      decide: "decide",
      compact: "compact",
    }[first];
    if (!kind) return null;
    return runtimeActionByKind(kind);
  }

  function runtimeActionByKind(kind) {
    const actions = {
      review: {
        kind: "review",
        label: "Review",
        mode: "review",
        goal: "查看最新的运行结果。",
        command: [python, "-m", moduleName, "review", "--root", getWorkspace()],
        requiresPermission: false,
        summary: "我会查看最新结果并展示结论。",
        permissionSummary: "",
      },
      accept: {
        kind: "accept",
        label: "Accept",
        mode: "accept",
        goal: "接受最新已查看的结果。",
        command: [python, "-m", moduleName, "accept", "--root", getWorkspace()],
        requiresPermission: true,
        summary: "确认后我会接受已验证的结果。",
        permissionSummary: "接受结果会更新当前运行时状态。请确认是否继续。",
        permissionPreview: permissionPreview({
          action: "接受已查看的结果",
          impact: "最终确定已查看的运行结果。",
          scope: "当前运行时状态",
          network: "不需要网络访问。",
          risk: "low",
          reversible: "继续前可先查看改动。",
        }),
      },
      continue: {
        kind: "continue",
        label: "Continue",
        mode: "resume",
        goal: "继续当前的运行时目标。",
        command: [
          python,
          "-m",
          moduleName,
          "resume",
          "--root",
          getWorkspace(),
          "--max-iterations",
          "8",
          "--max-tasks-per-iteration",
          "1",
        ],
        requiresPermission: true,
        summary: "确认后我会继续当前目标。",
        permissionSummary: "继续推进可能会修改文件或运行本地操作。请确认是否继续。",
        permissionPreview: permissionPreview({
          action: "继续当前目标",
          impact: "可能会修改工作区文件并运行本地验证。",
          scope: "当前工作区",
          network: "可能会联系模型服务商；外部工具仍需单独批准。",
          risk: "medium",
          reversible: "改动在接受前都可查看。",
        }),
      },
      debug: {
        kind: "debug",
        label: "Debug",
        mode: "debug",
        goal: "诊断并修复最近受阻的运行时步骤。",
        command: [python, "-m", moduleName, "debug", "--root", getWorkspace()],
        requiresPermission: true,
        summary: "确认后我会诊断受阻的步骤并准备修复路径。",
        permissionSummary: "调试修复可能会读取运行证据并修改文件。请确认是否继续。",
        permissionPreview: permissionPreview({
          action: "诊断并修复受阻的步骤",
          impact: "读取失败证据，并可能修改工作区文件。",
          scope: "当前工作区与运行证据",
          network: "可能会联系模型服务商；外部工具仍需单独批准。",
          risk: "medium",
          reversible: "修复在接受前都可查看。",
        }),
      },
      decide: {
        kind: "decide",
        label: "Decide",
        mode: "decide",
        goal: "列出当前运行时目标的待决事项。",
        command: [python, "-m", moduleName, "decide", "--root", getWorkspace(), "--list-pending"],
        requiresPermission: false,
        summary: "我会列出需要你决定的事项。",
        permissionSummary: "",
      },
      compact: {
        kind: "compact",
        label: "Compact",
        mode: "compact",
        goal: "压缩会话上下文以释放空间。",
        command: [python, "-m", moduleName, "compact", "--root", getWorkspace()],
        requiresPermission: true,
        summary: "确认后我会压缩当前会话上下文。",
        permissionSummary: "压缩上下文会摘要较早的对话轮次。请确认是否继续。",
        permissionPreview: permissionPreview({
          action: "压缩会话上下文",
          impact: "摘要较早的对话轮次以释放上下文空间。",
          scope: "当前会话上下文",
          network: "不需要网络访问。",
          risk: "low",
          reversible: "不会修改工作区文件。",
        }),
      },
    };
    return actions[kind] ?? null;
  }

  function permissionPreview({ action, impact, scope, network, risk, reversible, scope_detail }) {
    return {
      action,
      impact,
      scope,
      network,
      risk,
      reversible,
      ...(scope_detail ? { scope_detail } : {}),
    };
  }

  function userProgressToStudioEvent(event, sessionId, runId) {
    const channel = String(event.channel || "");
    const eventType = String(event.event_type || "");
    const transcriptKind = String(event.transcript_kind || "");
    let type = "reasoning_delta";
    if (transcriptKind === "final" || transcriptKind === "stop") {
      type = "final_answer";
    } else if (transcriptKind === "tool_use") {
      type = "tool_start";
    } else if (transcriptKind === "tool_result") {
      type = "tool_end";
    } else if (transcriptKind === "file_change") {
      type = "file_changed";
    } else if (transcriptKind === "verification") {
      type = "tool_observation";
    } else if (transcriptKind === "permission_request") {
      type = "permission_request";
    } else if (channel === "model") {
      if (eventType === "start") type = "model_start";
      else if (eventType === "delta") type = "model_delta";
      else if (eventType === "end") type = "model_end";
      else if (eventType === "error") type = "model_error";
    } else if (channel === "tool") {
      if (eventType === "tool_call") type = "tool_start";
      else if (eventType === "tool_output") type = "tool_end";
      else if (eventType === "error") type = "error";
      else type = "tool_delta";
    } else if (channel === "file") {
      type = "file_changed";
    } else if (channel === "execution_chain") {
      if (eventType === "turn_start" || eventType === "turn_end") type = "agent_turn";
      else type = eventType === "tool_observation" ? "tool_observation" : "reasoning_delta";
    } else if (channel === "conclusion") {
      type = event.phase === "result" ? "final_answer" : "assistant_delta";
    } else if (channel === "diagnostic") {
      type = "tool_delta";
    }
    return redact({
      schema_version: "0.1.0",
      event_id: `runtime-${runId}-${event.event_id}`,
      session_id: sessionId,
      type,
      status: event.status,
      title: event.title,
      summary: event.summary,
      content_delta: event.content_delta || "",
      command: event.command || [],
      data: event.data || {},
      tool_call_id: event.tool_call_id,
      parent_event_id: event.parent_event_id,
      artifact_refs: event.artifact_refs || [],
      evidence_refs: [...(event.evidence_refs || []), `.asteria/runs/${runId}/user_progress.jsonl`],
      model_provider: event.model_provider,
      model_name: event.model_name,
      telemetry: event.telemetry || {},
      phase: event.phase,
      display_level: event.display_level,
      created_at: event.created_at,
      source: "runtime_user_progress",
      runtime_channel: channel,
      runtime_event_type: eventType,
      transcript_kind: transcriptKind,
      ui_intent: event.ui_intent,
      actions: event.actions || [],
      file_changes: event.file_changes || [],
      run_id: runId,
    });
  }

  function enrichRuntimeRequestDecision(decision, runtimeRequests) {
    const metadata =
      decision?.metadata && typeof decision.metadata === "object" ? decision.metadata : {};
    if (metadata.kind !== "runtime_request" || metadata.permission_preview) return decision;
    const requestIds = new Set(
      Array.isArray(metadata.runtime_request_ids) ? metadata.runtime_request_ids.map(String) : [],
    );
    const matched = (runtimeRequests || []).filter((request) =>
      requestIds.has(String(request.runtime_request_id || "")),
    );
    if (!matched.length) return decision;
    return {
      ...decision,
      metadata: {
        ...metadata,
        permission_preview: permissionPreviewForRuntimeRequests(matched),
      },
    };
  }

  function permissionPreviewForRuntimeRequests(requests) {
    const readScope = runtimeRequestDetailValues(requests, [
      "read_scope",
      "requested_read_scope",
      "paths",
    ]);
    const writeScope = runtimeRequestDetailValues(requests, [
      "write_scope",
      "requested_write_scope",
    ]);
    const tools = runtimeRequestDetailValues(requests, [
      "allowed_tools",
      "tools",
      "tool",
      "tool_name",
    ]);
    const requestTypes = [
      ...new Set(requests.map((request) => String(request.request_type || "")).filter(Boolean)),
    ].sort();
    const riskRank = { low: 0, medium: 1, high: 2 };
    const risk =
      requests
        .map((request) => String(request.risk || "medium").toLowerCase())
        .sort((left, right) => (riskRank[right] ?? 1) - (riskRank[left] ?? 1))[0] || "medium";
    let action = "查看任务边界变更";
    let impact = "在继续之前查看请求的任务契约变更。";
    let reversible = "拒绝将保持当前任务边界不变。";
    if (writeScope.length) {
      action = "允许额外的工作区改动";
      impact = `允许写入 ${scopeValueSummary(writeScope)}。`;
      reversible = "改动在接受前都可查看。";
    } else if (readScope.length) {
      action = "允许额外的项目上下文";
      impact = `允许读取 ${scopeValueSummary(readScope)}。`;
      reversible = "本次批准不会修改工作区文件。";
    } else if (tools.length) {
      action = "允许一个额外的工具";
      impact = `允许使用 ${scopeValueSummary(tools)}。`;
      reversible = "该工具仍受当前任务契约约束。";
    }
    const scopeParts = [];
    if (readScope.length) scopeParts.push(`读取：${scopeValueSummary(readScope)}`);
    if (writeScope.length) scopeParts.push(`写入：${scopeValueSummary(writeScope)}`);
    if (tools.length) scopeParts.push(`工具：${scopeValueSummary(tools)}`);
    const externalTool = tools.some((tool) => /network|web|http|mcp/i.test(tool));
    return permissionPreview({
      action,
      impact,
      scope: scopeParts.join("；") || "当前任务契约",
      network: externalTool
        ? "请求的工具可能访问外部服务。"
        : requestTypes.includes("model_upgrade_request")
          ? "将为请求的路由联系模型服务商。"
          : "不需要额外的网络访问。",
      risk,
      reversible,
      scope_detail: {
        read_scope: readScope,
        write_scope: writeScope,
        tools,
        request_types: requestTypes,
      },
    });
  }

  function buildTranscriptRuntimeProgress(event, transcriptKind, taskSummary = null) {
    if (!event) return null;
    const data = event.data && typeof event.data === "object" ? event.data : {};
    const taskCount = Number(taskSummary?.total || 0) || Number(data.task_count || 0);
    const projection = {
      transcript_kind: transcriptKind,
      ui_intent: event.ui_intent || "work_progress",
      phase: event.phase,
      status: event.status,
      title: event.title,
      summary: event.summary,
      content_delta: event.content_delta || "",
      event_id: event.event_id,
      created_at: event.created_at,
    };
    if (taskCount) projection.task_count = taskCount;
    if (event.tool_call_id) projection.tool_call_id = event.tool_call_id;
    return projection;
  }

  function enrichRuntimeProgress(progress, payload) {
    const agentLoop = payload.agent_loop_run_summary || {};
    const runLoop = payload.run_loop_summary || {};
    const workerSummary = workerSummaryForProgress(
      payload.worker_tree || {},
      payload.worker_results || [],
      payload.promotion_preview || {},
    );
    const userProgress = payload.user_progress || [];
    const taskPlan = payload.task_plan || {};
    const taskSummary =
      Array.isArray(taskPlan.tasks) && taskPlan.tasks.length
        ? { total: taskPlan.tasks.length }
        : progress.todo?.counts || null;
    const toolEvent = latestMainToolEvent(userProgress);
    const toolKind = toolEvent?.transcript_kind || "tool_use";
    const finalEvent = latestMainFinalEvent(userProgress);
    const finalKind = finalEvent?.transcript_kind || "final";
    const planProjection = buildTranscriptRuntimeProgress(
      latestMainTranscriptEvent(userProgress, "plan"),
      "plan",
      taskSummary,
    );
    const toolProjection = buildTranscriptRuntimeProgress(toolEvent, toolKind);
    const verifyProjection = buildTranscriptRuntimeProgress(
      latestMainTranscriptEvent(userProgress, "verification"),
      "verification",
    );
    const finalProjection = buildTranscriptRuntimeProgress(finalEvent, finalKind);
    return {
      ...progress,
      ...(planProjection ? { plan: planProjection } : {}),
      ...(toolProjection ? { tool: toolProjection } : {}),
      ...(verifyProjection ? { verify: verifyProjection } : {}),
      ...(finalProjection ? { final: finalProjection } : {}),
      loop: {
        ...(progress.loop || {}),
        exit_reason: firstRuntimeText(
          progress.loop?.exit_reason,
          agentLoop.exit_reason,
          runLoop.stop_reason,
          "",
        ),
        rounds:
          progress.loop?.rounds ??
          agentLoop.rounds ??
          agentLoop.iteration_count ??
          runLoop.iteration_count,
      },
      worker_summary: workerSummary,
    };
  }

  function workerSummaryForProgress(workerTree, workerResults, promotionPreview = {}) {
    const total =
      Number(workerTree.total_workers ?? 0) ||
      (Array.isArray(workerResults) ? workerResults.length : 0);
    if (!total) return {};
    const failed = Array.isArray(workerResults)
      ? workerResults.filter((item) =>
          /fail|error|block|denied|timeout/i.test(String(item.status ?? item.outcome ?? "")),
        ).length
      : Number(workerTree.failed_workers ?? 0);
    const successful = Array.isArray(workerResults)
      ? workerResults.filter((item) =>
          /success|complete|pass|succeed/i.test(String(item.status ?? item.outcome ?? "")),
        ).length
      : Number(workerTree.successful_workers ?? 0);
    const parallel = Number(workerTree.parallel_batches ?? 0);
    const status = failed ? "failed" : successful >= total ? "completed" : "running";
    const profile = firstRuntimeText(
      Array.isArray(workerResults)
        ? workerResults
            .map((item) => item.worker_kind || item.agent_id)
            .filter(Boolean)
            .join(", ")
        : "",
      "worker",
    );
    const workers = flattenWorkerNodes(workerTree);
    const promotionHint = promotionPreviewHint(promotionPreview);
    const latestSwarm =
      workerTree.latest_swarm_plan && typeof workerTree.latest_swarm_plan === "object"
        ? workerTree.latest_swarm_plan
        : null;
    const schedulingMode = String(latestSwarm?.scheduling_mode || "").trim();
    const fakePath = latestSwarm?.fake_path;
    return {
      status,
      total,
      successful,
      failed,
      parallel_batches: parallel,
      progress_percent: total ? Math.round((successful / total) * 100) : 0,
      summary: failed
        ? `${failed} background task${failed === 1 ? "" : "s"} need attention.`
        : `${successful}/${total} background task${total === 1 ? "" : "s"} completed.`,
      worker_profile: profile,
      promotion_hint: promotionHint,
      scheduling_mode: schedulingMode || null,
      fake_path: typeof fakePath === "boolean" ? fakePath : null,
      parallel_writes: latestSwarm?.parallel_writes ?? null,
      spawn_kind: latestSwarm?.spawn_kind || null,
      workers,
      evidence_refs: [
        "workers.jsonl",
        "worker_results.jsonl",
        "swarm_execution_plans.jsonl",
        "agent_run_graph.json",
      ],
    };
  }

  function buildPromotionPreview(payload) {
    const exports = Array.isArray(payload.candidate_exports) ? payload.candidate_exports : [];
    const dryRuns = Array.isArray(payload.merge_gate_dry_runs) ? payload.merge_gate_dry_runs : [];
    const promotions = Array.isArray(payload.candidate_promotions)
      ? payload.candidate_promotions
      : [];
    const latestDryRun = dryRuns.length ? dryRuns[dryRuns.length - 1] : null;
    const pendingStatuses = new Set([
      "queued",
      "pending_manual_approval",
      "auto_approved",
      "blocked",
    ]);
    const pending = promotions.filter((item) => pendingStatuses.has(String(item.status || "")));
    const promoted = promotions.filter((item) => String(item.status || "") === "promoted");
    const latestExport = exports.length ? exports[exports.length - 1] : null;
    const mergePreviewStatus = latestDryRun
      ? latestDryRun.ok
        ? "ready"
        : "needs_review"
      : exports.length
        ? "pending"
        : "none";
    const rawSummary = String(latestDryRun?.summary || "");
    const mergePreviewSummary = rawSummary
      .replace(/Merge gate/gi, "Merge preview")
      .replace(/merge gate/gi, "merge preview");
    // isolate→verify→merge lineage, grouped by task_id (candidate_export + candidate_promotion both
    // carry task_id; the dry-run is batch-level, so "verified" is a batch signal, not per-task — the
    // UI labels it as such). Tasks without a task_id are skipped; the flat items[] stays as fallback.
    const byTask = new Map();
    for (const ex of exports) {
      const taskId = String(ex.task_id || "");
      if (!taskId) continue;
      const entry = byTask.get(taskId) || { task_id: taskId };
      entry.candidate_id = entry.candidate_id || ex.candidate_id;
      entry.isolated = {
        status: ex.export_status,
        files: Array.isArray(ex.changed_files) ? ex.changed_files.length : 0,
      };
      byTask.set(taskId, entry);
    }
    for (const pr of promotions) {
      const taskId = String(pr.task_id || "");
      if (!taskId) continue;
      const entry = byTask.get(taskId) || { task_id: taskId };
      entry.candidate_id = entry.candidate_id || pr.candidate_id;
      entry.merged = {
        status: pr.status,
        files:
          Array.isArray(pr.promoted_files) && pr.promoted_files.length
            ? pr.promoted_files.length
            : Array.isArray(pr.promotable_files)
              ? pr.promotable_files.length
              : 0,
        risky_files: Array.isArray(pr.merge_gate?.risky_files) ? pr.merge_gate.risky_files : [],
      };
      byTask.set(taskId, entry);
    }
    const batchVerified = latestDryRun ? { ok: Boolean(latestDryRun.ok), batch: true } : null;
    const lineages = [...byTask.values()]
      .slice(-8)
      .map((entry) => ({ ...entry, verified: batchVerified }));
    return {
      export_count: exports.length,
      dry_run_count: dryRuns.length,
      pending_promotions: pending.length,
      promoted_count: promoted.length,
      merge_preview_status: mergePreviewStatus,
      merge_preview_summary:
        mergePreviewSummary ||
        (exports.length ? "Candidate exports recorded; open Inspector for details." : ""),
      latest_export: latestExport,
      latest_dry_run: latestDryRun,
      lineages,
      items: [
        ...exports.slice(-6).map((item) => ({
          kind: "candidate_export",
          id: item.candidate_export_id,
          task_id: item.task_id,
          status: item.export_status,
          files: item.changed_files,
          execution_profile_id: item.execution_profile_id,
        })),
        ...dryRuns.slice(-3).map((item) => ({
          kind: "merge_preview",
          id: item.merge_gate_dry_run_id,
          ok: item.ok,
          summary: String(item.summary || "").replace(/Merge gate/gi, "Merge preview"),
          batch_violations: item.batch_violations,
        })),
        ...pending.slice(-6).map((item) => ({
          kind: "promotion_pending",
          id: item.promotion_id,
          task_id: item.task_id,
          status: item.status,
          files: item.promotable_files,
          // Risk is read ONLY from this same promotion record's own merge_gate (1:1, no cross-record
          // join). risk_level annotates; it never blocks. Empty risky_files => render no risk claim
          // (a hold can also be deletion-driven, a cause not recorded here).
          risky_files: Array.isArray(item.merge_gate?.risky_files)
            ? item.merge_gate.risky_files
            : [],
          risk_level: String(item.merge_gate?.risk_level || "low"),
        })),
      ],
      evidence_refs: [
        ...(exports.length ? ["candidate_exports.jsonl"] : []),
        ...(dryRuns.length ? ["merge_gate_dry_runs.jsonl"] : []),
        ...(promotions.length ? ["candidate_promotions.jsonl"] : []),
      ],
    };
  }

  async function buildWorkerTree(runDir, agentRunGraph = {}) {
    const workers = await readJsonlTail(path.join(runDir, "workers.jsonl"), 500);
    const results = await readJsonlTail(path.join(runDir, "worker_results.jsonl"), 500);
    const events = await readJsonlTail(path.join(runDir, "events.jsonl"), 500);
    const swarmPlans = await readJsonlTail(path.join(runDir, "swarm_execution_plans.jsonl"), 20);
    const resultByWorker = new Map(
      results.map((item) => [String(item.worker_invocation_id || ""), item]),
    );
    const nodes = new Map();
    for (const worker of workers) {
      const id = String(worker.worker_invocation_id || "");
      if (!id) continue;
      const result = resultByWorker.get(id) || {};
      nodes.set(id, {
        worker_invocation_id: id,
        worker_result_id: result.worker_result_id || null,
        parent_worker_invocation_id:
          worker.parent_worker_invocation_id || result.parent_worker_invocation_id || null,
        parent_task_id: worker.parent_task_id || null,
        worker_kind: worker.worker_kind || result.worker_kind || null,
        parallel_safety: worker.parallel_safety || null,
        child_plan_refs: Array.isArray(worker.child_plan_refs)
          ? worker.child_plan_refs
          : Array.isArray(result.child_plan_refs)
            ? result.child_plan_refs
            : [],
        task_id: worker.task_id || result.task_id || "task",
        agent_id: worker.agent_id || "agent",
        runtime_profile_id: worker.runtime_profile_id || "unknown",
        execution_profile_id: worker.execution_profile_id || null,
        spawn_kind: worker.spawn_kind || null,
        fake_path: worker.fake_path ?? null,
        scheduling_mode: worker.scheduling_mode || null,
        status: worker.status || "unknown",
        result_status: result.status || null,
        artifact_refs: Array.isArray(result.artifact_refs) ? result.artifact_refs : [],
        validation_refs: Array.isArray(result.validation_refs) ? result.validation_refs : [],
        failure_evidence_refs: Array.isArray(result.failure_evidence_refs)
          ? result.failure_evidence_refs
          : [],
        cost: result.cost || { model_calls: 0, tool_calls: 0 },
        summary: result.summary || worker.summary || "",
        children: [],
      });
    }
    const roots = [];
    const orphanWorkers = [];
    for (const node of nodes.values()) {
      const parentId = String(node.parent_worker_invocation_id || "");
      if (!parentId) {
        roots.push(node);
        continue;
      }
      const parent = nodes.get(parentId);
      if (!parent) {
        roots.push(node);
        orphanWorkers.push(node.worker_invocation_id);
        continue;
      }
      parent.children.push(node);
    }
    const statusCounts = {};
    for (const node of nodes.values()) {
      const status = String(node.result_status || node.status || "unknown");
      statusCounts[status] = (statusCounts[status] || 0) + 1;
    }
    return {
      total_workers: nodes.size,
      status_counts: statusCounts,
      successful_workers: statusCounts.succeeded || 0,
      failed_workers:
        (statusCounts.failed || 0) + (statusCounts.denied || 0) + (statusCounts.timeout || 0),
      parallel_batches: events.filter(
        (event) =>
          event.type === "task_graph_selection" &&
          ["readonly_batch_selection", "parallel_safe_batch_selection"].includes(
            String(event.data?.reason || ""),
          ),
      ).length,
      coordination_modes: [
        ...new Set(
          events
            .filter((event) => event.type === "task_graph_selection" && event.data?.reason)
            .map((event) => String(event.data.reason)),
        ),
      ],
      total_model_calls: [...nodes.values()].reduce(
        (total, node) => total + Number(node.cost?.model_calls || 0),
        0,
      ),
      total_tool_calls: [...nodes.values()].reduce(
        (total, node) => total + Number(node.cost?.tool_calls || 0),
        0,
      ),
      agent_run_graph: agentRunGraph || {},
      collaboration_summary: agentRunGraph?.collaboration_summary || {},
      swarm_execution_plans: swarmPlans,
      latest_swarm_plan: swarmPlans.length ? swarmPlans[swarmPlans.length - 1] : null,
      orphan_workers: orphanWorkers,
      roots,
    };
  }

  function mainActionForRun(payload, currentDecisions) {
    const pending = (currentDecisions || []).filter((decision) => decision?.status === "pending");
    if (pending.length) {
      return {
        kind: "decide",
        label: "Decide",
        next_command: "asteria decide --list-pending",
        requires_permission: false,
        status: "waiting_decision",
        decision_count: pending.length,
        source: "decisions.jsonl",
        evidence_refs: ["decisions.jsonl"],
      };
    }
    const finalSummary = payload.final_report_summary || {};
    const loopSummary = payload.run_loop_summary || {};
    const progress = payload.runtime_progress || {};
    // agent_loop_run_summary.recommended_command was an FSM projection RA7b deleted (never written
    // now); the spine's next-command chip resolves from runtime_progress / final_report_summary.
    const nextCommand = firstRuntimeText(
      progress.next_command,
      finalSummary.recommended_next_command,
      loopSummary.recommended_next_command,
      "",
    );
    if (!nextCommand) {
      // Guard against a false "Done": nextCommand also goes empty when the evidence files are
      // unreadable (readJson swallows a corrupt/half-written file to {}), not only when a run truly
      // finished. The run's own status is the source of truth for whether it actually ended — a
      // running / blocked / paused run must never be shown as "Done / idle" just because its summary
      // files were empty or failed to parse.
      const runStatus = String(
        (payload.run || {}).status ?? finalSummary.run_status ?? "",
      ).toLowerCase();
      if (/run|block|paus/.test(runStatus)) {
        const attention = /block|paus/.test(runStatus);
        return {
          kind: "continue",
          label: attention ? "Needs attention" : "In progress",
          next_command: "",
          requires_permission: false,
          status: runStatus,
          decision_count: 0,
          source: "run.status",
          evidence_refs: ["run.json"],
        };
      }
      return {
        kind: "done",
        label: "Done",
        next_command: "",
        requires_permission: false,
        status: "idle",
        decision_count: 0,
        source: "runtime_progress",
        evidence_refs: ["final_report_summary.json", "run_loop_summary.json"],
      };
    }
    const action = runtimeActionFor(nextCommand);
    return {
      kind: action?.kind || "continue",
      label: action?.label || "Continue",
      next_command: nextCommand,
      requires_permission: Boolean(action?.requiresPermission),
      status: action?.requiresPermission ? "needs_permission" : "ready",
      decision_count: 0,
      source: progress.next_command
        ? "runtime_progress.next_command"
        : "runtime_summary.recommended_next_command",
      evidence_refs: ["final_report_summary.json", "run_loop_summary.json"],
    };
  }

  function userProgressToRunDetailEvent(event, runId) {
    const mapped = userProgressToStudioEvent(event, "", runId);
    mapped.session_id = "";
    mapped.event_id = `run-detail-${runId}-${event.event_id || event.sequence || Date.now()}`;
    return mapped;
  }

  // B10-a context budget snapshot. The runtime already computes and persists a full per-task budget
  // (context_budget_snapshots.jsonl: estimated tokens vs the 200k window, the 0.75 compaction / 0.9
  // hard-stop thresholds, per-section token breakdown, dedupe savings, compaction boundary) — but none
  // of it was ever read, so the Inspector could not show how much context each task actually carried.
  // This projects it into a compact, glanceable summary: the LATEST snapshot (the current budget) plus
  // the PEAK pressure seen across the run (the moment closest to compaction). It is a pure surfacing of
  // existing evidence — no thresholds or verdicts are invented here.
  function buildContextBudget(rows) {
    const snapshots = (Array.isArray(rows) ? rows : []).filter(
      (row) => row && typeof row === "object",
    );
    if (!snapshots.length) return { available: false };
    const project = (row) => {
      const sections = row.sections && typeof row.sections === "object" ? row.sections : {};
      const topSections = Object.entries(sections)
        .map(([name, tokens]) => ({ name, tokens: Number(tokens) || 0 }))
        .sort((a, b) => b.tokens - a.tokens)
        .slice(0, 6);
      return {
        task_id: row.task_id ?? null,
        scope: row.scope ?? null,
        estimated_tokens: Number(row.estimated_tokens) || 0,
        window_tokens: Number(row.context_window_tokens) || 0,
        ratio: Number(row.context_window_ratio) || 0,
        pressure_status: String(row.pressure_status || "within_budget"),
        compaction_threshold: Number(row.compaction_threshold) || 0,
        hard_stop_threshold: Number(row.hard_stop_threshold) || 0,
        duplicate_estimated_tokens: Number(row.duplicate_estimated_tokens) || 0,
        duplicate_ref_count: Number(row.duplicate_ref_count) || 0,
        top_sections: topSections,
        compact_boundary:
          row.compact_boundary && typeof row.compact_boundary === "object"
            ? {
                status: String(row.compact_boundary.status || ""),
                recommended_action: String(row.compact_boundary.recommended_action || ""),
                estimated_tokens_delta: Number(row.compact_boundary.estimated_tokens_delta) || 0,
              }
            : null,
      };
    };
    const projected = snapshots.map(project);
    const peak = projected.reduce((worst, cur) => (cur.ratio > worst.ratio ? cur : worst));
    return {
      available: true,
      count: projected.length,
      latest: projected[projected.length - 1],
      peak,
      snapshots: projected,
      evidence_refs: ["context_budget_snapshots.jsonl"],
    };
  }

  async function listRunEvidenceFiles(runDir, runId) {
    let entries = [];
    try {
      entries = await fs.readdir(runDir, { withFileTypes: true });
    } catch {
      return [];
    }
    const files = [];
    for (const entry of entries) {
      if (!entry.isFile()) continue;
      const relative = `.asteria/runs/${runId}/${entry.name}`;
      if (!isSafeWorkspacePath(relative) || !isPreviewableFile(relative)) continue;
      const stat = await fs.stat(path.join(runDir, entry.name));
      files.push({ path: relative, size: stat.size, modified_at: stat.mtime.toISOString() });
    }
    return files.sort((a, b) => String(a.path).localeCompare(String(b.path)));
  }

  async function readRunDetail(runId) {
    if (!isSafeId(runId)) return { ok: false, error: "invalid run id" };
    const runsDir = path.join(getWorkspace(), ".asteria", "runs");
    const runDir = path.resolve(runsDir, runId);
    if (!runDir.startsWith(runsDir) || !existsSync(runDir))
      return { ok: false, error: "run not found" };
    const jsonFiles = {
      run: "run.json",
      cost_report: "cost_report.json",
      goal_spec: "goal_spec.json",
      task_plan: "task_plan.json",
      task_plan_eval: "task_plan_eval.json",
      agent_run_graph: "agent_run_graph.json",
      agent_loop_run_summary: "agent_loop_run_summary.json",
      run_loop_summary: "run_loop_summary.json",
      final_report_summary: "final_report_summary.json",
      model_route_timeline: "model_route_timeline.json",
      // The model's OWN todo list (todo_write). task_plan is what the planner laid out up front;
      // this is how the model actually organized the work as it went — and it was written but never
      // read here, so the checklist could only ever show the static plan.
      model_todos: "model_todos.json",
    };
    const payload = { ok: true, run_id: runId };
    for (const [key, file] of Object.entries(jsonFiles)) {
      payload[key] = redact(await readJson(path.join(runDir, file)));
    }
    payload.runtime_progress = redact(
      payload.final_report_summary?.runtime_progress ||
        payload.run_loop_summary?.runtime_progress ||
        {},
    );
    payload.model_calls = redact(await readJsonlTail(path.join(runDir, "model_calls.jsonl"), 120));
    payload.task_execution_evidence = redact(
      await readJsonlTail(path.join(runDir, "task_execution_evidence.jsonl"), 80),
    );
    payload.worker_results = redact(
      await readJsonlTail(path.join(runDir, "worker_results.jsonl"), 80),
    );
    payload.validation_results = redact(
      await readJsonlTail(path.join(runDir, "validation_results.jsonl"), 80),
    );
    payload.mcp_invocations = redact(
      await readJsonlTail(path.join(runDir, "mcp_invocations.jsonl"), 80),
    );
    payload.skill_invocations = redact(
      await readJsonlTail(path.join(runDir, "skill_invocations.jsonl"), 80),
    );
    // capability_decisions.jsonl was written by the runtime but never read here (have-write-no-read);
    // surface it so the Inspector can show why each tool/MCP/skill capability was allowed or denied.
    payload.capability_decisions = redact(
      await readJsonlTail(path.join(runDir, "capability_decisions.jsonl"), 80),
    );
    // runtime_hooks.jsonl: same have-write-no-read gap. The control hooks are what nudge the model
    // (turn_start) and hold the loop open when an expected artifact is missing (pre_final) — the
    // reason a run sometimes takes more rounds than it said it would. The main thread shows only the
    // held-open ones; the full hook trail belongs here, as evidence.
    payload.runtime_hooks = redact(
      await readJsonlTail(path.join(runDir, "runtime_hooks.jsonl"), 120),
    );
    const runtimeRequests = await readJsonlTail(path.join(runDir, "runtime_requests.jsonl"), 120);
    const decisions = await readJsonlTail(path.join(runDir, "decisions.jsonl"), 120);
    const currentDecisions = latestDecisions(decisions).map((decision) =>
      enrichRuntimeRequestDecision(decision, runtimeRequests),
    );
    payload.runtime_requests = redact(runtimeRequests);
    payload.decision_requests = redact(
      currentDecisions.filter((decision) => decision?.status === "pending"),
    );
    payload.decisions = redact(currentDecisions);
    payload.decision_history = redact(decisions);
    payload.main_action = redact(mainActionForRun(payload, currentDecisions));
    payload.candidate_exports = redact(
      await readJsonlTail(path.join(runDir, "candidate_exports.jsonl"), 80),
    );
    payload.merge_gate_dry_runs = redact(
      await readJsonlTail(path.join(runDir, "merge_gate_dry_runs.jsonl"), 40),
    );
    payload.candidate_promotions = redact(
      await readJsonlTail(path.join(runDir, "candidate_promotions.jsonl"), 80),
    );
    payload.promotion_preview = redact(buildPromotionPreview(payload));
    payload.worker_tree = redact(await buildWorkerTree(runDir, payload.agent_run_graph || {}));
    payload.context_budget = redact(
      buildContextBudget(
        await readJsonlTail(path.join(runDir, "context_budget_snapshots.jsonl"), 80),
      ),
    );
    const workflowStateRows = await readJsonlTail(
      path.join(runDir, "orchestration_runner_state.jsonl"),
      120,
    );
    payload.orchestration_workflow = redact(buildOrchestrationWorkflowMonitor(workflowStateRows));
    payload.runtime_progress = redact(
      enrichRuntimeProgress(payload.runtime_progress || {}, payload),
    );
    // 500 (not 120) to match the thread's own event read (readRuntimeUserProgressEvents). user_progress
    // is ~85% inspector rows, so a 120-physical-line tail kept only ~18 user-facing events and dropped a
    // run's whole opening (goal → plan → first steps) — the "process" the user wants to see. 500 keeps a
    // typical run's full arc while staying bounded for very long runs.
    const userProgress = await readJsonlTail(path.join(runDir, "user_progress.jsonl"), 500);
    const legacyEvents = await readJsonlTail(path.join(runDir, "events.jsonl"), 120);
    payload.user_progress = redact(userProgress);
    payload.raw_evidence = redact({
      legacy_events: legacyEvents,
      model_calls: payload.model_calls,
      task_execution_evidence: payload.task_execution_evidence,
      worker_results: payload.worker_results,
      validation_results: payload.validation_results,
      mcp_invocations: payload.mcp_invocations,
      skill_invocations: payload.skill_invocations,
      runtime_requests: payload.runtime_requests,
    });
    payload.legacy_events = redact(legacyEvents);
    payload.timeline_events_source = userProgress.length ? "user_progress" : "events";
    payload.timeline_default = userProgress.length ? "user_progress" : "legacy_events_fallback";
    payload.inspector_raw_evidence_source = "raw_evidence";
    payload.events = redact(
      userProgress.length
        ? userProgress.map((event) => userProgressToRunDetailEvent(event, runId)).filter(Boolean)
        : legacyEvents,
    );
    payload.files = await listRunEvidenceFiles(runDir, runId);
    return redact(payload);
  }

  return {
    readRunDetail,
    runtimeActionFor,
    runtimeActionByKind,
    userProgressToStudioEvent,
    permissionPreview,
  };
}
