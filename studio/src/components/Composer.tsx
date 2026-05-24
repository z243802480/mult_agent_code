import React, { useState } from "react";
import { Send } from "lucide-react";

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

  return (
    <form className={`composer ${isAuto ? "autoMode" : isChat ? "chatMode" : ""}`} onSubmit={(event) => void submit(event)}>
      <textarea
        value={message}
        onChange={(event) => setMessage(event.target.value)}
        onKeyDown={onKeyDown}
        placeholder={MODE_PLACEHOLDERS[mode]}
      />
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
