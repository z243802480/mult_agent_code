import React, { useState } from "react";
import { RotateCcw } from "lucide-react";
import type { RunDetailPayload } from "../../types";
import type { StudioViewMode } from "../../hooks/useViewMode";
import { planTurnRewind } from "./turnRewind";

export function TurnRewindButton({
  turnIndex,
  isLast,
  isRunning,
  runDetail,
  viewMode,
  onRewind,
}: {
  turnIndex: number;
  isLast: boolean;
  isRunning: boolean;
  runDetail: RunDetailPayload | null | undefined;
  viewMode: StudioViewMode;
  onRewind: (turnIndex: number, action: string) => Promise<void>;
}) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const plan = planTurnRewind(runDetail, isRunning);

  if (isLast) return null;
  if (viewMode === "focus") return null;

  const disabled = plan.disabled || busy;

  async function confirmRewind() {
    if (!plan.action || disabled) return;
    setBusy(true);
    try {
      await onRewind(turnIndex, plan.action);
      setConfirming(false);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="turnRewindWrap">
      {!confirming ? (
        <button
          type="button"
          className="turnRewindButton"
          title={plan.disabledReason ?? plan.reason}
          disabled={disabled}
          onClick={() => setConfirming(true)}
        >
          <RotateCcw size={12} />
          <span>{plan.label}</span>
        </button>
      ) : (
        <div className="turnRewindConfirm" role="dialog" aria-label="确认回退">
          <p>{plan.reason}</p>
          <div className="turnRewindConfirmActions">
            <button type="button" onClick={() => setConfirming(false)} disabled={busy}>
              取消
            </button>
            <button
              type="button"
              className="primary"
              onClick={() => void confirmRewind()}
              disabled={busy}
            >
              {busy ? "执行中…" : plan.label}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
