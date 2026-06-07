import React from "react";
import { Loader2, Terminal } from "lucide-react";
import type { NarrativeStep as NarrativeStepType } from "../../types";
import { extractFileChangesFromSteps, aggregateFileChangeStats } from "../../fileChanges";
import { AggregateDiffChip } from "../../components/AggregateDiffChip";
import { FileChangeChips } from "../../components/FileChangeChips";
import { PermissionCard } from "../../components/PermissionCard";
import { ClampedOutput } from "../../components/ClampedOutput";

const PHASE_LABELS: Record<string, string> = {
  thinking: "Thinking",
  plan: "Planning",
  tool: "Using tools",
  result: "Preparing result",
  verification: "Verifying",
  repair: "Repairing",
  error: "Error",
};

export type LiveStreamProps = {
  steps: NarrativeStepType[];
  onPermit: (jobId: string, action: "allow" | "deny") => Promise<void>;
  onFileChangeClick?: (path: string) => void;
  /** Focus mode hides stdout/model streams; chips + permission remain visible. */
  showToolStreams?: boolean;
  compactDiff?: boolean;
  turnIndex?: number;
  onAggregateDiffClick?: (turnIndex: number) => void;
};

export function LiveStream({
  steps,
  onPermit,
  onFileChangeClick,
  showToolStreams = true,
  compactDiff = false,
  turnIndex,
  onAggregateDiffClick,
}: LiveStreamProps) {
  const activeStep = steps.at(-1);
  const phaseLabel = activeStep ? (PHASE_LABELS[activeStep.kind] ?? activeStep.label) : "Processing";
  const isWaiting = activeStep?.status === "waiting_user";
  const modelText = steps
    .filter((step) => step.kind === "thinking" || step.kind === "plan" || step.kind === "verification")
    .map((step) => {
      const event = step.events[0];
      if (event?.type?.startsWith("model_") && event.phase !== "chat") {
        return event.status === "running"
          ? "Model is drafting structured output. The readable plan will appear when validation finishes."
          : "Model output captured; preparing a readable result.";
      }
      return event?.content_delta || step.summary || "";
    })
    .filter(Boolean)
    .join("\n\n");
  const toolSteps = steps.filter((step) => step.kind === "tool" || step.kind === "repair");
  const fileChanges = extractFileChangesFromSteps(steps);
  const fileStats = aggregateFileChangeStats(fileChanges);
  const toolOutputs = showToolStreams
    ? toolSteps
      .flatMap((step) => step.events.map((event) => ({ id: step.id, text: event.content_delta, cmd: event.command })))
      .filter((output) => output.text)
    : [];
  const permEvent = steps
    .flatMap((step) => step.events)
    .find((event) => event.type === "permission_request" && event.status === "waiting_user" && event.job_id);

  return (
    <div className="liveStream">
      <div className="livePhaseRow">
        {isWaiting ? <span className="livePhaseDot waiting" /> : <Loader2 size={13} className="spinning liveSpinner" />}
        <span className="livePhaseLabel">{phaseLabel}</span>
        {activeStep?.title && activeStep.title !== phaseLabel && (
          <span className="livePhaseTitle">{activeStep.title}</span>
        )}
      </div>

      {toolSteps.length > 0 && (
        <div className="liveToolRow">
          {toolSteps.map((step) => {
            const cmd = step.events[0]?.command;
            const cmdStr = Array.isArray(cmd) ? cmd.slice(0, 4).join(" ") : "";
            const label = step.title || (cmdStr ? cmdStr.slice(0, 48) : step.label);
            return (
              <span key={step.id} className={`liveToolChip ${step.status}`} title={cmdStr || undefined}>
                <Terminal size={10} />
                {label}
              </span>
            );
          })}
        </div>
      )}

      {showToolStreams && toolOutputs.length > 0 && (
        <div className="liveToolOutputs">
          {toolOutputs.map((output, index) => (
            <ClampedOutput key={index} text={String(output.text ?? "")} className="liveToolOutput" maxLines={4} />
          ))}
        </div>
      )}

      {compactDiff ? (
        <AggregateDiffChip
          files={fileStats.files}
          additions={fileStats.additions}
          deletions={fileStats.deletions}
          onClick={turnIndex && onAggregateDiffClick ? () => onAggregateDiffClick(turnIndex) : undefined}
        />
      ) : (
        <FileChangeChips changes={fileChanges} onSelect={onFileChangeClick} />
      )}

      {showToolStreams && modelText && (
        <ClampedOutput text={modelText} className="liveModelText" maxLines={6} />
      )}

      {permEvent && (
        <PermissionCard
          event={permEvent}
          onAllow={() => onPermit(permEvent.job_id!, "allow")}
          onDeny={() => onPermit(permEvent.job_id!, "deny")}
        />
      )}
    </div>
  );
}
