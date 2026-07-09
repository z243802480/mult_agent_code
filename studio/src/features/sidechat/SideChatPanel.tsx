import React, { useEffect, useMemo, useRef, useState } from "react";
import { MessageCircle, X } from "lucide-react";
import type { StudioEvent } from "../../types";
import { MarkdownBody } from "../../components/MarkdownBody";
import { buildSideChatItems, sideChatPending } from "./sideChatUtils";

export function SideChatPanel({
  open,
  events,
  sending,
  onClose,
  onSend,
}: {
  open: boolean;
  events: StudioEvent[];
  sending: boolean;
  onClose: () => void;
  onSend: (message: string) => Promise<void>;
}) {
  const [draft, setDraft] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);
  const items = useMemo(() => buildSideChatItems(events), [events]);
  const waiting = sending || sideChatPending(events);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el || !open) return;
    const smooth = !window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    el.scrollTo({ top: el.scrollHeight, behavior: smooth ? "smooth" : "auto" });
  }, [items.length, waiting, open]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const text = draft.trim();
    if (!text || sending) return;
    setDraft("");
    await onSend(text);
  }

  function onKeyDown(event: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== "Enter" || event.shiftKey) return;
    event.preventDefault();
    void submit(event as unknown as React.FormEvent);
  }

  if (!open) return null;

  return (
    <div className="sideChatDock open" aria-label="快速提问">
      <section className="sideChatPanel">
        <header className="sideChatHeader">
          <div>
            <strong>快速提问</strong>
            <p className="muted">不占用主线程的提问——主目标保持不变。</p>
          </div>
          <button
            type="button"
            className="iconButton"
            title="关闭 (Ctrl+;)"
            aria-label="关闭快速提问"
            onClick={onClose}
          >
            <X size={16} />
          </button>
        </header>
        <div className="sideChatMessages" ref={scrollRef}>
          {items.length === 0 && !waiting && (
            <p className="muted sideChatEmpty">
              可以问工作区、运行状态或规划相关的问题——不会开启新的一轮。
            </p>
          )}
          {items.map((item) => (
            <div key={item.id} className={`sideChatBubble sideChatBubble-${item.kind}`}>
              {item.kind === "assistant" &&
              (item.text.includes("## ") || item.text.includes("```")) ? (
                <MarkdownBody text={item.text} />
              ) : (
                <p>{item.text}</p>
              )}
            </div>
          ))}
          {waiting && (
            <div className="sideChatBubble sideChatBubble-pending">
              <p className="muted">思考中…</p>
            </div>
          )}
        </div>
        <form className="sideChatComposer" onSubmit={(event) => void submit(event)}>
          <textarea
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={onKeyDown}
            placeholder="问一个简短的问题…"
            rows={2}
            disabled={sending}
          />
          <button type="submit" disabled={sending || !draft.trim()}>
            发送
          </button>
        </form>
      </section>
    </div>
  );
}

export function SideChatToggle({ open, onToggle }: { open: boolean; onToggle: () => void }) {
  return (
    <button
      type="button"
      className={open ? "sideChatHeaderButton active" : "sideChatHeaderButton"}
      title="快速提问 (Ctrl+;)"
      aria-label="切换快速提问"
      aria-pressed={open}
      onClick={onToggle}
    >
      <MessageCircle size={16} />
      <span>提问</span>
    </button>
  );
}
