import type { AnyRecord, NarrativeStep as NarrativeStepType } from "./types";

export type FileChangeRecord = {
  path: string;
  operation?: string;
  additions?: number;
  deletions?: number;
};

export function fileChangePath(record: AnyRecord): string {
  return String(record.path ?? record.file ?? record.relative_path ?? "").replace(/\\/g, "/").trim();
}

export function fileChangeBasename(pathValue: string): string {
  const parts = pathValue.split("/");
  return parts[parts.length - 1] || pathValue || "file";
}

export function extractFileChangesFromSteps(steps: NarrativeStepType[]): FileChangeRecord[] {
  const seen = new Set<string>();
  const result: FileChangeRecord[] = [];

  const push = (raw: AnyRecord) => {
    const pathValue = fileChangePath(raw);
    if (!pathValue || seen.has(pathValue)) return;
    seen.add(pathValue);
    result.push({
      path: pathValue,
      operation: raw.operation ? String(raw.operation) : raw.event_type ? String(raw.event_type) : undefined,
      additions: numberOrUndefined(raw.additions ?? raw.added_lines ?? raw.insertions),
      deletions: numberOrUndefined(raw.deletions ?? raw.removed_lines ?? raw.deletions_count),
    });
  };

  for (const step of steps) {
    for (const event of step.events) {
      for (const item of (event.file_changes ?? []) as AnyRecord[]) push(item);
      if (event.type === "file_changed") {
        push(event.data as AnyRecord);
        const summary = String(event.summary ?? "");
        const match = summary.match(/(?:^|\s)([\w./_-]+\.(?:py|ts|tsx|js|mjs|md|json|yaml|yml|css|html|toml))/i);
        if (match) push({ path: match[1], operation: "change" });
      }
    }
  }
  return result;
}

function numberOrUndefined(value: unknown): number | undefined {
  const num = Number(value);
  return Number.isFinite(num) ? num : undefined;
}
