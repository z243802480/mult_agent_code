import React, { useState } from "react";
import {
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clock3,
  FileText,
  FolderOpen,
  Play,
  ShieldAlert,
  Terminal,
  XCircle,
} from "lucide-react";
import type { StudioEvent, AnyRecord } from "../types";
import { Status } from "./Shared";

function iconFor(type: StudioEvent["type"]) {
  if (type === "tool_start" || type === "tool_delta" || type === "tool_end") return <Terminal size={15} />;
  if (type === "model_start" || type === "model_delta" || type === "model_end") return <Play size={15} />;
  if (type === "model_error") return <XCircle size={15} />;
  if (type === "permission_request") return <ShieldAlert size={15} />;
  if (type === "file_changed") return <FolderOpen size={15} />;
  if (type === "final_answer") return <CheckCircle2 size={15} />;
  if (type === "error") return <XCircle size={15} />;
  if (type === "reasoning_delta") return <Clock3 size={15} />;
  if (type === "assistant_delta") return <FileText size={15} />;
  return null;
}

function phaseLabel(phase: StudioEvent["phase"], fallback: string): string {
  if (phase === "understand") return "understand";
  if (phase === "plan") return "plan";
  if (phase === "execute") return "execute";
  if (phase === "review") return "review";
  if (phase === "resume") return "resume";
  if (phase === "result") return "result";
  if (phase === "next") return "next";
  return fallback;
}

export function EventCard({
  event,
  selected,
  onSelect,
  compact = false,
}: {
  event: StudioEvent;
  selected: boolean;
  onSelect: () => void;
  compact?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const icon = iconFor(event.type);
  const isUser = event.type === "user_message";
  const isModel = ["model_start", "model_delta", "model_end", "model_error"].includes(event.type);
  const showBody =
    isUser ||
    isModel ||
    event.type === "assistant_delta" ||
    event.type === "reasoning_delta" ||
    event.type === "final_answer" ||
    event.type === "error" ||
    event.type === "permission_request";
  const showCommandInline = event.type === "permission_request";
  const fileChanges = (event.file_changes ?? []) as AnyRecord[];

  return (
    <article
      className={`eventCard ${event.type} ${event.status} ${selected ? "selected" : ""} ${compact ? "compact" : ""}`}
      onClick={onSelect}
    >
      <div className="phaseRail">
        <span>{phaseLabel(event.phase, event.title)}</span>
      </div>
      <div className="eventBody">
        <div className="eventHeader">
          <div>
            <span className="eventIcon">{icon}</span>
            <strong>{event.title}</strong>
            <Status status={event.status} />
          </div>
          {event.type === "reasoning_delta" && (
            <button
              className="foldButton"
              onClick={(click) => {
                click.stopPropagation();
                setOpen((o) => !o);
              }}
            >
              {open ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
            </button>
          )}
        </div>
        <p className="eventSummary">{event.summary}</p>
        <div className="eventFacts">
          {event.model_provider && (
            <span>
              {event.model_provider}/{event.model_name ?? "unknown"}
            </span>
          )}
          {(event.evidence_refs?.length ?? 0) > 0 && <span>{event.evidence_refs!.length} evidence</span>}
          {(event.artifact_refs?.length ?? 0) > 0 && <span>{event.artifact_refs!.length} artifacts</span>}
          {fileChanges.length > 0 && <span>{fileChanges.length} 文件</span>}
          <span>{new Date(event.created_at).toLocaleTimeString()}</span>
        </div>
        {showBody &&
          (open || event.type !== "reasoning_delta") &&
          event.content_delta && (
            <pre className={isUser ? "messageText" : "deltaText"}>{event.content_delta}</pre>
          )}
        {showCommandInline && event.command && (
          <code className="commandLine">{event.command.join(" ")}</code>
        )}
      </div>
    </article>
  );
}
