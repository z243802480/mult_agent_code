import React, { useState } from "react";
import { ChevronRight, Terminal } from "lucide-react";
import type { NarrativeStep as NarrativeStepType } from "../../types";
import { ClampedOutput } from "../../components/ClampedOutput";

const TOOL_STATUS_LABEL: Record<string, string> = {
  running: "运行中",
  queued: "排队中",
  completed: "完成",
  failed: "失败",
  blocked: "阻塞",
  waiting_user: "等待中",
};

/**
 * The tool step's inline-displayable output. Streamed deltas (content_delta) win when present — that
 * is the live token stream. When a tool streamed nothing (shell/test tools don't), fall back to the
 * captured stdout/stderr the runtime already persisted on the tool_result event's `data` (see
 * command_tools.py: RunCommandTool / RunTestsTool write data.stdout/stderr, already truncated). This
 * is what let a completed `$ pytest` show only "完成" on the thread — the result was in the event all
 * along, just never read. Full/raw output still lives in the Inspector; this surfaces the recorded
 * excerpt so the common case doesn't need a detour.
 */
export function toolResultOutput(step: NarrativeStepType): string {
  const streamed = step.events
    .map((event) => event.content_delta || "")
    .join("")
    .trim();
  if (streamed) return streamed;
  for (const event of step.events) {
    const data = (event.data ?? {}) as Record<string, unknown>;
    const stdout = typeof data.stdout === "string" ? data.stdout.trim() : "";
    const stderr = typeof data.stderr === "string" ? data.stderr.trim() : "";
    if (!stdout && !stderr) continue;
    const parts: string[] = [];
    if (stdout) parts.push(stdout);
    if (stderr) parts.push(`stderr:\n${stderr}`);
    if (data.stdout_truncated === true || data.stderr_truncated === true) {
      parts.push("…（输出已截断，完整见 Inspector）");
    }
    return parts.join("\n\n");
  }
  return "";
}

/**
 * Inline collapsible tool card (Codex / Claude Code disclosure pattern): the header is the
 * tool_use (command + status); the body is the tool_result, default-collapsed and clamped.
 * Full/raw stdout stays in the Inspector (settled NarrativeStep selection) — we never dump the
 * whole output inline. Honest: when nothing was recorded the card simply isn't expandable.
 */
export function ToolCallCard({
  step,
  showOutput = true,
}: {
  step: NarrativeStepType;
  showOutput?: boolean;
}) {
  const command = step.events[0]?.command;
  const cmdStr = Array.isArray(command) ? command.join(" ") : String(command ?? "");
  const label = step.title || (cmdStr ? cmdStr.slice(0, 72) : step.label);
  // Streamed deltas, or the shell tool's captured stdout/stderr when it streamed nothing.
  const output = toolResultOutput(step);
  const hasOutput = Boolean(showOutput && output);
  const [open, setOpen] = useState(false);
  const status = String(step.status ?? "");
  // Map to a Chinese label; an unmapped/unknown status shows nothing rather than leaking the raw
  // English enum ("queued"/"cancelled"/…) into the thread (statusLabel is gated on truthiness below).
  const statusLabel = TOOL_STATUS_LABEL[status] ?? "";

  return (
    <div className={`toolCard ${status}`}>
      <button
        type="button"
        className="toolCardHeader"
        onClick={hasOutput ? () => setOpen((value) => !value) : undefined}
        data-static={hasOutput ? undefined : "true"}
        title={cmdStr || undefined}
      >
        {hasOutput ? (
          <ChevronRight size={12} className={`chevron ${open ? "open" : ""}`} />
        ) : (
          <span className="toolCardChevronSpacer" aria-hidden="true" />
        )}
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
