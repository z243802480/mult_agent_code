import React, { useEffect, useRef, useState } from "react";
import { ClipboardList, Loader2, MessageCircle, PlayCircle, Send, ShieldCheck, Square, X } from "lucide-react";
import { PERMISSION_TIERS, DEFAULT_PERMISSION_TIER, legacyPermission, type PermissionTierId } from "../permissionTiers";

const MODES = ["auto", "chat", "plan", "run"] as const;
type Mode = typeof MODES[number];

const MODE_LABELS: Record<Mode, string> = {
  auto: "Auto",
  chat: "Chat",
  plan: "Plan",
  run: "Goal",
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
  auto: "Message Asteria… (Enter send, Shift+Enter newline)",
  chat: "Ask a question…",
  plan: "Describe what to plan…",
  run: "Describe a goal…",
};

export type PromptSignal = { text: string; id: number };

const SLASH_ACTIONS: { key: string; label: string; mode: Mode; prompt: string; sideAsk?: boolean }[] = [
  { key: "/ask", label: "Quick ask", mode: "auto", prompt: "", sideAsk: true },
  { key: "/plan", label: "Plan", mode: "plan", prompt: "Create a plan for " },
  { key: "/goal", label: "Goal", mode: "run", prompt: "Work on this goal: " },
];

function actionProfile(mode: Mode, permission: string) {
  const effective = mode === "auto" ? "auto" : mode;
  if (effective === "chat") {
    return { icon: <MessageCircle size={13} />, label: "Chat", permission: "Read-only", tone: "good" as const };
  }
  if (effective === "plan") {
    return { icon: <ClipboardList size={13} />, label: "Plan", permission: "Read-only", tone: "good" as const };
  }
  if (effective === "run") {
    return {
      icon: <PlayCircle size={13} />,
      label: "Goal",
      permission: permission === "allow" ? "Safe actions" : "Ask first",
      tone: (permission === "allow" ? "warn" : "neutral") as "warn" | "neutral",
    };
  }
  return {
    icon: <ShieldCheck size={13} />,
    label: "Auto",
    permission: permission === "allow" ? "Safe actions" : "Ask first",
    tone: (permission === "allow" ? "warn" : "neutral") as "warn" | "neutral",
  };
}

export function Composer({
  onSend,
  onSideAsk,
  sideAsk = false,
  onSideAskToggle,
  promptSignal,
  viewMode = "focus",
  initialPermissionMode,
  isRunning = false,
  onStop,
}: {
  onSend: (message: string, mode: string, permission: string, permissionMode?: string) => Promise<void>;
  onSideAsk?: (message: string) => Promise<void>;
  sideAsk?: boolean;
  onSideAskToggle?: () => void;
  promptSignal?: PromptSignal;
  viewMode?: import("../hooks/useViewMode").StudioViewMode;
  initialPermissionMode?: PermissionTierId;
  isRunning?: boolean;
  onStop?: () => Promise<void> | void;
}) {
  const [message, setMessage] = useState("");
  const [mode, setMode] = useState<Mode>("auto");
  const [permissionMode, setPermissionMode] = useState<PermissionTierId>(initialPermissionMode ?? DEFAULT_PERMISSION_TIER);
  const permission = legacyPermission(permissionMode);
  const [sending, setSending] = useState(false);
  // Messages typed while a run is in flight (I9). They wait honestly for the run to finish, then
  // auto-send at the turn boundary — we never claim to inject mid-step, which the runtime can't honor.
  const [queue, setQueue] = useState<string[]>([]);
  const wasRunning = useRef(false);

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

  // Flush the head of the queue when the current run finishes (isRunning true→false). One at a time
  // at the turn boundary; each queued item's own run then unblocks the next.
  useEffect(() => {
    if (wasRunning.current && !isRunning && queue.length > 0 && !sending) {
      const [head, ...rest] = queue;
      setQueue(rest);
      setSending(true);
      Promise.resolve(onSend(head, mode, permission, permissionMode)).finally(() => setSending(false));
    }
    wasRunning.current = isRunning;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isRunning, queue.length]);

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
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
  const profile = sideAsk
    ? { icon: <MessageCircle size={13} />, label: "Quick ask", permission: "Off-thread", tone: "good" as const }
    : actionProfile(mode, permission);
  const placeholder = sideAsk
    ? "Quick ask — off-thread, with session context (Enter send)…"
    : isRunning
      ? "Queue a follow-up… (sends when the run finishes · Esc to stop)"
      : MODE_PLACEHOLDERS[mode];
  const slashOpen = message.trim() === "/" || /^\/[a-z]*$/i.test(message.trim());
  const slashQuery = message.trim().toLowerCase();
  const slashActions = slashOpen
    ? SLASH_ACTIONS.filter((action) => action.key.startsWith(slashQuery === "/" ? "/" : slashQuery)).slice(0, 5)
    : [];

  return (
    <form className={`composer compact ${isAuto ? "autoMode" : isChat ? "chatMode" : ""}${sideAsk ? " sideAskMode" : ""}`} onSubmit={(event) => void submit(event)}>
      {queue.length > 0 && (
        <div className="composerQueue">
          <span className="composerQueueLabel">Queued · sends when the run finishes</span>
          {queue.map((q, i) => (
            <span key={i} className="composerQueueChip" title={q}>
              <span className="composerQueueText">{q}</span>
              <button type="button" onClick={() => setQueue((qs) => qs.filter((_, j) => j !== i))} aria-label="Remove queued message">
                <X size={11} />
              </button>
            </span>
          ))}
        </div>
      )}
      <div className="composerInputWrap">
        <textarea
          value={message}
          onChange={(event) => setMessage(event.target.value)}
          onKeyDown={onKeyDown}
          placeholder={placeholder}
          rows={1}
        />
        {sideAsk && (
          <p className="composerSideAskHint muted">Answers appear in Quick ask — main goal stays on the thread.</p>
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
              title="Quick ask — off-thread with session context"
              aria-pressed={sideAsk}
              onClick={onSideAskToggle}
            >
              <MessageCircle size={13} />
              <span>Quick ask</span>
            </button>
          )}
          {!sideAsk && (
            <>
              <div className="segmented composerModeSegmented" role="radiogroup" aria-label="Mode">
                {PRIMARY_MODES.map((item) => (
                  <button
                    type="button"
                    key={item}
                    role="radio"
                    aria-checked={mode === item}
                    className={mode === item ? "active" : ""}
                    onClick={() => setMode(item)}
                  >
                    {MODE_LABELS[item]}
                  </button>
                ))}
              </div>
            </>
          )}
          {showPermission && (
            <div className="segmented composerPermissionSegmented" role="radiogroup" aria-label="Permission tier">
              {PERMISSION_TIERS.map((tier) => (
                <button
                  type="button"
                  key={tier.id}
                  role="radio"
                  aria-checked={permissionMode === tier.id}
                  className={permissionMode === tier.id ? "active" : ""}
                  title={tier.hint}
                  onClick={() => setPermissionMode(tier.id)}
                >
                  {tier.label}
                </button>
              ))}
            </div>
          )}
          <span className="composerPermissionHint">{profile.permission}</span>
        </div>
        {isRunning && onStop && !sideAsk ? (
          <button className="composerSend composerStop" type="button" onClick={() => void onStop()} title="Stop the running task">
            <Square size={14} />
            <span>Stop</span>
          </button>
        ) : (
          <button className="composerSend" disabled={sending} type="submit">
            {sending ? <Loader2 size={15} className="spinning" /> : <Send size={15} />}
            <span>{isChat ? "Ask" : "Send"}</span>
          </button>
        )}
      </div>
    </form>
  );
}
