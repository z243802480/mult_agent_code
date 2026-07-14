import React, { useEffect, useRef, useState } from "react";
import { FileText, Loader2, MessageCircle, Pause, Send, Square, X } from "lucide-react";
import {
  PERMISSION_TIERS,
  DEFAULT_PERMISSION_TIER,
  legacyPermission,
  type PermissionTierId,
} from "../permissionTiers";
import type { WorkspaceFile } from "../types";
import { loadQueue, saveQueue } from "../session/composerQueue";

const MENTION_LIMIT = 8;

// Locate an active "@token" ending at the caret: an @ at a word boundary, no whitespace between it
// and the caret. Returns the @ index and the query typed after it, or null. Powers @-file mentions.
function activeMention(text: string, caret: number): { start: number; query: string } | null {
  const upto = text.slice(0, caret);
  const at = upto.lastIndexOf("@");
  if (at < 0) return null;
  if (at > 0 && !/\s/.test(text[at - 1])) return null;
  const query = upto.slice(at + 1);
  if (/\s/.test(query)) return null;
  return { start: at, query };
}

function basename(pathValue: string): string {
  const parts = pathValue.split("/");
  return parts[parts.length - 1] || pathValue;
}

const MODES = ["auto", "chat", "plan", "run"] as const;
type Mode = (typeof MODES)[number];

const MODE_LABELS: Record<Mode, string> = {
  auto: "自动",
  chat: "对话",
  plan: "计划",
  run: "目标",
};

// User-facing intent modes only. Lifecycle/maintainer actions (review/resume/accept/finalize) are
// NOT user input modes — they surface as contextual buttons (RuntimeSnapshot / rewind) when
// appropriate, so the user never has to "switch into accept mode" to drive the workflow engine.
const PRIMARY_MODES = ["auto", "chat", "plan", "run"] as const;

// Permission tiers are defined once in ../permissionTiers (shared with the Settings panel and the
// server's PERMISSION_TIER_IDS). This first-class control reaches the runtime's --permission-level
// (server.mjs); ask_everything gates edits up-front, the other two auto-apply edits — shell commands
// still prompt inline in every tier.

const MODE_PLACEHOLDERS: Record<Mode, string> = {
  auto: "给 Asteria 发消息…(Enter 发送，Shift+Enter 换行)",
  chat: "问一个问题…",
  plan: "描述要规划的内容…",
  run: "描述一个目标…",
};

export type PromptSignal = { text: string; id: number };

const SLASH_ACTIONS: {
  key: string;
  label: string;
  mode: Mode;
  prompt: string;
  sideAsk?: boolean;
}[] = [
  { key: "/ask", label: "快速提问", mode: "auto", prompt: "", sideAsk: true },
  { key: "/plan", label: "计划", mode: "plan", prompt: "为其制定计划：" },
  { key: "/goal", label: "目标", mode: "run", prompt: "推进这个目标：" },
];

export function Composer({
  onSend,
  onSideAsk,
  sideAsk = false,
  onSideAskToggle,
  promptSignal,
  viewMode = "focus",
  initialPermissionMode,
  isRunning = false,
  runStateKnown = true,
  onStop,
  onPause,
  files = [],
  sessionId,
}: {
  onSend: (
    message: string,
    mode: string,
    permission: string,
    permissionMode?: string,
  ) => Promise<void>;
  onSideAsk?: (message: string) => Promise<void>;
  sideAsk?: boolean;
  onSideAskToggle?: () => void;
  promptSignal?: PromptSignal;
  viewMode?: import("../hooks/useViewMode").StudioViewMode;
  initialPermissionMode?: PermissionTierId;
  isRunning?: boolean;
  /** False until this session's transcript has been read once — see the queue-flush effect. */
  runStateKnown?: boolean;
  onStop?: () => Promise<void> | void;
  /** Cooperative pause: the run stops at its next turn boundary and can be resumed. */
  onPause?: () => Promise<void> | void;
  files?: WorkspaceFile[];
  /** Scopes the persisted queue so lined-up messages belong to the session they were typed in. */
  sessionId?: string;
}) {
  const [message, setMessage] = useState("");
  const [mode, setMode] = useState<Mode>("auto");
  const [permissionMode, setPermissionMode] = useState<PermissionTierId>(
    initialPermissionMode ?? DEFAULT_PERMISSION_TIER,
  );
  const permission = legacyPermission(permissionMode);
  const [sending, setSending] = useState(false);
  // Messages typed while a run is in flight (I9). They wait honestly for the run to finish, then
  // auto-send at the turn boundary — we never claim to inject mid-step, which the runtime can't honor.
  // Seeded from (and mirrored to) per-session storage: these used to live in memory only, so a
  // refresh dropped the user's lined-up instructions without a word. See composerQueue.ts.
  const [queue, setQueue] = useState<string[]>(() => loadQueue(sessionId ?? ""));
  useEffect(() => {
    saveQueue(sessionId ?? "", queue);
  }, [sessionId, queue]);
  const wasRunning = useRef(false);
  // @-file mention (mainstream coding-agent affordance): type @ to point the agent at a workspace
  // file. The path is inserted as text; the runtime reads it via its file tools — no backend change.
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const pendingCaretRef = useRef<number | null>(null);
  const [mention, setMention] = useState<{ start: number; query: string } | null>(null);
  const [mentionIndex, setMentionIndex] = useState(0);

  const mentionMatches = mention
    ? files
        .filter((file) => file.path.toLowerCase().includes(mention.query.toLowerCase()))
        .slice(0, MENTION_LIMIT)
    : [];
  const mentionOpen = mentionMatches.length > 0;

  function syncMention(text: string, caret: number) {
    setMention(activeMention(text, caret));
    setMentionIndex(0);
  }

  function insertMention(file: WorkspaceFile) {
    const el = textareaRef.current;
    const caret = el ? el.selectionStart : message.length;
    const m = activeMention(message, caret) ?? mention;
    if (!m) return;
    const before = message.slice(0, m.start);
    const after = message.slice(caret);
    const inserted = `@${file.path} `;
    pendingCaretRef.current = (before + inserted).length;
    setMessage(before + inserted + after);
    setMention(null);
  }

  // Restore the caret after an insert re-renders the textarea (keeps typing flowing after the path).
  useEffect(() => {
    if (pendingCaretRef.current == null || !textareaRef.current) return;
    const pos = pendingCaretRef.current;
    pendingCaretRef.current = null;
    textareaRef.current.focus();
    textareaRef.current.setSelectionRange(pos, pos);
  }, [message]);

  // Auto-grow the textarea with its content (up to a max, then scroll) — mainstream composer
  // behavior. Resets cleanly when the message clears after send.
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [message]);

  // Reflect a newly-saved default tier (Settings panel) in the composer control immediately. Fires
  // only when the persisted default value actually changes, so a per-message override picked this
  // session survives unrelated re-renders.
  React.useEffect(() => {
    if (initialPermissionMode) setPermissionMode(initialPermissionMode);
  }, [initialPermissionMode]);

  React.useEffect(() => {
    if (promptSignal?.text) {
      setMessage(promptSignal.text);
      setMode((prev) => (prev === "auto" || prev === "chat" ? "plan" : prev));
    }
  }, [promptSignal?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const text = message.trim();
    if (!text) return;
    // Run in flight (main thread): enqueue instead of sending, so the user can line up the next
    // instruction without waiting. Side-ask questions are off-thread and send immediately.
    if (isRunning && !sideAsk) {
      setQueue((q) => [...q, text]);
      setMessage("");
      return;
    }
    setMessage("");
    setSending(true);
    try {
      if (sideAsk && onSideAsk) {
        await onSideAsk(text);
      } else {
        await onSend(text, mode, permission, permissionMode);
      }
    } finally {
      setSending(false);
    }
  }

  // Flush the head of the queue whenever the session is idle. One at a time at the turn boundary;
  // each queued item's own run then unblocks the next.
  //
  // Gated on runStateKnown, not on a running→idle transition. The transition gate meant a queue
  // RESTORED after a refresh never flushed (no transition ever happened) — it just sat there. But we
  // also cannot flush the moment we mount: before the transcript is read, `isRunning` is false only
  // because we have not looked yet, and sending then would fire a message into a still-live run.
  useEffect(() => {
    if (runStateKnown && !isRunning && queue.length > 0 && !sending) {
      const [head, ...rest] = queue;
      setQueue(rest);
      setSending(true);
      Promise.resolve(onSend(head, mode, permission, permissionMode)).finally(() =>
        setSending(false),
      );
    }
    wasRunning.current = isRunning;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isRunning, runStateKnown, queue.length, sending]);

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    // Mention menu owns the keyboard while open: navigate + insert instead of send/stop.
    if (mentionOpen) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setMentionIndex((i) => (i + 1) % mentionMatches.length);
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setMentionIndex((i) => (i - 1 + mentionMatches.length) % mentionMatches.length);
        return;
      }
      if (e.key === "Enter" || e.key === "Tab") {
        e.preventDefault();
        insertMention(mentionMatches[mentionIndex]);
        return;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        setMention(null);
        return;
      }
    }
    if (e.key === "Escape" && isRunning && onStop && !sideAsk) {
      e.preventDefault();
      void onStop();
      return;
    }
    if (e.key !== "Enter") return;
    if (e.shiftKey) return;
    e.preventDefault();
    void submit(e as unknown as React.FormEvent);
  }

  const isAuto = mode === "auto" && !sideAsk;
  const isChat = mode === "chat" || sideAsk;
  const showPermission = !sideAsk && (mode === "auto" || mode === "run");
  const placeholder = sideAsk
    ? "快速提问 — 不占主线程，带会话上下文（Enter 发送）…"
    : isRunning
      ? "排一条后续消息…（运行结束后发送 · Esc 停止）"
      : MODE_PLACEHOLDERS[mode];
  const slashOpen = message.trim() === "/" || /^\/[a-z]*$/i.test(message.trim());
  const slashQuery = message.trim().toLowerCase();
  const slashActions = slashOpen
    ? SLASH_ACTIONS.filter((action) =>
        action.key.startsWith(slashQuery === "/" ? "/" : slashQuery),
      ).slice(0, 5)
    : [];

  return (
    <form
      className={`composer compact ${isAuto ? "autoMode" : isChat ? "chatMode" : ""}${sideAsk ? " sideAskMode" : ""}`}
      onSubmit={(event) => void submit(event)}
    >
      {queue.length > 0 && (
        <div className="composerQueue" role="status" aria-live="polite">
          <span className="composerQueueLabel">{queue.length} 条已排队 · 运行结束后发送</span>
          {queue.map((q, i) => (
            <span key={i} className="composerQueueChip" title={q}>
              <span className="composerQueueText">{q}</span>
              <button
                type="button"
                onClick={() => setQueue((qs) => qs.filter((_, j) => j !== i))}
                aria-label="移除排队消息"
              >
                <X size={11} />
              </button>
            </span>
          ))}
        </div>
      )}
      <div className="composerInputWrap">
        <textarea
          ref={textareaRef}
          value={message}
          onChange={(event) => {
            setMessage(event.target.value);
            syncMention(event.target.value, event.target.selectionStart);
          }}
          onClick={(event) => syncMention(message, event.currentTarget.selectionStart)}
          onKeyDown={onKeyDown}
          placeholder={placeholder}
          rows={1}
        />
        {mentionOpen && (
          <div className="mentionMenu" role="listbox" aria-label="工作区文件">
            {mentionMatches.map((file, i) => (
              <button
                type="button"
                key={file.path}
                role="option"
                aria-selected={i === mentionIndex}
                className={i === mentionIndex ? "mentionOption active" : "mentionOption"}
                onMouseDown={(event) => event.preventDefault()}
                onMouseEnter={() => setMentionIndex(i)}
                onClick={() => insertMention(file)}
              >
                <FileText size={12} />
                <span className="mentionName">{basename(file.path)}</span>
                <span className="mentionPath">{file.path}</span>
              </button>
            ))}
          </div>
        )}
        {sideAsk && (
          <p className="composerSideAskHint muted">回答显示在快速提问区——主目标留在主线程。</p>
        )}
        {slashActions.length > 0 && (
          <div className="slashMenu">
            {slashActions.map((action) => (
              <button
                type="button"
                key={action.key}
                disabled={sending}
                onClick={() => {
                  setMode(action.mode);
                  setMessage(action.prompt);
                  if (action.sideAsk && !sideAsk) onSideAskToggle?.();
                }}
              >
                <strong>{action.label}</strong>
                <span>{action.key}</span>
              </button>
            ))}
          </div>
        )}
      </div>
      <div className="composerFooter">
        <div className="composerModeGroup">
          {onSideAskToggle && (
            <button
              type="button"
              className={sideAsk ? "composerSideAskToggle active" : "composerSideAskToggle"}
              title="快速提问 — 不占主线程，带会话上下文"
              aria-pressed={sideAsk}
              onClick={onSideAskToggle}
            >
              <MessageCircle size={13} />
              <span>快速提问</span>
            </button>
          )}
          {/* Two compact dropdowns instead of 7 radio buttons: a mainstream composer exposes at most
              a mode picker — the fine-grained controls collapse into selects so the input bar reads
              clean. All modes/tiers and their runtime wiring are unchanged. */}
          {!sideAsk && (
            <label className="composerSelect" title="模式">
              <select
                value={mode}
                onChange={(event) => setMode(event.target.value as Mode)}
                aria-label="模式"
              >
                {PRIMARY_MODES.map((item) => (
                  <option key={item} value={item}>
                    {MODE_LABELS[item]}
                  </option>
                ))}
              </select>
            </label>
          )}
          {showPermission && (
            <label className="composerSelect" title="权限 — Asteria 无需询问可自行完成多少">
              <select
                value={permissionMode}
                onChange={(event) => setPermissionMode(event.target.value as PermissionTierId)}
                aria-label="权限档"
              >
                {PERMISSION_TIERS.map((tier) => (
                  <option key={tier.id} value={tier.id}>
                    {tier.label}
                  </option>
                ))}
              </select>
            </label>
          )}
        </div>
        {isRunning && onStop && !sideAsk ? (
          <>
            {onPause && (
              // Pause sits BEFORE Stop and is the quieter of the two: it is the recoverable one.
              // Stop kills the process — the work in flight is gone. Pause lets the run finish its
              // current step, exit cleanly, and be resumed.
              <button
                className="composerSend composerPause"
                type="button"
                onClick={() => void onPause()}
                title="在当前这一步做完后暂停（可继续）"
              >
                <Pause size={14} />
                <span>暂停</span>
              </button>
            )}
            <button
              className="composerSend composerStop"
              type="button"
              onClick={() => void onStop()}
              title="停止正在运行的任务（不可恢复）"
            >
              <Square size={14} />
              <span>停止</span>
            </button>
          </>
        ) : (
          <button className="composerSend" disabled={sending} type="submit">
            {sending ? <Loader2 size={15} className="spinning" /> : <Send size={15} />}
            <span>{isChat ? "提问" : "发送"}</span>
          </button>
        )}
      </div>
    </form>
  );
}
