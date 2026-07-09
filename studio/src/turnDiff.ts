import type { FileChangeRecord } from "./fileChanges";
import { extractFileChangesFromSteps } from "./fileChanges";
import { buildRunNarrative, toNarrativeEvents } from "./narrative";
import type { NarrativeStep as NarrativeStepType, StudioEvent } from "./types";

export type TurnDiffScope = {
  id: string;
  label: string;
  kind: "workspace" | "turn";
  turnIndex?: number;
  files: FileChangeRecord[];
  userPreview?: string;
};

export function splitIntoTurns(steps: NarrativeStepType[]): NarrativeStepType[][] {
  const turns: NarrativeStepType[][] = [];
  let current: NarrativeStepType[] | null = null;
  // Steps that arrive before the first user_message (e.g. an assistant greeting or a
  // diagnostic at session start) used to be silently dropped — neither branch caught them.
  // Keep them in an implicit leading turn (rendered goal-less by ConversationTurn) so no
  // transcript content is lost.
  let leading: NarrativeStepType[] | null = null;
  for (const step of steps) {
    if (step.kind === "goal") {
      if (leading) {
        turns.push(leading);
        leading = null;
      }
      if (current) turns.push(current);
      current = [step];
    } else if (current) {
      current.push(step);
    } else {
      (leading ??= []).push(step);
    }
  }
  if (leading) turns.push(leading);
  if (current) turns.push(current);
  return turns;
}

function turnMiddleSteps(turnSteps: NarrativeStepType[]): NarrativeStepType[] {
  const rest = turnSteps.slice(1);
  const responseIndex = (() => {
    for (let index = rest.length - 1; index >= 0; index -= 1) {
      if (rest[index].kind === "final" || rest[index].kind === "error") return index;
    }
    return -1;
  })();
  return responseIndex >= 0 ? rest.filter((_, index) => index !== responseIndex) : rest;
}

function turnUserPreview(turnSteps: NarrativeStepType[]): string {
  const goalStep = turnSteps[0];
  const goalEvent = goalStep?.events[0];
  const text = String(
    goalEvent?.content_delta ?? goalStep?.summary ?? goalStep?.title ?? "",
  ).trim();
  if (text.length <= 72) return text;
  return `${text.slice(0, 69)}…`;
}

export function buildTurnDiffScopes(events: StudioEvent[]): TurnDiffScope[] {
  const mainEvents = events.filter(
    (event) => !event.display_level || event.display_level === "main",
  );
  const narrative = buildRunNarrative(toNarrativeEvents(mainEvents));
  const turns = splitIntoTurns(narrative.steps);
  const scopes: TurnDiffScope[] = [
    {
      id: "current",
      label: "当前",
      kind: "workspace",
      files: [],
    },
  ];

  turns.forEach((turnSteps, index) => {
    const files = extractFileChangesFromSteps(turnMiddleSteps(turnSteps));
    if (!files.length) return;
    const turnIndex = index + 1;
    scopes.push({
      id: `turn-chrono-${turnIndex}`,
      label: `T${turnIndex}`,
      kind: "turn",
      turnIndex,
      files,
      userPreview: turnUserPreview(turnSteps),
    });
  });

  const turnScopes = scopes.filter((scope) => scope.kind === "turn");
  turnScopes.reverse().forEach((scope, displayIndex) => {
    scope.label = `T${displayIndex + 1}`;
    scope.id = `turn-${displayIndex + 1}`;
  });

  return scopes;
}

export function scopePaths(scope: TurnDiffScope | null | undefined): Set<string> {
  return new Set((scope?.files ?? []).map((file) => file.path));
}
