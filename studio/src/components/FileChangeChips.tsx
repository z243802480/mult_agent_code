import React, { useState } from "react";
import { FileText, Check, Undo2, Loader2 } from "lucide-react";
import type { FileChangeRecord } from "../fileChanges";
import { fileChangeBasename } from "../fileChanges";

export function FileChangeChips({
  changes,
  limit = 10,
  className = "liveFileRow",
  onSelect,
  onAccept,
  onRevert,
}: {
  changes: FileChangeRecord[];
  limit?: number;
  className?: string;
  onSelect?: (path: string) => void;
  onAccept?: (path: string) => Promise<boolean> | void;
  onRevert?: (path: string) => Promise<boolean> | void;
}) {
  if (!changes.length) return null;
  const visible = changes.slice(0, limit);
  const remainder = changes.length - visible.length;

  return (
    <div className={className}>
      {visible.map((change) => (
        <FileChangeChip
          key={change.path}
          change={change}
          onSelect={onSelect}
          onAccept={onAccept}
          onRevert={onRevert}
        />
      ))}
      {remainder > 0 && <span className="liveFileChip muted">+{remainder} more</span>}
    </div>
  );
}

function FileChangeChip({
  change,
  onSelect,
  onAccept,
  onRevert,
}: {
  change: FileChangeRecord;
  onSelect?: (path: string) => void;
  onAccept?: (path: string) => Promise<boolean> | void;
  onRevert?: (path: string) => Promise<boolean> | void;
}) {
  // State declared before any early return so hook order is stable regardless of the branch taken.
  const [pending, setPending] = useState<"" | "accept" | "revert">("");
  const [resolved, setResolved] = useState<"" | "kept" | "reverted">("");

  const name = fileChangeBasename(change.path);
  const adds = change.additions != null ? `+${change.additions}` : "";
  const dels = change.deletions != null ? `-${change.deletions}` : "";
  const delta = [adds, dels].filter(Boolean).join(" ");
  const hasActions = Boolean(onAccept || onRevert);
  const interactive = Boolean(onSelect) || hasActions;

  async function runAction(kind: "accept" | "revert") {
    if (pending || resolved) return;
    if (kind === "revert") {
      // Destructive: `git checkout -- <path>` discards ALL uncommitted changes to this file.
      const ok = window.confirm(
        `Revert ${change.path} to the last commit? Uncommitted changes to this file will be lost.`,
      );
      if (!ok) return;
    }
    const fn = kind === "accept" ? onAccept : onRevert;
    if (!fn) return;
    setPending(kind);
    try {
      const done = await fn(change.path);
      if (done !== false) setResolved(kind === "accept" ? "kept" : "reverted");
    } finally {
      setPending("");
    }
  }

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
    <span className={`liveFileChipWrap ${resolved ? "resolved" : ""}`}>
      <button
        type="button"
        className="liveFileChip interactive"
        title={`View diff: ${change.path}`}
        onClick={() => onSelect?.(change.path)}
        disabled={Boolean(resolved)}
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
      {resolved ? (
        <span className={`liveFileResolved ${resolved}`}>
          {resolved === "kept" ? "Kept" : "Reverted"}
        </span>
      ) : hasActions ? (
        <span className="liveFileActions">
          {onAccept && (
            <button
              type="button"
              className="liveFileAction accept"
              title="Keep — stage this file (git add)"
              aria-label={`Keep ${name}`}
              disabled={Boolean(pending)}
              onClick={() => void runAction("accept")}
            >
              {pending === "accept" ? <Loader2 size={11} className="spinning" /> : <Check size={11} />}
            </button>
          )}
          {onRevert && (
            <button
              type="button"
              className="liveFileAction revert"
              title="Revert — discard this file's changes (git checkout)"
              aria-label={`Revert ${name}`}
              disabled={Boolean(pending)}
              onClick={() => void runAction("revert")}
            >
              {pending === "revert" ? <Loader2 size={11} className="spinning" /> : <Undo2 size={11} />}
            </button>
          )}
        </span>
      ) : null}
    </span>
  );
}
