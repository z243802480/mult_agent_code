import React, { useState } from "react";
import type { StudioEvent } from "../../types";

// Sub-agent status monitor (ADR-0023 · learns from Claude Code's agents panel): a right-side view of
// the expert sub-agents the lead delegated to, grouped by state, each drillable into its own process.
// The lead's main thread shows only the returned summary (Part B4); the expert's detailed work lives
// here — isolated evidence, not the lead's conversation.

type ExpertStatus = "running" | "failed" | "done";

interface ExpertRow {
  childTaskId: string;
  role: string;
  status: ExpertStatus;
  statusLine: string;
  iterations?: number;
  transcript: StudioEvent[];
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : {};
}

// The batch-level merge-gate reconciliation for concurrent isolated writes (ADR-0023 B1-b). This
// card is NOT tied to one child (it summarizes the whole write fan-out), so it is surfaced as a
// panel banner rather than an expert row: how many disjoint writes were promoted into the shared
// workspace, or that a cross-write conflict blocked the batch (nothing promoted).
export interface MergeReconciliation {
  ok: boolean;
  summary: string;
  promotedFiles: number;
}

export function buildReconciliation(events: StudioEvent[]): MergeReconciliation | null {
  let result: MergeReconciliation | null = null;
  for (const event of events) {
    if (event.transcript_kind !== "subagent_summary") continue;
    const data = asRecord(event.data);
    if (String(data.subagent_phase ?? "") !== "merge_gate") continue;
    // Last reconciliation wins (a run can fan out writers more than once).
    result = {
      ok: data.ok !== false,
      summary: String(event.summary ?? ""),
      promotedFiles: typeof data.promoted_files === "number" ? (data.promoted_files as number) : 0,
    };
  }
  return result;
}

export function buildExpertRows(events: StudioEvent[]): ExpertRow[] {
  const order: string[] = [];
  const byChild = new Map<string, ExpertRow>();

  // Pass 1: the dispatch + result cards (main thread) define each expert and its status.
  for (const event of events) {
    if (event.transcript_kind !== "subagent_summary") continue;
    const data = asRecord(event.data);
    const childId = String(data.child_task_id ?? "");
    if (!childId) continue;
    let row = byChild.get(childId);
    if (!row) {
      row = { childTaskId: childId, role: String(data.subagent_role ?? "expert"), status: "running", statusLine: "", transcript: [] };
      byChild.set(childId, row);
      order.push(childId);
    }
    row.role = String(data.subagent_role ?? row.role);
    const phase = String(data.subagent_phase ?? "");
    if (phase === "dispatch") {
      if (!row.statusLine) row.statusLine = String(event.summary ?? "");
    } else if (phase === "result") {
      row.statusLine = String(event.summary ?? row.statusLine);
      if (typeof data.iterations === "number") row.iterations = data.iterations;
      row.status = data.ok === false ? "failed" : "done";
    }
  }

  // Pass 2: the expert's own transcript — its narration + tool observations ride the Inspector tagged
  // with subagent_role and its child task id (data.task_id === childTaskId). Drill-down shows these.
  for (const event of events) {
    if (event.transcript_kind === "subagent_summary") continue;
    const data = asRecord(event.data);
    if (!data.subagent_role) continue;
    const row = byChild.get(String(data.task_id ?? ""));
    if (row) row.transcript.push(event);
  }

  return order.map((id) => byChild.get(id)!).filter(Boolean);
}

const STATUS_GROUPS: { status: ExpertStatus; label: string; className: string }[] = [
  { status: "running", label: "运行中", className: "isRunning" },
  { status: "failed", label: "未完成", className: "isFailed" },
  { status: "done", label: "已完成", className: "isDone" },
];

export function SubagentPanel({ events }: { events: StudioEvent[] }) {
  const experts = buildExpertRows(events);
  const reconciliation = buildReconciliation(events);
  const [openId, setOpenId] = useState<string | null>(null);

  if (experts.length === 0) {
    return (
      <div className="subagentPanel subagentEmpty">
        <div className="subagentEmptyTitle">本次运行还没有委派子 agent。</div>
        <div className="subagentEmptyHint">
          当主 agent 把子任务交给专家（reviewer / coder / researcher…）时，这里会显示每个专家的状态，
          点开可以看它自己的过程。
        </div>
      </div>
    );
  }

  const running = experts.filter((e) => e.status === "running").length;

  return (
    <div className="subagentPanel">
      {reconciliation && (
        <div className={`subagentMerge ${reconciliation.ok ? "isOk" : "isBlocked"}`}>
          <span className="subagentMergeDot" aria-hidden />
          <span className="subagentMergeText" title={reconciliation.summary}>
            {reconciliation.summary}
          </span>
        </div>
      )}
      <div className="subagentSummaryLine">
        {experts.length} 个子 agent · {running} 运行中 · {experts.length - running} 已结束
      </div>
      {STATUS_GROUPS.map((group) => {
        const rows = experts.filter((e) => e.status === group.status);
        if (!rows.length) return null;
        return (
          <div key={group.status} className={`subagentGroup ${group.className}`}>
            <div className="subagentGroupLabel">
              {group.label} <span className="subagentGroupCount">{rows.length}</span>
            </div>
            {rows.map((row) => {
              const open = openId === row.childTaskId;
              return (
                <div key={row.childTaskId} className="subagentRow">
                  <button
                    type="button"
                    className="subagentRowHead"
                    aria-expanded={open}
                    onClick={() => setOpenId(open ? null : row.childTaskId)}
                  >
                    <span className={`subagentDot ${group.className}`} aria-hidden />
                    <span className="subagentRole">{row.role}</span>
                    <span className="subagentStatusText" title={row.statusLine}>
                      {row.statusLine || "…"}
                    </span>
                    {typeof row.iterations === "number" && (
                      <span className="subagentIters">{row.iterations} 步</span>
                    )}
                    <span className="subagentChevron">{open ? "▾" : "▸"}</span>
                  </button>
                  {open && (
                    <div className="subagentDrill">
                      {row.transcript.length === 0 ? (
                        <div className="subagentDrillEmpty">该子 agent 暂无可展开的过程记录。</div>
                      ) : (
                        row.transcript.map((event, index) => (
                          <div key={event.event_id ?? index} className="subagentStep">
                            {event.title && <span className="subagentStepTitle">{event.title}</span>}
                            <span className="subagentStepSummary">{event.summary}</span>
                          </div>
                        ))
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        );
      })}
    </div>
  );
}
