// Identifies MCP-tool and Skill invocations on the main thread.
//
// The runtime already emits these as user_progress tool_output events whose `data` carries
// capability_type + the nested invocation record + the allow/deny capability_decision
// (mcp_adapter.py / skill_adapter.py). The Studio server copies that data verbatim onto the
// StudioEvent (userProgressToStudioEvent). Until now the frontend rendered them as anonymous
// "Action" lines with a generic terminal icon — indistinguishable from a shell command. This
// helper pulls out exactly what's recorded so the thread can name them honestly.
//
// Honesty: only fields actually present on the record are returned. Full request/response bodies
// and the SKILL.md text stay in the Inspector; the main thread shows plain-language identity only.

import type { StudioEvent, AnyRecord } from "./types";

export type CapabilityInfo = {
  type: "mcp" | "skill";
  label: string; // "MCP tool" | "Skill" — replaces the anonymous "Action" label
  title: string; // "github · create_issue" | "deep-research"
  decision: string; // raw decision value (lowercased), e.g. "allow" | "deny"
  denied: boolean;
  retries: number; // MCP retry_attempts (0 for skills)
  artifacts: number; // Skill artifact count (0 for MCP)
};

function asRecord(value: unknown): AnyRecord {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as AnyRecord) : {};
}

export function capabilityInfo(event: StudioEvent | null | undefined): CapabilityInfo | null {
  const data = asRecord(event?.data);
  const type = data.capability_type;
  if (type !== "mcp" && type !== "skill") return null;

  const decisionValue = String(asRecord(data.capability_decision).decision ?? "").toLowerCase();
  const denied = decisionValue === "deny" || decisionValue === "denied";

  if (type === "mcp") {
    const inv = asRecord(data.mcp_invocation);
    const server = String(inv.server_name ?? "").trim();
    const tool = String(inv.tool_name ?? "").trim();
    return {
      type: "mcp",
      label: "MCP 工具",
      title: [server, tool].filter(Boolean).join(" · ") || String(event?.title ?? "MCP 工具"),
      decision: decisionValue,
      denied,
      retries: Number(inv.retry_attempts ?? 0) || 0,
      artifacts: 0,
    };
  }

  const inv = asRecord(data.skill_invocation);
  const skill = String(inv.skill_name ?? "").trim();
  const artifacts = Array.isArray(inv.artifacts)
    ? inv.artifacts.length
    : Array.isArray(inv.artifact_refs)
      ? inv.artifact_refs.length
      : 0;
  return {
    type: "skill",
    label: "技能",
    title: skill || String(event?.title ?? "技能"),
    decision: decisionValue,
    denied,
    retries: 0,
    artifacts,
  };
}
