import React, { useState } from "react";
import { ChevronDown, ChevronRight, MessageSquare, X } from "lucide-react";
import {
  clearDiffComments,
  formatCommentsMessage,
  removeDiffComment,
  useDiffComments,
} from "../session/diffComments";
import {
  clearPlanComments,
  formatPlanCommentsMessage,
  removePlanComment,
  usePlanComments,
} from "../session/planComments";

/**
 * Pending feedback tray (G4 diff 行评 + G6 计划步骤意见) — GitHub "pending review" semantics:
 * comments accumulate here and nothing reaches the model until 提交. Submit routes through the
 * EXISTING channels: mid-run steer while a run is in flight (delivered at the next turn boundary —
 * labeled honestly), a normal new turn when idle. Comments are only cleared after the channel
 * reports success, so a failed delivery never eats the user's written feedback.
 */
/**
 * Which existing channel carries the batched comment message. Pure so the routing table is
 * unit-testable: running + steer → mid-run steer; idle → a normal new turn; running with steer
 * opted out → blocked (there is no honest way to deliver now, and we say so instead of queueing
 * behind the user's back).
 */
export function pickCommentChannel(
  isRunning: boolean,
  midRunSteer: boolean,
  hasSteer: boolean,
): "steer" | "send" | "blocked" {
  if (!isRunning) return "send";
  return midRunSteer && hasSteer ? "steer" : "blocked";
}

/** The one batched message: each pending kind contributes its own section. */
export function buildFeedbackMessage(
  diffComments: Parameters<typeof formatCommentsMessage>[0],
  planComments: Parameters<typeof formatPlanCommentsMessage>[0],
): string {
  return [
    diffComments.length ? formatCommentsMessage(diffComments) : null,
    planComments.length ? formatPlanCommentsMessage(planComments) : null,
  ]
    .filter(Boolean)
    .join("\n\n");
}

function trayLabel(diffCount: number, planCount: number): string {
  if (diffCount && planCount)
    return `${diffCount + planCount} 条意见待提交（diff ${diffCount} · 计划 ${planCount}）`;
  if (planCount) return `${planCount} 条计划意见待提交`;
  return `${diffCount} 条 diff 行评论待提交`;
}

export function DiffCommentTray({
  isRunning,
  midRunSteer,
  onSteer,
  onSend,
}: {
  isRunning: boolean;
  midRunSteer: boolean;
  /** Mid-run channel; resolves false when delivery failed. */
  onSteer?: (message: string) => Promise<boolean | void> | void;
  /** Idle channel (a normal turn); resolves false when delivery failed. */
  onSend: (message: string) => Promise<boolean | void>;
}) {
  const diffComments = useDiffComments();
  const planComments = usePlanComments();
  const [open, setOpen] = useState(false);
  const [sending, setSending] = useState(false);
  if (!diffComments.length && !planComments.length) return null;

  const channel = pickCommentChannel(isRunning, midRunSteer, Boolean(onSteer));
  const blocked = channel === "blocked";

  function clearAll() {
    clearDiffComments();
    clearPlanComments();
  }

  async function submit() {
    const message = buildFeedbackMessage(diffComments, planComments);
    setSending(true);
    try {
      const result =
        channel === "steer" && onSteer ? await onSteer(message) : await onSend(message);
      // Only a reported failure (false) keeps the batch; void-returning channels clear as before.
      if (result !== false) clearAll();
    } finally {
      setSending(false);
    }
  }

  const rows = [
    ...diffComments.map((item) => ({
      id: item.id,
      anchor: `${item.file}${item.line != null ? `:${item.line}` : ""}`,
      text: item.text,
      remove: () => removeDiffComment(item.id),
    })),
    ...planComments.map((item) => ({
      id: item.id,
      anchor: `计划第 ${item.step} 步`,
      text: item.text,
      remove: () => removePlanComment(item.id),
    })),
  ];

  return (
    <div className="diffCommentTray">
      <button
        type="button"
        className="diffCommentTrayHead"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
      >
        {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
        <MessageSquare size={13} />
        <span>{trayLabel(diffComments.length, planComments.length)}</span>
      </button>
      {open && (
        <ul className="diffCommentTrayList">
          {rows.map((row) => (
            <li key={row.id} className="diffCommentTrayItem">
              <span className="diffCommentTrayAnchor">{row.anchor}</span>
              <span className="diffCommentTrayText" title={row.text}>
                {row.text}
              </span>
              <button
                type="button"
                className="diffCommentRemove"
                title="删除这条意见"
                aria-label={`删除对 ${row.anchor} 的意见`}
                onClick={row.remove}
              >
                <X size={12} />
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="diffCommentTrayActions">
        <button type="button" className="diffActionButton" disabled={sending} onClick={clearAll}>
          清空
        </button>
        <button
          type="button"
          className="diffActionButton primary"
          disabled={sending || blocked}
          title={blocked ? "运行中且未开启中途插话——等本轮结束后再提交。" : undefined}
          onClick={() => void submit()}
        >
          {isRunning && !blocked ? "提交 · 下一轮生效" : "提交意见"}
        </button>
      </div>
    </div>
  );
}
