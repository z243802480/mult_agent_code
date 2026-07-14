import React from "react";
import { Loader2 } from "lucide-react";
import type { NarrativeStep as NarrativeStepType } from "../../types";
import { extractFileChangesFromSteps, aggregateFileChangeStats } from "../../fileChanges";
import { AggregateDiffChip } from "../../components/AggregateDiffChip";
import { FileChangeChips } from "../../components/FileChangeChips";
import { PermissionCard } from "../../components/PermissionCard";
import { ClampedOutput } from "../../components/ClampedOutput";
import { ToolCallCard } from "./ToolCallCard";
import { cleanReasoning, THINKING_PLACEHOLDERS, dedupeAdjacentToolSteps } from "../../narrative";
import type { StudioViewMode } from "../../hooks/useViewMode";

// Main-thread, user-facing phase copy. Keys are step kinds; unknown kinds fall back
// to the step's own label. Keep this plain and human — no internal phase vocabulary.
const PHASE_LABELS: Record<string, string> = {
  thinking: "思考中",
  plan: "规划中",
  tool: "执行中",
  result: "结果",
  verification: "核对结果",
  repair: "执行中",
  error: "出错",
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
  viewMode?: StudioViewMode;
};

export function LiveStream({
  steps,
  onPermit,
  onFileChangeClick,
  showToolStreams = true,
  compactDiff = false,
  turnIndex,
  onAggregateDiffClick,
  viewMode = "focus",
}: LiveStreamProps) {
  const expandOutput = viewMode === "verbose";
  const activeStep = steps.at(-1);
  const phaseLabel = activeStep ? (PHASE_LABELS[activeStep.kind] ?? activeStep.label) : "处理中";
  const isWaiting = activeStep?.status === "waiting_user";
  const modelText = cleanReasoning(
    steps
      .filter(
        (step) => step.kind === "thinking" || step.kind === "plan" || step.kind === "verification",
      )
      .map((step) => {
        // Render the real streamed model delta for every phase. Join ALL of the step's events (the
        // delta is accumulated phase-agnostically in narrative.toNarrativeEvents) rather than only the
        // first, then fall back to the step summary when there is no streamed prose.
        const joined = cleanReasoning(step.events.map((e) => e.content_delta || "").join(""));
        return (joined || step.summary || "").trim();
      })
      // Drop harness placeholders ("Asteria is preparing the next step.") so the live stream shows the
      // model's real words or nothing — never machine status text impersonating reasoning (ADR-0021).
      .filter((text) => text && !THINKING_PLACEHOLDERS.has(text))
      .join("\n\n"),
  );
  // A pending job-based permission ask classifies as kind "tool" (it IS actionable), but it renders as
  // its own PermissionCard (below) — it must NOT also render as a ToolCallCard, which would leak the
  // raw runtime command it carries ("python -m asteria_runtime run …") into the live stream. Exclude
  // those steps from the tool cards, mirroring the completed-turn TurnMiddle (permIds) exclusion.
  const isPendingPermissionStep = (step: NarrativeStepType) =>
    step.events.some(
      (event) =>
        event.type === "permission_request" && event.status === "waiting_user" && event.job_id,
    );
  const toolSteps = dedupeAdjacentToolSteps(
    steps.filter(
      (step) =>
        !isPendingPermissionStep(step) &&
        (step.kind === "tool" ||
          step.kind === "repair" ||
          step.kind === "subagent" ||
          // Held-open guardrail: shown WHILE the run is live, so the extra rounds have a reason on
          // screen as they happen — not only in hindsight after the turn closes.
          step.kind === "guardrail"),
    ),
  );
  const fileChanges = extractFileChangesFromSteps(steps);
  const fileStats = aggregateFileChangeStats(fileChanges);
  const permEvent = steps
    .flatMap((step) => step.events)
    .find(
      (event) =>
        event.type === "permission_request" && event.status === "waiting_user" && event.job_id,
    );

  return (
    <div className="liveStream">
      <div className="livePhaseRow">
        {isWaiting ? (
          <span className="livePhaseDot waiting" />
        ) : (
          <Loader2 size={13} className="spinning liveSpinner" />
        )}
        <span className="livePhaseLabel">{phaseLabel}</span>
        {activeStep?.title && activeStep.title !== phaseLabel && (
          <span className="livePhaseTitle">{activeStep.title}</span>
        )}
      </div>

      {toolSteps.length > 0 && (
        <div className="liveToolCards">
          {toolSteps.map((step) => (
            <ToolCallCard key={step.id} step={step} showOutput={showToolStreams} />
          ))}
        </div>
      )}

      {compactDiff ? (
        <AggregateDiffChip
          files={fileStats.files}
          additions={fileStats.additions}
          deletions={fileStats.deletions}
          onClick={
            turnIndex && onAggregateDiffClick ? () => onAggregateDiffClick(turnIndex) : undefined
          }
        />
      ) : (
        <FileChangeChips changes={fileChanges} onSelect={onFileChangeClick} />
      )}

      {showToolStreams && modelText && (
        <div className="streamTextWrap">
          <ClampedOutput
            text={modelText}
            className="liveModelText"
            maxLines={8}
            defaultExpanded={expandOutput}
          />
          <span className="streamCaret" aria-hidden="true" />
        </div>
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
