import React from "react";
import { ChevronDown, ChevronRight, CircleDot } from "lucide-react";
import type { RunDetailPayload } from "../types";
import {
  contextHealth,
  contextWindowSummary,
  formatUsage,
  percent,
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
  const [open, setOpen] = React.useState(false);

  if (!summary) return null;
  const health = contextHealth(summary.ratio);
  const showPressureBar = summary.ratio >= 0.75 || health !== "good";

  return (
    <div className={`contextPanel ${showPressureBar ? "pressure-visible" : ""}`}>
      {showPressureBar && (
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
      {open && (
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
