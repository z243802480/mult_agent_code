import React, { useState } from "react";
import {
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clock3,
  FileText,
  FolderOpen,
  ListChecks,
  Play,
  ShieldAlert,
  Terminal,
  XCircle,
} from "lucide-react";
import type { StudioEvent, AnyRecord } from "../types";
import { Status } from "./Shared";
import { WorkerProgressBar } from "./WorkerProgressBar";

function asRecord(value: unknown): AnyRecord {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as AnyRecord) : {};
}

function formatEventTime(value: unknown): string {
  const date = new Date(String(value ?? ""));
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString();
}

function iconFor(type: StudioEvent["type"]) {
  if (type === "agent_turn") return <Clock3 size={15} />;
  if (type === "tool_start" || type === "tool_delta" || type === "tool_end") return <Terminal size={15} />;
  if (type === "tool_observation") return <ListChecks size={15} />;
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

function observationText(event: StudioEvent): string {
  const observation = (event.data as AnyRecord | undefined)?.observation as AnyRecord | undefined;
  const summary = String(observation?.model_summary ?? observation?.summary ?? "").trim();
  const stdout = String(observation?.stdout_excerpt ?? "").trim();
  const stderr = String(observation?.stderr_excerpt ?? "").trim();
  return [summary, stdout && `stdout: ${stdout}`, stderr && `stderr: ${stderr}`]
    .filter(Boolean)
    .join("\n");
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
    event.type === "agent_turn" ||
    event.type === "tool_observation" ||
    event.type === "final_answer" ||
    event.type === "error" ||
    event.type === "permission_request";
  const showCommandInline = event.type === "permission_request";
  const fileChanges = (event.file_changes ?? []) as AnyRecord[];
  const bodyText = event.content_delta || (event.type === "tool_observation" ? observationText(event) : "");

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
        {asRecord(event.data).kind === "worker_summary" && (
          <WorkerProgressBar data={asRecord(event.data)} />
        )}
        <div className="eventFacts">
          {event.model_provider && (
            <span>
              {event.model_provider}/{event.model_name ?? "unknown"}{event.model_tier ? ` ? ${event.model_tier}` : ""}
            </span>
          )}
          {event.model_route && !event.model_provider && (
            <span>
              {String((event.model_route as AnyRecord).provider ?? "model")}/{String((event.model_route as AnyRecord).model ?? "unknown")}
            </span>
          )}
          {(event.evidence_refs?.length ?? 0) > 0 && <span>{event.evidence_refs!.length} evidence</span>}
          {(event.artifact_refs?.length ?? 0) > 0 && <span>{event.artifact_refs!.length} artifacts</span>}
          {fileChanges.length > 0 && <span>{fileChanges.length} file{fileChanges.length === 1 ? "" : "s"}</span>}
          <span>{formatEventTime(event.created_at)}</span>
        </div>
        {showBody &&
          (open || event.type !== "reasoning_delta") &&
          bodyText && (
            <pre className={isUser ? "messageText" : "deltaText"}>{bodyText}</pre>
          )}
        {showCommandInline && event.command && (
          <code className="commandLine">{event.command.join(" ")}</code>
        )}
      </div>
    </article>
  );
}
