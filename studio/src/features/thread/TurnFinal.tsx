import React from "react";
import type { NarrativeStep as NarrativeStepType } from "../../types";
import { MarkdownBody } from "../../components/MarkdownBody";
import { firstText } from "./threadUtils";
import { turnModelMetadata } from "./turnHelpers";

export function TurnFinal({ step, middleSteps }: { step: NarrativeStepType; middleSteps: NarrativeStepType[]; }) {
  const event = step.events[0];
  const text = event?.content_delta || step.summary || step.title || "No content";
  const isError = step.kind === "error" || step.status === "failed";
  const visibleText = stripContextNoise(text);
  const sections = finalSections(visibleText, isError, middleSteps);
  const modelMeta = turnModelMetadata(middleSteps, step);
  const useMarkdown = visibleText.includes("## ") || visibleText.includes("```") || visibleText.includes("\n- ");
  const primarySection = sections[0];
  // No placeholder filtering needed: finalSections only emits verification / next-step sections
  // when the runtime actually produced them, so every secondary section here is real content.
  const secondarySections = sections.slice(1);

  return (
    <div className={`turnFinal ${isError ? "failed" : ""}`}>
      <div className="turnFinalHeader">
        <span className="turnFinalAvatar">A</span>
        <span className="turnFinalLabel">Asteria</span>
        {modelMeta && <span className="turnFinalMeta">{modelMeta}</span>}
      </div>
      <div className="turnFinalText">
        {useMarkdown ? (
          <MarkdownBody text={visibleText} />
        ) : (
          <>
            <section className="primaryFinalSection">
              {primarySection.title && <h3>{primarySection.title}</h3>}
              {primarySection.lines.map((line, lineIndex) => renderFinalLine(line, lineIndex))}
            </section>
            {secondarySections.length > 0 && (
              <details className="turnFinalDetails">
                <summary>Verification & next steps</summary>
                {secondarySections.map((section, index) => (
                  <section key={`${section.title}-${index}`}>
                    {section.title && <h3>{section.title}</h3>}
                    {section.lines.map((line, lineIndex) => renderFinalLine(line, lineIndex))}
                  </section>
                ))}
              </details>
            )}
          </>
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

type FinalSection = { title: string; lines: string[] };

// Honest final card (ADR-0012): render only what the runtime actually produced. Never invent a
// final answer, never pad missing verification / next-step with fabricated filler. Absent extras
// are simply not shown (answer-first, like Codex / Claude Code) rather than scaffolded with
// "nothing was recorded" placeholders that a downstream filter then has to hide.
function finalSections(text: string, isError: boolean, middleSteps: NarrativeStepType[]): FinalSection[] {
  const sections = splitFinalSections(text);
  const byTitle = new Map(
    sections
      .filter((section) => section.title)
      .map((section) => [canonicalFinalTitle(section.title), section.lines.filter((line) => line.trim())])
  );
  const rawLines = sections.flatMap((section) => section.lines).filter((line) => line.trim());
  const resultLines = byTitle.get("Result") ?? byTitle.get("Issue") ?? rawLines;
  const verificationLines = byTitle.get("Verification") ?? inferredVerificationLines(middleSteps);
  const risksLines = byTitle.get("Risks / Next step") ?? byTitle.get("Next step") ?? inferredRiskLines(middleSteps, isError);

  const out: FinalSection[] = [
    {
      title: isError ? "Issue" : "Result",
      // Never fabricate a success/status line when the runtime recorded no answer content.
      lines: resultLines.length ? resultLines : ["No answer content was recorded for this turn."],
    },
  ];
  if (verificationLines.length) out.push({ title: "Verification", lines: verificationLines });
  if (risksLines.length) out.push({ title: "Risks / Next step", lines: risksLines });
  return out;
}

function canonicalFinalTitle(value: string): string {
  const text = value.trim().toLowerCase();
  if (/issue|error|problem|blocked|风险|问题/.test(text)) return "Issue";
  if (/verify|validation|review|检查|验证/.test(text)) return "Verification";
  if (/risk|next|action|tradeoff|下一步|风险/.test(text)) return "Risks / Next step";
  if (/result|summary|outcome|done|结果|总结/.test(text)) return "Result";
  return value.trim();
}

function inferredVerificationLines(middleSteps: NarrativeStepType[]): string[] {
  const verification = middleSteps
    .filter((step) => step.kind === "verification" || step.events.some((event) => event.phase === "review"))
    .map((step) => firstText(step.summary, step.title))
    .filter(Boolean);
  return [...new Set(verification)].slice(0, 3);
}

function inferredRiskLines(middleSteps: NarrativeStepType[], isError: boolean): string[] {
  const failed = middleSteps
    .filter((step) => step.status === "failed" || step.status === "blocked" || step.kind === "error" || step.kind === "repair")
    .map((step) => firstText(step.summary, step.title))
    .filter(Boolean);
  if (failed.length) return [...new Set(failed)].slice(0, 3);
  return isError ? ["Review the issue detail and choose Debug, Replan, Ask, or Stop."] : [];
}

function splitFinalSections(text: string): FinalSection[] {
  const sections: { title: string; lines: string[] }[] = [];
  let current: { title: string; lines: string[] } = { title: "", lines: [] };
  for (const raw of String(text || "").split(/\r?\n/)) {
    const heading = raw.match(/^##\s+(.+?)\s*$/);
    if (heading) {
      if (current.title || current.lines.some(Boolean)) sections.push(current);
      current = { title: heading[1].trim(), lines: [] };
      continue;
    }
    current.lines.push(raw);
  }
  if (current.title || current.lines.some(Boolean)) sections.push(current);
  return sections.length ? sections : [{ title: "", lines: [text] }];
}

function renderFinalLine(line: string, index: number) {
  if (!line.trim()) return null;
  const bullet = line.match(/^\s*-\s+(.+)$/);
  if (bullet) return <p key={index} className="finalBullet">{bullet[1]}</p>;
  if (/^\s{2,}\S/.test(line)) return <p key={index} className="finalDetail">{line.trim()}</p>;
  return <p key={index}>{line}</p>;
}

