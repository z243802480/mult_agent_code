import type { NarrativeStep as NarrativeStepType, StudioEvent } from "../../types";
import { extractFileChangesFromSteps } from "../../fileChanges";
import { firstText } from "./threadUtils";

export function middleSummary(steps: NarrativeStepType[]): string {
  const commandCount = steps.reduce(
    (count, step) => count + step.events.filter((event) => Array.isArray(event.command) && event.command.length > 0).length,
    0
  );
  const fileCount = extractFileChangesFromSteps(steps).length;
  const hasVerification = steps.some((step) =>
    step.kind === "verification" || step.events.some((event) => event.phase === "review")
  );
  const hasRepair = steps.some((step) => step.kind === "repair");
  const hasError = steps.some((step) => step.kind === "error" || step.status === "failed" || step.status === "blocked");
  const hasPlan = steps.some((step) => step.kind === "plan");
  const parts: string[] = [];
  if (commandCount) parts.push(`Ran ${commandCount} action${commandCount === 1 ? "" : "s"}`);
  if (fileCount) parts.push(`Updated ${fileCount} file${fileCount === 1 ? "" : "s"}`);
  if (hasVerification) parts.push("Verified");
  if (hasRepair) parts.push("Repaired");
  if (hasError) parts.push("Needs attention");
  if (!parts.length && hasPlan) parts.push("Planned");
  if (!parts.length) parts.push(`${steps.length} process update${steps.length === 1 ? "" : "s"}`);
  return parts.slice(0, 3).join(" / ");
}

export function hasFinalAnswerForPhase(steps: NarrativeStepType[], phase?: string): boolean {
  return steps.some((step) =>
    step.kind === "final"
    && step.events.some((event) =>
      event.type === "final_answer" && (!phase || event.phase === phase)
    )
  );
}

export function isModelThinkingStep(step: NarrativeStepType, phase?: string): boolean {
  return step.kind === "thinking"
    && step.events.some((event) =>
      event.type.startsWith("model_") && (!phase || event.phase === phase)
    );
}

export function middleRepresentativeEvent(steps: NarrativeStepType[]): StudioEvent | null {
  const events = steps.flatMap((step) => step.events);
  return events.find((event) => event.type === "permission_request" && event.status === "waiting_user")
    ?? events.find((event) => event.status === "failed" || event.status === "blocked")
    ?? events.find((event) => event.status === "running")
    ?? events[0]
    ?? null;
}

export function turnModelMetadata(middleSteps: NarrativeStepType[], responseStep: NarrativeStepType | null): string {
  const events = [...middleSteps.flatMap((step) => step.events), ...(responseStep?.events ?? [])];
  const modelEvent = [...events].reverse().find((item) => item.model_provider || item.model_name);
  if (!modelEvent) return "";
  const provider = String(modelEvent.model_provider ?? "").trim();
  const model = String(modelEvent.model_name ?? "").trim();
  const parts = [provider && model ? `${provider}/${model}` : provider || model];
  return parts.filter(Boolean).join(" · ");
}

