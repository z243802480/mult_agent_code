import type { NarrativeStep as NarrativeStepType, StudioEvent } from "../../types";
import { extractFileChangesFromSteps } from "../../fileChanges";

export function middleSummary(steps: NarrativeStepType[]): string {
  const commandCount = steps.reduce(
    (count, step) =>
      count +
      step.events.filter((event) => Array.isArray(event.command) && event.command.length > 0)
        .length,
    0,
  );
  const fileCount = extractFileChangesFromSteps(steps).length;
  const hasVerification = steps.some(
    (step) => step.kind === "verification" || step.events.some((event) => event.phase === "review"),
  );
  const hasRepair = steps.some((step) => step.kind === "repair");
  const hasError = steps.some(
    (step) => step.kind === "error" || step.status === "failed" || step.status === "blocked",
  );
  const hasPlan = steps.some((step) => step.kind === "plan");
  const parts: string[] = [];
  if (commandCount) parts.push(`执行了 ${commandCount} 个操作`);
  if (fileCount) parts.push(`更新了 ${fileCount} 个文件`);
  if (hasVerification) parts.push("已验证");
  if (hasRepair) parts.push("已修复");
  if (hasError) parts.push("待处理");
  if (!parts.length && hasPlan) parts.push("已规划");
  if (!parts.length) parts.push(`${steps.length} 条过程更新`);
  return parts.slice(0, 3).join(" / ");
}

export function hasFinalAnswerForPhase(steps: NarrativeStepType[], phase?: string): boolean {
  return steps.some(
    (step) =>
      step.kind === "final" &&
      step.events.some(
        (event) => event.type === "final_answer" && (!phase || event.phase === phase),
      ),
  );
}

export function isModelThinkingStep(step: NarrativeStepType, phase?: string): boolean {
  return (
    step.kind === "thinking" &&
    step.events.some(
      (event) => event.type.startsWith("model_") && (!phase || event.phase === phase),
    )
  );
}

export function middleRepresentativeEvent(steps: NarrativeStepType[]): StudioEvent | null {
  const events = steps.flatMap((step) => step.events);
  return (
    events.find(
      (event) => event.type === "permission_request" && event.status === "waiting_user",
    ) ??
    events.find((event) => event.status === "failed" || event.status === "blocked") ??
    events.find((event) => event.status === "running") ??
    events[0] ??
    null
  );
}

export function turnModelMetadata(
  _middleSteps: NarrativeStepType[],
  _responseStep: NarrativeStepType | null,
): string {
  // Main thread no longer surfaces provider/model in the TurnFinal header (de-internalization).
  // Returning an empty string keeps the call site and types intact; the header meta span is hidden
  // because TurnFinal only renders it when this is non-empty. Raw model info still lives in the Inspector.
  return "";
}
