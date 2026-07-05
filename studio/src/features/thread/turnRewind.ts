import type { RunDetailPayload } from "../../types";
import { firstText } from "../../narrative";

export type TurnRewindPlan = {
  action: string;
  label: string;
  reason: string;
  disabled: boolean;
  disabledReason?: string;
};

export function planTurnRewind(runDetail: RunDetailPayload | null | undefined, isRunning: boolean): TurnRewindPlan {
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
  ).replace(/^asteria\s+/i, "").trim();

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
