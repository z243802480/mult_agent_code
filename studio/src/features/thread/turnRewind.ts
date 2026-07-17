import type { RunDetailPayload, StudioEvent } from "../../types";
import { firstText } from "../../narrative";

/**
 * Per-turn snapshot anchors computed from the RAW main-thread events, matched to turns by time
 * window. The narrative layer legitimately drops some settle events from steps (e.g. a
 * pointer-only final_report is loop scaffolding), so scanning a turn's rendered steps can miss the
 * anchor even though the transcript has it — caught live on a run with no conversational recap.
 * `turnStarts` are each turn's first-event created_at values (chronological).
 */
export function turnSnapshotMap(
  turnStarts: (string | undefined)[],
  events: StudioEvent[],
): (string | null)[] {
  const bounds = turnStarts.map((value) => {
    const parsed = Date.parse(String(value ?? ""));
    return Number.isFinite(parsed) ? parsed : null;
  });
  const result: (string | null)[] = turnStarts.map(() => null);
  for (const event of events) {
    const value = (event.data as Record<string, unknown> | undefined)?.workspace_snapshot;
    if (typeof value !== "string" || !value.trim()) continue;
    const ts = Date.parse(String(event.created_at ?? ""));
    if (!Number.isFinite(ts)) continue;
    // The snapshot belongs to the LAST turn that started at or before it.
    let turn = -1;
    for (let i = 0; i < bounds.length; i++) {
      if (bounds[i] != null && bounds[i]! <= ts) turn = i;
    }
    if (turn >= 0) result[turn] = value.trim();
  }
  return result;
}

export type TurnRewindPlan = {
  action: string;
  label: string;
  reason: string;
  disabled: boolean;
  disabledReason?: string;
};

export function planTurnRewind(
  runDetail: RunDetailPayload | null | undefined,
  isRunning: boolean,
): TurnRewindPlan {
  if (!runDetail?.ok || !runDetail.run_id) {
    return {
      action: "",
      label: "从这里接着做",
      reason: "从这一轮接着做。",
      disabled: true,
      disabledReason: "还没有可以接着做的内容。",
    };
  }
  if (isRunning) {
    return {
      action: "",
      label: "从这里接着做",
      reason: "请先等当前这一轮结束。",
      disabled: true,
      disabledReason: "还有一轮正在进行中。",
    };
  }

  const progress = (runDetail.runtime_progress ?? {}) as Record<string, unknown>;
  const loop = (progress.loop ?? {}) as Record<string, unknown>;
  const mainAction = (runDetail.main_action ?? {}) as Record<string, unknown>;
  const recommended = firstText(
    mainAction.next_command,
    progress.next_command,
    loop.recommended_next_command,
    runDetail.final_report_summary?.recommended_next_command,
    runDetail.run_loop_summary?.recommended_next_command,
  )
    .replace(/^asteria\s+/i, "")
    .trim();

  let action = recommended;
  if (!action || /^accept\b/i.test(action)) {
    action = "resume";
  } else if (/^replan\b/i.test(action)) {
    action = "resume";
  } else if (/^continue\b/i.test(action)) {
    action = "resume";
  }

  const label = /^review\b/i.test(action)
    ? "从这里重做"
    : /^resume\b/i.test(action) || /^continue\b/i.test(action)
      ? "从这里继续"
      : "从这里继续";

  return {
    action,
    label,
    reason: "从这里接着做。工作区文件不会自动回滚。",
    disabled: false,
  };
}
