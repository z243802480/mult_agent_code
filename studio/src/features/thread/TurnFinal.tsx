import React from "react";
import type { NarrativeStep as NarrativeStepType } from "../../types";
import { MarkdownBody } from "../../components/MarkdownBody";
import { turnModelMetadata } from "./turnHelpers";

export function TurnFinal({ step, middleSteps }: { step: NarrativeStepType; middleSteps: NarrativeStepType[]; }) {
  const event = step.events[0];
  const text = event?.content_delta || step.summary || step.title || "";
  const isError = step.kind === "error" || step.status === "failed";
  const visibleText = stripContextNoise(text);
  const modelMeta = turnModelMetadata(middleSteps, step);
  const { lead, details } = splitLeadAndDetails(visibleText);
  const leadText = lead
    || (isError
      ? "Something went wrong while finishing up."
      : "Done.");

  return (
    <div className={`turnFinal ${isError ? "failed" : ""}`}>
      <div className="turnFinalHeader">
        <span className="turnFinalAvatar">A</span>
        <span className="turnFinalLabel">Asteria</span>
        {modelMeta && <span className="turnFinalMeta">{modelMeta}</span>}
      </div>
      <div className="turnFinalText">
        <MarkdownBody text={leadText} />
        {details && (
          <details className="turnFinalDetails">
            <summary>Run details</summary>
            <MarkdownBody text={details} />
          </details>
        )}
      </div>
    </div>
  );
}

function stripContextNoise(text: string): string {
  const backendNoise = /\n(?:Context refs:|Current session:|Next actions:|Model route:|Route rationale:|Evidence refs:|Artifact refs:|Run id:|Latest run:)/i;
  return String(text || "")
    .split(backendNoise)[0]
    .replace(/\n?_Answered with model route:[\s\S]*$/i, "")
    .replace(/\n?_Local fallback answer:[\s\S]*$/i, "")
    .replace(/^Latest run:\s*`?run-[^\n]+\n?/gim, "")
    .replace(/^.*(?:Inspector|Evidence Explorer).*$/gim, "")
    .trim();
}

/**
 * Conversation-first split (ADR-0012): render the runtime's lead answer as prose; fold the structured
 * tail (plan / verification / process-summary sections) into a default-collapsed disclosure so the main
 * thread reads like Claude Code / Codex instead of a maintainer report. Full diagnostics live in the Inspector.
 * When the runtime emitted only a short conversational final, there is no tail and the whole thing renders as prose.
 */
function splitLeadAndDetails(text: string): { lead: string; details: string } {
  const raw = String(text || "");
  const lines = raw.split(/\r?\n/);
  const headingIdx: number[] = [];
  lines.forEach((line, index) => { if (/^#{2,6}\s+/.test(line)) headingIdx.push(index); });
  if (headingIdx.length <= 1) {
    // 0 or 1 section: it's already conversational — render as prose, stripping a lone leading heading.
    const stripped = raw.replace(/^#{2,6}\s+.*$/m, "").trim();
    return { lead: stripped || raw.trim(), details: "" };
  }
  const first = headingIdx[0];
  const second = headingIdx[1];
  const preamble = lines.slice(0, first).join("\n");
  const leadBody = lines.slice(first + 1, second).join("\n"); // first section body, heading stripped
  const lead = `${preamble}\n${leadBody}`.trim();
  const details = lines.slice(second).join("\n").trim();
  return { lead, details };
}
