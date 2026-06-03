import React, { useState } from "react";
import { ClipboardList, Eye, MessageCircle, PlayCircle, RotateCw, Send, ShieldCheck } from "lucide-react";

const MODES = ["auto", "chat", "plan", "run", "review", "resume"] as const;
type Mode = typeof MODES[number];

const MODE_LABELS: Record<Mode, string> = {
  auto: "Auto",
  chat: "Chat",
  plan: "Plan",
  run: "Goal",
  review: "Review",
  resume: "Resume",
};

const MODE_PLACEHOLDERS: Record<Mode, string> = {
  auto: "Tell Asteria what you want. It will answer, plan, or ask before taking action... (Enter to send, Shift+Enter for newline)",
  chat: "Ask a normal question... (Enter to send, Shift+Enter for newline)",
  plan: "Describe what you want planned. Asteria will not change files... (Enter to send, Shift+Enter for newline)",
  run: "Describe a longer goal. Asteria will ask before sensitive actions... (Enter to send, Shift+Enter for newline)",
  review: "Ask Asteria to check the current result... (Enter to send, Shift+Enter for newline)",
  resume: "Continue the current task or add updated constraints... (Enter to send, Shift+Enter for newline)",
};

export type PromptSignal = { text: string; id: number };

function actionProfile(mode: Mode, permission: string) {
  const effective = mode === "auto" ? "auto" : mode;
  if (effective === "chat") {
    return {
      icon: <MessageCircle size={14} />,
      label: "Chat",
      detail: "Answers directly. No workspace changes.",
      permission: "Read-only",
      tone: "good",
    };
  }
  if (effective === "plan") {
    return {
      icon: <ClipboardList size={14} />,
      label: "Plan",
      detail: "Builds a development plan before edits.",
      permission: "Read-only",
      tone: "good",
    };
  }
  if (effective === "review") {
    return {
      icon: <Eye size={14} />,
      label: "Review",
      detail: "Checks current evidence and result.",
      permission: "Read-only evidence",
      tone: "good",
    };
  }
  if (effective === "resume") {
    return {
      icon: <RotateCw size={14} />,
      label: "Resume",
      detail: permission === "allow" ? "Continues with approved safe actions." : "Asks before local changes.",
      permission: permission === "allow" ? "Safe actions allowed" : "Approval required",
      tone: permission === "allow" ? "warn" : "neutral",
    };
  }
  if (effective === "run") {
    return {
      icon: <PlayCircle size={14} />,
      label: "Goal",
      detail: permission === "allow" ? "Starts the controlled runtime." : "Prepares work and asks before changes.",
      permission: permission === "allow" ? "Safe actions allowed" : "Approval required",
      tone: permission === "allow" ? "warn" : "neutral",
    };
  }
  return {
    icon: <ShieldCheck size={14} />,
    label: "Auto",
    detail: "Chooses chat, plan, or goal from your request.",
    permission: permission === "allow" ? "Safe actions allowed" : "Approval required for changes",
    tone: permission === "allow" ? "warn" : "neutral",
  };
}

export function Composer({
  onSend,
  promptSignal,
}: {
  onSend: (message: string, mode: string, permission: string) => Promise<void>;
  promptSignal?: PromptSignal;
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
      await onSend(text, mode, permission);
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

  const isAuto = mode === "auto";
  const isChat = mode === "chat";
  const showPermission = mode === "auto" || mode === "run" || mode === "resume";
  const profile = actionProfile(mode, permission);

  return (
    <form className={`composer ${isAuto ? "autoMode" : isChat ? "chatMode" : ""}`} onSubmit={(event) => void submit(event)}>
      <textarea
        value={message}
        onChange={(event) => setMessage(event.target.value)}
        onKeyDown={onKeyDown}
        placeholder={MODE_PLACEHOLDERS[mode]}
      />
      <div className={`composerActionBar ${profile.tone}`} aria-label="Current action and permission">
        <div className="composerActionMain">
          {profile.icon}
          <strong>{profile.label}</strong>
          <span>{profile.detail}</span>
        </div>
        <div className="composerPermissionPill">
          <ShieldCheck size={12} />
          <span>{profile.permission}</span>
        </div>
      </div>
      <div className="composerBar">
        <div className="modeControls" aria-label="Mode override controls">
          <span className="modeHint">Auto</span>
          <details className="advancedModeDetails"><summary>Advanced</summary><div className="segmented advancedModes" title="Mode override">
            {MODES.map((item) => (
            <button
              type="button"
              className={mode === item ? "active" : ""}
              key={item}
              onClick={() => setMode(item)}
              title={MODE_LABELS[item]}
            >
              {item}
            </button>
            ))}
          </div></details>
        </div>
        {showPermission && (
          <select value={permission} onChange={(event) => setPermission(event.target.value)} aria-label="Permission mode">
            <option value="ask">Ask first</option>
            <option value="allow">Allow safe actions</option>
          </select>
        )}
        <button disabled={sending}>
          <Send size={16} /> {isAuto ? "Send" : isChat ? "Ask" : "Send"}
        </button>
      </div>
    </form>
  );
}
