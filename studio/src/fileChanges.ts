import type { AnyRecord, NarrativeStep as NarrativeStepType, StudioEvent } from "./types";

export type FileChangeRecord = {
  path: string;
  operation?: string;
  additions?: number;
  deletions?: number;
};

export function fileChangePath(record: AnyRecord): string {
  return String(record.path ?? record.file ?? record.relative_path ?? "")
    .replace(/\\/g, "/")
    .trim();
}

export function extractFileChangesFromSteps(steps: NarrativeStepType[]): FileChangeRecord[] {
  return extractFileChangesFromEvents(steps.flatMap((step) => step.events));
}

// Same extraction straight from transcript events — for surfaces that hold events, not narrative
// steps (e.g. the Inspector scoping its Preview tab to files THIS session actually touched).
export function extractFileChangesFromEvents(events: StudioEvent[]): FileChangeRecord[] {
  const seen = new Set<string>();
  const result: FileChangeRecord[] = [];

  const push = (raw: AnyRecord) => {
    const pathValue = fileChangePath(raw);
    if (!pathValue || seen.has(pathValue)) return;
    // .asteria/ is the runtime's own state root (goal_spec, task_plan, cost_report, backlog, ...).
    // Those are evidence bookkeeping, not user code edits, so they must never appear as reviewable
    // (and now Keep/Revert-able) file changes in the thread.
    if (isRuntimeInternalPath(pathValue)) return;
    seen.add(pathValue);
    result.push({
      path: pathValue,
      operation: raw.operation
        ? String(raw.operation)
        : raw.event_type
          ? String(raw.event_type)
          : undefined,
      additions: numberOrUndefined(raw.additions ?? raw.added_lines ?? raw.insertions),
      deletions: numberOrUndefined(raw.deletions ?? raw.removed_lines ?? raw.deletions_count),
    });
  };

  for (const event of events) {
    for (const item of (event.file_changes ?? []) as AnyRecord[]) push(item);
    // Structured file_changed events already carry the real, full path. The old summary-text
    // scrape was dropped: its `js|json` alternation mis-captured `foo.json` as a phantom `foo.js`,
    // and it surfaced un-path-filterable internal-artifact basenames. Real paths only, no guessing.
    if (event.type === "file_changed") push(event.data as AnyRecord);
  }
  return result;
}

function isRuntimeInternalPath(pathValue: string): boolean {
  const p = pathValue.replace(/\\/g, "/").toLowerCase();
  return p === ".asteria" || p.startsWith(".asteria/") || p.includes("/.asteria/");
}

function numberOrUndefined(value: unknown): number | undefined {
  const num = Number(value);
  return Number.isFinite(num) ? num : undefined;
}

export function fileChangeBasename(pathValue: string): string {
  const parts = pathValue.split("/");
  return parts[parts.length - 1] || pathValue || "file";
}

export function aggregateFileChangeStats(changes: FileChangeRecord[]): {
  files: number;
  additions: number;
  deletions: number;
} {
  let additions = 0;
  let deletions = 0;
  for (const change of changes) {
    additions += change.additions ?? 0;
    deletions += change.deletions ?? 0;
  }
  return { files: changes.length, additions, deletions };
}
