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
      label: "Pick up from here",
      reason: "Pick up from this turn.",
      disabled: true,
      disabledReason: "Nothing to pick up from yet.",
    };
  }
  if (isRunning) {
    return {
      action: "",
      label: "Pick up from here",
      reason: "Wait for the current turn to finish first.",
      disabled: true,
      disabledReason: "A turn is still in progress.",
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
    ? "Redo from here"
    : /^resume\b/i.test(action) || /^continue\b/i.test(action)
      ? "Continue from here"
      : "Continue from here";

  return {
    action,
    label,
    reason: "Pick up from here. Workspace files are not rolled back automatically.",
    disabled: false,
  };
}
