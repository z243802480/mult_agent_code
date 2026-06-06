import React from "react";
import { FileText } from "lucide-react";
import type { FileChangeRecord } from "../fileChanges";
import { fileChangeBasename } from "../fileChanges";

export function FileChangeChips({
  changes,
  limit = 10,
  className = "liveFileRow",
  onSelect,
}: {
  changes: FileChangeRecord[];
  limit?: number;
  className?: string;
  onSelect?: (path: string) => void;
}) {
  if (!changes.length) return null;
  const visible = changes.slice(0, limit);
  const remainder = changes.length - visible.length;

  return (
    <div className={className}>
      {visible.map((change) => (
        <FileChangeChip key={change.path} change={change} onSelect={onSelect} />
      ))}
      {remainder > 0 && <span className="liveFileChip muted">+{remainder} more</span>}
    </div>
  );
}

function FileChangeChip({
  change,
  onSelect,
}: {
  change: FileChangeRecord;
  onSelect?: (path: string) => void;
}) {
  const name = fileChangeBasename(change.path);
  const adds = change.additions != null ? `+${change.additions}` : "";
  const dels = change.deletions != null ? `-${change.deletions}` : "";
  const delta = [adds, dels].filter(Boolean).join(" ");
  const interactive = Boolean(onSelect);

  if (!interactive) {
    return (
      <span className="liveFileChip" title={change.path}>
        <FileText size={10} />
        {name}
        {delta && <span className="liveFileDelta">{delta}</span>}
      </span>
    );
  }

  return (
    <button
      type="button"
      className="liveFileChip interactive"
      title={`View diff: ${change.path}`}
      onClick={() => onSelect?.(change.path)}
    >
      <FileText size={10} />
      <span className="liveFileName">{name}</span>
      {delta && (
        <span className="liveFileDelta">
          {adds && <span className="deltaAdd">{adds}</span>}
          {dels && <span className="deltaDel">{dels}</span>}
        </span>
      )}
    </button>
  );
}
