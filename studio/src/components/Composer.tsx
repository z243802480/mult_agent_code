import React, { useState } from "react";
import { ClipboardList, Eye, Loader2, MessageCircle, PlayCircle, RotateCw, Send, ShieldCheck } from "lucide-react";

const MODES = ["auto", "chat", "plan", "run", "review", "resume", "accept"] as const;
type Mode = typeof MODES[number];

const MODE_LABELS: Record<Mode, string> = {
  auto: "Auto",
  chat: "Chat",
  plan: "Plan",
  run: "Goal",
  review: "Review",
  resume: "Resume",
  accept: "Accept",
};

// Intent modes ride an inline segmented control; lifecycle/maintainer actions
// (review/resume/accept) live behind an overflow menu — same string set, no
// backend change. (reference-first B5: mainstream main-modes are 2-3, never a flat 7-row.)
const PRIMARY_MODES = ["auto", "chat", "plan", "run"] as const;
const OVERFLOW_MODES = ["review", "resume", "accept"] as const;

const MODE_PLACEHOLDERS: Record<Mode, string> = {
  auto: "Message Asteria… (Enter send, Shift+Enter newline)",
  chat: "Ask a question…",
  plan: "Describe what to plan…",
  run: "Describe a goal…",
  review: "Ask to review the result…",
  resume: "Continue or add constraints…",
  accept: "Accept the reviewed result…",
};

export type PromptSignal = { text: string; id: number };

const SLASH_ACTIONS: { key: string; label: string; mode: Mode; prompt: string; sideAsk?: boolean }[] = [
  { key: "/ask", label: "Quick ask", mode: "auto", prompt: "", sideAsk: true },
  { key: "/plan", label: "Plan", mode: "plan", prompt: "Create a plan for " },
  { key: "/goal", label: "Goal", mode: "run", prompt: "Work on this goal: " },
  { key: "/review", label: "Review", mode: "review", prompt: "Review the current result." },
  { key: "/accept", label: "Finalize", mode: "accept", prompt: "Finalize the reviewed result." },
  { key: "/debug", label: "Debug", mode: "resume", prompt: "Debug the current blocker." },
  { key: "/continue", label: "Continue", mode: "resume", prompt: "Continue the current task." },
];

function actionProfile(mode: Mode, permission: string) {
  const effective = mode === "auto" ? "auto" : mode;
  if (effective === "chat") {
    return { icon: <MessageCircle size={13} />, label: "Chat", permission: "Read-only", tone: "good" as const };
  }
  if (effective === "plan") {
    return { icon: <ClipboardList size={13} />, label: "Plan", permission: "Read-only", tone: "good" as const };
  }
  if (effective === "review") {
    return { icon: <Eye size={13} />, label: "Review", permission: "Read-only", tone: "good" as const };
  }
  if (effective === "accept") {
    return { icon: <ShieldCheck size={13} />, label: "Finalize", permission: "Applied", tone: "warn" as const };
  }
  if (effective === "resume") {
    return {
      icon: <RotateCw size={13} />,
      label: "Resume",
      permission: permission === "allow" ? "Safe actions" : "Ask first",
      tone: (permission === "allow" ? "warn" : "neutral") as "warn" | "neutral",
    };
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
}: {
  onSend: (message: string, mode: string, permission: string) => Promise<void>;
  onSideAsk?: (message: string) => Promise<void>;
  sideAsk?: boolean;
  onSideAskToggle?: () => void;
  promptSignal?: PromptSignal;
  viewMode?: import("../hooks/useViewMode").StudioViewMode;
}) {
  const [message, setMessage] = useState("");
  const [mode, setMode] = useState<Mode>("auto");
  const [permission, setPermission] = useState("ask");
  const [sending, setSending] = useState(false);

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
    setMessage("");
    setSending(true);
    try {
      if (sideAsk && onSideAsk) {
        await onSideAsk(text);
      } else {
        await onSend(text, mode, permission);
      }
    } finally {
      setSending(false);
    }
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key !== "Enter") return;
    if (e.shiftKey) return;
    e.preventDefault();
    void submit(e as unknown as React.FormEvent);
  }

  const isAuto = mode === "auto" && !sideAsk;
  const isChat = mode === "chat" || sideAsk;
  const showPermission = !sideAsk && (mode === "auto" || mode === "run" || mode === "resume");
  const isOverflowMode = (OVERFLOW_MODES as readonly string[]).includes(mode);
  const profile = sideAsk
    ? { icon: <MessageCircle size={13} />, label: "Quick ask", permission: "Off-thread", tone: "good" as const }
    : actionProfile(mode, permission);
  const placeholder = sideAsk
    ? "Quick ask — off-thread, with session context (Enter send)…"
    : MODE_PLACEHOLDERS[mode];
  const slashOpen = message.trim() === "/" || /^\/[a-z]*$/i.test(message.trim());
  const slashQuery = message.trim().toLowerCase();
  const slashActions = slashOpen
    ? SLASH_ACTIONS.filter((action) => action.key.startsWith(slashQuery === "/" ? "/" : slashQuery)).slice(0, 5)
    : [];

  return (
    <form className={`composer compact ${isAuto ? "autoMode" : isChat ? "chatMode" : ""}${sideAsk ? " sideAskMode" : ""}`} onSubmit={(event) => void submit(event)}>
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
              <details className="composerModeDetails composerModeOverflow">
                <summary
                  className={isOverflowMode ? "composerModeSummary active" : "composerModeSummary"}
                  title="More modes"
                  aria-label="More modes"
                >
                  <span>{isOverflowMode ? MODE_LABELS[mode] : "⋯"}</span>
                </summary>
                <div className="composerModeMenu">
                  {OVERFLOW_MODES.map((item) => (
                    <button
                      type="button"
                      key={item}
                      className={mode === item ? "active" : ""}
                      onClick={(event) => {
                        setMode(item);
                        (event.currentTarget.closest("details") as HTMLDetailsElement | null)?.removeAttribute("open");
                      }}
                    >
                      {MODE_LABELS[item]}
                    </button>
                  ))}
                </div>
              </details>
            </>
          )}
          {showPermission && (
            <select value={permission} onChange={(event) => setPermission(event.target.value)} aria-label="Permission mode">
              <option value="ask">Ask first</option>
              <option value="allow">Allow safe</option>
            </select>
          )}
          <span className="composerPermissionHint">{viewMode !== "focus" ? profile.permission : ""}</span>
        </div>
        <button className="composerSend" disabled={sending} type="submit">
          {sending ? <Loader2 size={15} className="spinning" /> : <Send size={15} />}
          <span>{isChat ? "Ask" : "Send"}</span>
        </button>
      </div>
    </form>
  );
}
