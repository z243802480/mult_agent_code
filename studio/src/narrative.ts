import type { StudioEvent, NarrativeStep, RunNarrative } from "./types";

export function toNarrativeEvents(events: StudioEvent[]): StudioEvent[] {
  const result: StudioEvent[] = [];
  let activeModel: StudioEvent | null = null;
  for (const event of events) {
    if (event.type === "model_start") {
      activeModel = { ...event, type: "model_delta", summary: event.summary || "正在等待模型返回内容。" };
      result.push(activeModel);
      continue;
    }
    if (event.type === "model_delta") {
      if (activeModel && activeModel.phase === event.phase && activeModel.model_provider === event.model_provider) {
        activeModel.content_delta = `${activeModel.content_delta ?? ""}${event.content_delta ?? ""}`;
        activeModel.summary = event.summary || activeModel.summary;
        activeModel.status = event.status;
        activeModel.created_at = event.created_at;
      } else {
        activeModel = { ...event };
        result.push(activeModel);
      }
      continue;
    }
    if (event.type === "model_end") {
      if (activeModel && activeModel.phase === event.phase && activeModel.model_provider === event.model_provider) {
        activeModel.status = "completed";
        activeModel.summary = event.summary || activeModel.summary;
        activeModel.telemetry = event.telemetry;
      }
      activeModel = null;
      continue;
    }
    if (event.type === "model_error") { activeModel = null; result.push(event); continue; }
    if (event.type === "tool_start" || event.type === "tool_delta" || event.type === "tool_end") {
      activeModel = null; result.push(event); continue;
    }
    activeModel = null;
    result.push(event);
  }
  return result;
}

function narrativeKind(event: StudioEvent): NarrativeStep["kind"] {
  if (event.type === "user_message") return "goal";
  if (event.type === "permission_request") return "tool";
  if (event.type === "tool_start" || event.type === "tool_delta" || event.type === "tool_end") return "tool";
  if (event.type === "model_error" || event.type === "error") return "error";
  if (event.type === "final_answer") return "final";
  if (event.phase === "plan") return "plan";
  if (event.phase === "review") return "verification";
  if (event.phase === "execute" || event.phase === "resume") return event.status === "failed" ? "repair" : "tool";
  if (event.type === "model_start" || event.type === "model_delta" || event.type === "model_end" || event.type === "reasoning_delta") return "thinking";
  if (event.type === "file_changed") return "result";
  return "thinking";
}

function narrativeLabel(kind: NarrativeStep["kind"], event: StudioEvent): string {
  if (kind === "goal") return "用户目标";
  if (kind === "thinking" && event.phase === "plan" && event.model_provider) return "结构化生成";
  if (kind === "thinking") return "思考";
  if (kind === "plan") return "计划";
  if (kind === "tool") return event.command?.length ? "工具调用" : "动作";
  if (kind === "result") return "文件变化";
  if (kind === "repair") return "修复";
  if (kind === "verification") return "验证";
  if (kind === "final") return "最终结果";
  return "问题";
}

function shouldGroup(step: NarrativeStep, event: StudioEvent): boolean {
  const first = step.events[0];
  if (step.kind === "goal" || step.kind === "final" || step.kind === "error") return false;
  if (step.kind === "thinking") return first.phase === event.phase && first.model_provider === event.model_provider;
  if (step.kind === "tool") {
    if (first.command?.join(" ") === event.command?.join(" ")) return true;
    return first.type.startsWith("tool_") && event.type.startsWith("tool_") && first.title === event.title;
  }
  return first.phase === event.phase;
}

function mergeStatus(current: StudioEvent["status"], next: StudioEvent["status"]): StudioEvent["status"] {
  if (next === "failed" || current === "failed") return "failed";
  if (next === "waiting_user" || current === "waiting_user") return "waiting_user";
  if (next === "running" || current === "running") return "running";
  if (next === "queued" || current === "queued") return "queued";
  return "completed";
}

function countRefs(events: StudioEvent[], key: "evidence_refs" | "artifact_refs"): number {
  return events.reduce((n, e) => n + (e[key]?.length ?? 0), 0);
}

export function buildRunNarrative(events: StudioEvent[]): RunNarrative {
  const steps: NarrativeStep[] = [];
  for (const event of events) {
    const kind = narrativeKind(event);
    const label = narrativeLabel(kind, event);
    const previous = steps.at(-1);
    if (previous && previous.kind === kind && shouldGroup(previous, event)) {
      previous.events.push(event);
      previous.summary = event.summary || previous.summary;
      previous.status = mergeStatus(previous.status, event.status);
      previous.title = event.title || previous.title;
      continue;
    }
    steps.push({
      id: `${kind}-${steps.length}-${event.event_id}`,
      kind,
      label,
      title: event.title,
      summary: event.summary || event.content_delta || event.title,
      status: event.status,
      events: [event],
      defaultOpen: kind === "final",
    });
  }
  // Only the last actively-running step expands automatically
  const lastActive = [...steps].reverse().find(
    (s) => s.status === "running" || s.status === "waiting_user"
  );
  if (lastActive) lastActive.defaultOpen = true;
  // If run has ended without a final step, open only the last failed/error step
  const hasFinal = steps.some((s) => s.kind === "final");
  const hasRunning = !!lastActive;
  if (!hasFinal && !hasRunning) {
    const lastFailed = [...steps].reverse().find(
      (s) => s.status === "failed" || s.kind === "error"
    );
    if (lastFailed) lastFailed.defaultOpen = true;
  }

  const finalEvent = [...events].reverse().find((e) => e.type === "final_answer" || e.type === "error");
  const goalEvent = events.find((e) => e.type === "user_message");
  const status = finalEvent?.type === "error" ? "failed" : finalEvent ? "completed" : "running";
  if (status !== "running") {
    for (const step of steps) {
      if (step.status === "running" || step.status === "queued") step.status = "completed";
      step.events = step.events.map((e) =>
        e.status === "running" || e.status === "queued" ? { ...e, status: "completed" } : e
      );
    }
  }
  return {
    steps,
    report: {
      status,
      headline:
        status === "running"
          ? "Agent 正在处理任务。"
          : status === "failed"
          ? "运行遇到了问题。"
          : "运行已完成，并生成了最终结果。",
      goal: (goalEvent?.summary ?? "") as string,
      modelEvents: events.filter(
        (e) => e.type.startsWith("model_") || e.type === "assistant_delta" || e.type === "reasoning_delta"
      ).length,
      toolEvents: events.filter((e) => e.type.startsWith("tool_") || (e.command?.length ?? 0) > 0).length,
      evidenceRefs: countRefs(events, "evidence_refs"),
      artifactRefs: countRefs(events, "artifact_refs"),
      finalText: (finalEvent?.content_delta ?? finalEvent?.summary ?? "") as string,
    },
  };
}

export function parseReportSections(text: string): Record<string, string> {
  const sections: Record<string, string> = {};
  let current = "Result";
  for (const rawLine of String(text || "").split(/\r?\n/)) {
    const heading = rawLine.match(/^##\s+(.+?)\s*$/);
    if (heading) { current = heading[1].trim(); sections[current] = ""; continue; }
    sections[current] = [sections[current], rawLine].filter(Boolean).join("\n").trim();
  }
  return sections;
}

export function summarizeProcess(steps: NarrativeStep[]): string[] {
  const labels = new Set(steps.map((s) => s.label));
  const items: string[] = [];
  if (labels.has("用户目标")) items.push("接收用户目标，并把它固定为本次 run 的任务契约。");
  if (labels.has("思考") || labels.has("结构化生成")) items.push("接收模型输出，把结构化生成归入规划过程。");
  if (labels.has("计划")) items.push("生成任务计划，包含验收条件、运行约束和执行边界。");
  if (labels.has("工具调用") || labels.has("动作")) items.push("调用本地 runtime 命令，并把原始命令输出留在 Inspector。");
  if (labels.has("验证")) items.push("收集验证或审查信号，用于判断结果是否可信。");
  if (labels.has("最终结果")) items.push("将过程折叠成最终报告，明确结论、证据、风险和下一步。");
  return items.length ? items : steps.map((s) => `${s.label}: ${s.summary}`).slice(0, 6);
}

export function firstText(...items: unknown[]): string {
  for (const item of items) {
    const text = String(item ?? "").trim();
    if (text) return text;
  }
  return "";
}

/**
 * Returns true only if the LATEST conversation turn is still active.
 * "Active" means: after the last final_answer/error event, there are events
 * with running/queued/waiting_user status.  This avoids treating stale
 * "running" events from old completed runs as "currently running".
 */
export function isSessionLive(events: StudioEvent[]): boolean {
  const lastFinal = [...events].reverse().find(
    (e) => e.type === "final_answer" || e.type === "error"
  );
  const cutoff = lastFinal?.created_at;
  const liveEvents = cutoff
    ? events.filter((e) => e.created_at > cutoff)
    : events;
  return liveEvents.some(
    (e) => e.status === "running" || e.status === "queued" || e.status === "waiting_user"
  );
}
