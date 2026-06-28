import React, { useState } from "react";
import { ChevronDown, ChevronRight, Terminal } from "lucide-react";
import type { NarrativeStep as NarrativeStepType } from "../../types";
import { ClampedOutput } from "../../components/ClampedOutput";

const TOOL_STATUS_LABEL: Record<string, string> = {
  running: "running",
  completed: "done",
  failed: "failed",
  blocked: "blocked",
  waiting_user: "waiting",
};

/**
 * Inline collapsible tool card (Codex / Claude Code disclosure pattern): the header is the
 * tool_use (command + status); the body is the tool_result, default-collapsed and clamped.
 * Full/raw stdout stays in the Inspector (settled NarrativeStep selection) — we never dump the
 * whole output inline. Honest: when nothing was recorded the card simply isn't expandable.
 */
export function ToolCallCard({ step, showOutput = true }: {
  step: NarrativeStepType;
  showOutput?: boolean;
}) {
  const command = step.events[0]?.command;
  const cmdStr = Array.isArray(command) ? command.join(" ") : String(command ?? "");
  const label = step.title || (cmdStr ? cmdStr.slice(0, 72) : step.label);
  // tool_result: the recorded output deltas for this tool step, clamped on display.
  const output = step.events.map((event) => event.content_delta || "").join("").trim();
  const hasOutput = Boolean(showOutput && output);
  const [open, setOpen] = useState(false);
  const status = String(step.status ?? "");
  const statusLabel = TOOL_STATUS_LABEL[status] ?? status;

  return (
    <div className={`toolCard ${status}`}>
      <button
        type="button"
        className="toolCardHeader"
        onClick={hasOutput ? () => setOpen((value) => !value) : undefined}
        data-static={hasOutput ? undefined : "true"}
        title={cmdStr || undefined}
      >
        {hasOutput
          ? (open ? <ChevronDown size={12} /> : <ChevronRight size={12} />)
          : <span className="toolCardChevronSpacer" aria-hidden="true" />}
        <Terminal size={11} />
        <span className="toolCardLabel">{label}</span>
        {statusLabel && <span className={`toolCardStatus ${status}`}>{statusLabel}</span>}
      </button>
      {hasOutput && open && (
        <ClampedOutput text={output} className="toolCardOutput" maxLines={10} />
      )}
    </div>
  );
}
