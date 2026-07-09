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
  Plug,
  ShieldAlert,
  Sparkles,
  Terminal,
  XCircle,
} from "lucide-react";
import type { StudioEvent, AnyRecord } from "../types";
import { Status } from "./Shared";
import { WorkerProgressBar } from "./WorkerProgressBar";
import { ClampedOutput } from "./ClampedOutput";
import { capabilityInfo } from "../capability";

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
  if (type === "tool_start" || type === "tool_delta" || type === "tool_end")
    return <Terminal size={15} />;
  if (type === "tool_observation") return <ListChecks size={15} />;
  if (type === "model_start" || type === "model_delta" || type === "model_end")
    return <Play size={15} />;
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
  if (phase === "understand") return "理解";
  if (phase === "plan") return "计划";
  if (phase === "execute") return "执行";
  if (phase === "review") return "查看";
  if (phase === "resume") return "继续";
  if (phase === "result") return "结果";
  if (phase === "next") return "下一步";
  return fallback;
}

function observationText(event: StudioEvent): string {
  const observation = (event.data as AnyRecord | undefined)?.observation as AnyRecord | undefined;
  const summary = String(observation?.model_summary ?? observation?.summary ?? "").trim();
  const stdout = String(observation?.stdout_excerpt ?? "").trim();
  const stderr = String(observation?.stderr_excerpt ?? "").trim();
  return [summary, stdout && `输出：${stdout}`, stderr && `错误：${stderr}`]
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
  const cap = capabilityInfo(event);
  const icon = cap ? (
    cap.type === "mcp" ? (
      <Plug size={15} />
    ) : (
      <Sparkles size={15} />
    )
  ) : (
    iconFor(event.type)
  );
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
  const fileChanges = (event.file_changes ?? []) as AnyRecord[];
  const bodyText =
    event.content_delta || (event.type === "tool_observation" ? observationText(event) : "");
  const clampBody =
    compact ||
    event.type === "tool_observation" ||
    event.type === "tool_end" ||
    event.type === "tool_delta";

  return (
    <article
      className={`eventCard ${event.type} ${event.status} ${selected ? "selected" : ""} ${compact ? "compact" : ""}`}
      onClick={onSelect}
    >
      {!compact && (
        <div className="phaseRail">
          <span>{phaseLabel(event.phase, event.title)}</span>
        </div>
      )}
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
          <WorkerProgressBar data={asRecord(event.data)} compact={compact} />
        )}
        <div className="eventFacts">
          {cap?.denied && <span className="capabilityChip denied">已被权限拦截</span>}
          {cap && !cap.denied && cap.retries > 0 && <span>重试 {cap.retries} 次</span>}
          {cap && !cap.denied && cap.artifacts > 0 && <span>产出 {cap.artifacts} 个文件</span>}
          {!compact && event.model_provider && (
            <span>
              {event.model_provider}/{event.model_name ?? "未知"}
              {event.model_tier ? ` ? ${event.model_tier}` : ""}
            </span>
          )}
          {!compact && event.model_route && !event.model_provider && (
            <span>
              {String((event.model_route as AnyRecord).provider ?? "model")}/
              {String((event.model_route as AnyRecord).model ?? "未知")}
            </span>
          )}
          {!compact && (event.evidence_refs?.length ?? 0) > 0 && (
            <span>{event.evidence_refs!.length} 条证据</span>
          )}
          {!compact && (event.artifact_refs?.length ?? 0) > 0 && (
            <span>{event.artifact_refs!.length} 个产物</span>
          )}
          {fileChanges.length > 0 && <span>{fileChanges.length} 个文件</span>}
          <span>{formatEventTime(event.created_at)}</span>
        </div>
        {showBody &&
          (open || event.type !== "reasoning_delta") &&
          bodyText &&
          (clampBody ? (
            <ClampedOutput
              text={bodyText}
              className={isUser ? "messageText" : "deltaText"}
              maxLines={8}
            />
          ) : (
            <pre className={isUser ? "messageText" : "deltaText"}>{bodyText}</pre>
          ))}
      </div>
    </article>
  );
}
