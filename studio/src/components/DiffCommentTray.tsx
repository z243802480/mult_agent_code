import React, { useState } from "react";
import { ChevronDown, ChevronRight, MessageSquare, X } from "lucide-react";
import {
  clearDiffComments,
  formatCommentsMessage,
  removeDiffComment,
  useDiffComments,
} from "../session/diffComments";

/**
 * Pending diff-comment tray (G4 评论即指令) — GitHub "pending review" semantics: line comments
 * accumulate here and nothing reaches the model until 提交. Submit routes through the EXISTING
 * channels: mid-run steer while a run is in flight (delivered at the next turn boundary — labeled
 * honestly), a normal new turn when idle. Comments are only cleared after the channel reports
 * success, so a failed delivery never eats the user's written feedback.
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
  const comments = useDiffComments();
  const [open, setOpen] = useState(false);
  const [sending, setSending] = useState(false);
  if (!comments.length) return null;

  const channel = pickCommentChannel(isRunning, midRunSteer, Boolean(onSteer));
  const blocked = channel === "blocked";

  async function submit() {
    const message = formatCommentsMessage(comments);
    setSending(true);
    try {
      const result =
        channel === "steer" && onSteer ? await onSteer(message) : await onSend(message);
      // Only a reported failure (false) keeps the batch; void-returning channels clear as before.
      if (result !== false) clearDiffComments();
    } finally {
      setSending(false);
    }
  }

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
        <span>{comments.length} 条 diff 行评论待提交</span>
      </button>
      {open && (
        <ul className="diffCommentTrayList">
          {comments.map((item) => (
            <li key={item.id} className="diffCommentTrayItem">
              <span className="diffCommentTrayAnchor">
                {item.file}
                {item.line != null ? `:${item.line}` : ""}
              </span>
              <span className="diffCommentTrayText" title={item.text}>
                {item.text}
              </span>
              <button
                type="button"
                className="diffCommentRemove"
                title="删除这条评论"
                aria-label={`删除对 ${item.file} 的评论`}
                onClick={() => removeDiffComment(item.id)}
              >
                <X size={12} />
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="diffCommentTrayActions">
        <button
          type="button"
          className="diffActionButton"
          disabled={sending}
          onClick={() => clearDiffComments()}
        >
          清空
        </button>
        <button
          type="button"
          className="diffActionButton primary"
          disabled={sending || blocked}
          title={blocked ? "运行中且未开启中途插话——等本轮结束后再提交。" : undefined}
          onClick={() => void submit()}
        >
          {isRunning && !blocked ? "提交 · 下一轮生效" : "提交评论"}
        </button>
      </div>
    </div>
  );
}
