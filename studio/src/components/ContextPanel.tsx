import React from "react";
import { ChevronDown, ChevronRight, CircleDot } from "lucide-react";
import type { RunDetailPayload } from "../types";
import {
  contextBudgetSnapshot,
  contextHealth,
  contextWindowSummary,
  formatUsage,
  percent,
  type ContextBudgetSnapshot,
  type ContextSection,
} from "../contextSummary";

export function ContextPanel({
  runDetail,
  isRunning,
  selectedSectionId,
  onSelectSection,
  onCompact,
  compacting,
}: {
  runDetail: RunDetailPayload | null;
  isRunning: boolean;
  selectedSectionId?: string | null;
  onSelectSection?: (sectionId: string) => void;
  onCompact?: () => void;
  compacting?: boolean;
}) {
  const summary = contextWindowSummary(runDetail);
  const budget = contextBudgetSnapshot(runDetail);
  const [open, setOpen] = React.useState(false);

  // Render when EITHER source has data. The budget snapshot is independent evidence: a run can persist
  // context_budget_snapshots.jsonl without the run-level cost_report rollup the usage bar reads, and it
  // must still surface (otherwise B10-a would vanish exactly on the runs the rollup missed).
  if (!summary && !budget) return null;
  const health = summary ? contextHealth(summary.ratio) : "good";
  const showPressureBar = Boolean(summary && (summary.ratio >= 0.75 || health !== "good"));

  return (
    <div className={`contextPanel ${showPressureBar ? "pressure-visible" : ""}`}>
      {summary && showPressureBar && (
        <div className={`contextPressureBar health-${health}`} role="status">
          <CircleDot size={12} />
          <span>上下文 {percent(summary.ratio)}</span>
          <strong>{summary.status || health}</strong>
          {onCompact && summary.ratio >= 0.75 && (
            <button
              type="button"
              className="contextCompactButton"
              disabled={compacting || isRunning}
              onClick={onCompact}
            >
              压缩
            </button>
          )}
        </div>
      )}
      {budget && <ContextBudgetBlock budget={budget} />}
      {summary && (
        <button
          type="button"
          className="contextPanelToggle"
          onClick={() => setOpen((value) => !value)}
        >
          {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
          <span>上下文用量</span>
          <strong>
            {formatUsage(summary.used)}
            {summary.capacity ? ` / ${formatUsage(summary.capacity)}` : ""}
          </strong>
          <em>{percent(summary.ratio)}</em>
        </button>
      )}
      {summary && open && (
        <div className="contextPanelBody">
          <div className="contextUsageBar large">
            <span style={{ width: percent(summary.ratio) }} className={`health-${health}`} />
          </div>
          <div className="contextBreakdown full">
            {summary.sections.map((section) => (
              <ContextSectionRow
                key={section.id}
                section={section}
                active={selectedSectionId === section.id}
                onSelect={onSelectSection}
              />
            ))}
            {!summary.sections.length && <p className="muted">本次运行暂无分区明细记录。</p>}
          </div>
        </div>
      )}
    </div>
  );
}

// B10-a: the per-task budget snapshot the runtime measured — the dedupe savings and compaction
// boundary the run-level usage bar above cannot show. Rendered only when it carries something
// actionable (duplicated context to reclaim, a compaction the runtime recommends, or a peak that
// crossed the compaction threshold); silent otherwise so a healthy run stays quiet.
function ContextBudgetBlock({ budget }: { budget: ContextBudgetSnapshot }) {
  const health = contextHealth(budget.ratio);
  const hasDupes = budget.duplicateRefs > 0 && budget.duplicateTokens > 0;
  const recommendsCompaction =
    budget.compaction != null &&
    budget.compaction.status !== "not_required" &&
    budget.compaction.action !== "continue";
  const peakNotable =
    budget.peak != null &&
    budget.peak.ratio >= budget.compactionThreshold &&
    budget.compactionThreshold > 0;
  if (!hasDupes && !recommendsCompaction && !peakNotable) return null;
  return (
    <div className="contextBudgetSnapshot" role="group" aria-label="上下文预算快照">
      <div className="contextBudgetHeader">
        <span>预算快照</span>
        <strong className={`health-${health}`}>{formatUsage(budget.estimatedTokens)} tokens</strong>
        {budget.taskCount > 1 && <em>{budget.taskCount} 个任务</em>}
      </div>
      <div className="contextBudgetFacts">
        {hasDupes && (
          <span className="contextBudgetFact" title="重复内容：压缩/去重可回收的上下文">
            {budget.duplicateRefs} 处重复 · 去重可省 ~{formatUsage(budget.duplicateTokens)}
          </span>
        )}
        {recommendsCompaction && budget.compaction && (
          <span className="contextBudgetFact warn" title="运行时给出的压缩建议">
            建议压缩 · 约可释放 ~{formatUsage(Math.abs(budget.compaction.delta))}
          </span>
        )}
        {peakNotable && budget.peak && (
          <span className="contextBudgetFact" title="本次运行的上下文压力峰值">
            峰值 {percent(budget.peak.ratio)}
            {budget.peak.taskId ? ` · ${budget.peak.taskId}` : ""}
          </span>
        )}
      </div>
    </div>
  );
}

function ContextSectionRow({
  section,
  active,
  onSelect,
}: {
  section: ContextSection;
  active: boolean;
  onSelect?: (sectionId: string) => void;
}) {
  const clickable = Boolean(onSelect);
  return (
    <button
      type="button"
      className={active ? "contextBreakdownRow active" : "contextBreakdownRow"}
      disabled={!clickable}
      onClick={() => onSelect?.(section.id)}
    >
      <span>{section.label}</span>
      <strong>{formatUsage(section.value)}</strong>
      <em>{percent(section.ratio)}</em>
    </button>
  );
}
