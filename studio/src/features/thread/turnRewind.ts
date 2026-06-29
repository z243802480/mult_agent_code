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
      label: "Rewind",
      reason: "Continue from this turn using the active run.",
      disabled: true,
      disabledReason: "No active run to rewind.",
    };
  }
  if (isRunning) {
    return {
      action: "",
      label: "Rewind",
      reason: "Wait for the current turn to finish before rewinding.",
      disabled: true,
      disabledReason: "A turn is still running.",
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
    ? "Rewind → Review"
    : /^resume\b/i.test(action) || /^continue\b/i.test(action)
      ? "Rewind → Continue"
      : "Rewind → Continue";

  return {
    action,
    label,
    reason: "Request runtime to continue from this point. Workspace files are not rolled back automatically.",
    disabled: false,
  };
}
