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
import {
  clearPlanRevision,
  countChangedLines,
  formatPlanRevisionMessage,
  usePlanRevision,
  type PlanRevision,
} from "../session/planRevision";

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

/**
 * The one batched message: each pending kind contributes its own section. The rewritten plan goes
 * LAST — the per-step comments are constraints on the plan being replaced, so the model should read
 * them before the plan they apply to.
 */
export function buildFeedbackMessage(
  diffComments: Parameters<typeof formatCommentsMessage>[0],
  planComments: Parameters<typeof formatPlanCommentsMessage>[0],
  planRevision?: PlanRevision | null,
): string {
  return [
    diffComments.length ? formatCommentsMessage(diffComments) : null,
    planComments.length ? formatPlanCommentsMessage(planComments) : null,
    planRevision ? formatPlanRevisionMessage(planRevision) : null,
  ]
    .filter(Boolean)
    .join("\n\n");
}

// The rewritten plan joins the existing breakdown as one more part; the mixed-batch wording is
// deliberately left byte-identical to 刀一's, because changing copy the user already reads is not
// this knife's job.
function trayLabel(diffCount: number, planCount: number, revisionCount: number): string {
  const parts: string[] = [];
  if (diffCount) parts.push(`diff ${diffCount}`);
  if (planCount) parts.push(`计划 ${planCount}`);
  if (revisionCount) parts.push("改过的计划");
  if (parts.length > 1) {
    return `${diffCount + planCount + revisionCount} 条意见待提交（${parts.join(" · ")}）`;
  }
  if (revisionCount) return "改过的计划待提交";
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
  const planRevision = usePlanRevision();
  const [open, setOpen] = useState(false);
  const [sending, setSending] = useState(false);
  if (!diffComments.length && !planComments.length && !planRevision) return null;

  const channel = pickCommentChannel(isRunning, midRunSteer, Boolean(onSteer));
  const blocked = channel === "blocked";

  function clearAll() {
    clearDiffComments();
    clearPlanComments();
    clearPlanRevision();
  }

  async function submit() {
    const message = buildFeedbackMessage(diffComments, planComments, planRevision);
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
    ...(planRevision
      ? [
          {
            id: "plan-revision",
            anchor: `改过的计划（${countChangedLines(planRevision)} 处不同）`,
            text: planRevision.text,
            remove: clearPlanRevision,
          },
        ]
      : []),
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
        <span>{trayLabel(diffComments.length, planComments.length, planRevision ? 1 : 0)}</span>
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
