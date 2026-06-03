import React, { useState } from "react";
import {
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CircleDot,
  Clock3,
  FileText,
  GitBranch,
  ListChecks,
  RefreshCw,
  ShieldAlert,
  Terminal,
  XCircle,
} from "lucide-react";
import type { NarrativeStep as NarrativeStepType, StudioEvent } from "../types";
import { Status } from "./Shared";
import { EventCard } from "./EventCard";

function formatEventTime(value: unknown): string {
  const date = new Date(String(value ?? ""));
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString();
}

function stepIcon(kind: NarrativeStepType["kind"]) {
  if (kind === "goal") return <CircleDot size={14} />;
  if (kind === "thinking") return <Clock3 size={14} />;
  if (kind === "plan") return <GitBranch size={14} />;
  if (kind === "turn") return <RefreshCw size={14} />;
  if (kind === "tool") return <Terminal size={14} />;
  if (kind === "observation") return <ListChecks size={14} />;
  if (kind === "result") return <FileText size={14} />;
  if (kind === "repair") return <RefreshCw size={14} />;
  if (kind === "verification") return <ShieldAlert size={14} />;
  if (kind === "final") return <CheckCircle2 size={14} />;
  return <XCircle size={14} />;
}

export function NarrativeStep({
  step,
  selected,
  onSelect,
}: {
  step: NarrativeStepType;
  selected: StudioEvent | null;
  onSelect: (event: StudioEvent) => void;
}) {
  const [open, setOpen] = useState(step.defaultOpen);
  const primary = step.events[0];
  const time = primary ? formatEventTime(primary.created_at) : "";

  // Goal step stays as a compact user-message bubble.
  if (step.kind === "goal") {
    const userText = primary?.content_delta || step.summary || step.title;
    return (
      <article className="narrativeStep goal completed">
        <div className="goalBubble">
          <p>{userText}</p>
          <span className="goalMeta">
            {time}
          </span>
        </div>
      </article>
    );
  }

  return (
    <article className={`narrativeStep ${step.kind} ${step.status}`}>
      <button className="stepChrome" onClick={() => setOpen((o) => !o)}>
        <span className="stepIcon">{stepIcon(step.kind)}</span>
        <span className="stepLabels">
          <strong>{step.label}</strong>
          <small>{step.title}</small>
        </span>
        <span className="stepInlineFacts">
          {primary?.model_provider && (
            <span>{primary.model_provider}</span>
          )}
          <span>{step.events.length} update{step.events.length === 1 ? "" : "s"}</span>
          <span>{time}</span>
        </span>
        <Status status={step.status} />
        {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
      </button>
      {open && (
        <div className="stepExpanded">
          {step.summary && step.summary !== step.title && (
            <p className="stepSummaryText">{step.summary}</p>
          )}
          <div className="stepEvents">
            {step.events.map((event) => (
              <EventCard
                event={event}
                compact
                selected={selected?.event_id === event.event_id}
                key={event.event_id}
                onSelect={() => onSelect(event)}
              />
            ))}
          </div>
        </div>
      )}
    </article>
  );
}
