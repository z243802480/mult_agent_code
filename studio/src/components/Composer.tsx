import React, { useState } from "react";
import { Send } from "lucide-react";

const MODES = ["chat", "plan", "run", "review", "resume"] as const;
type Mode = typeof MODES[number];

const MODE_LABELS: Record<Mode, string> = {
  chat: "对话",
  plan: "制定计划",
  run: "执行任务",
  review: "审查结果",
  resume: "恢复运行",
};

const MODE_PLACEHOLDERS: Record<Mode, string> = {
  chat: "问我任何问题：我是谁、怎么用、当前状态... (Ctrl+Enter 发送)",
  plan: "描述目标，我来拆解任务计划：重构某个模块、添加某个功能... (Ctrl+Enter 发送)",
  run: "描述要完成的任务，直接执行：修复失败测试、补全文档... (Ctrl+Enter 发送)",
  review: "留空直接审查最近一次 run，或粘贴具体问题... (Ctrl+Enter 发送)",
  resume: "留空恢复当前 run，或说明新的约束条件... (Ctrl+Enter 发送)",
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
  const [mode, setMode] = useState<Mode>("chat");
  const [permission, setPermission] = useState("ask");
  const [sending, setSending] = useState(false);

  // Fill textarea when a prompt is selected (id changes even for same text)
  React.useEffect(() => {
    if (promptSignal?.text) {
      setMessage(promptSignal.text);
      // Task-style prompts should switch away from chat mode
      setMode((prev) => (prev === "chat" ? "plan" : prev));
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
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      void submit(e as unknown as React.FormEvent);
    }
  }

  const isChat = mode === "chat";

  return (
    <form className={`composer ${isChat ? "chatMode" : ""}`} onSubmit={(event) => void submit(event)}>
      <textarea
        value={message}
        onChange={(event) => setMessage(event.target.value)}
        onKeyDown={onKeyDown}
        placeholder={MODE_PLACEHOLDERS[mode]}
      />
      <div className="composerBar">
        <div className="segmented">
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
        </div>
        {!isChat && (
          <select value={permission} onChange={(event) => setPermission(event.target.value)} aria-label="权限模式">
            <option value="ask">写入前询问</option>
            <option value="allow">直接允许</option>
          </select>
        )}
        <button disabled={sending}>
          <Send size={16} /> {isChat ? "问" : "发送"}
        </button>
      </div>
    </form>
  );
}
