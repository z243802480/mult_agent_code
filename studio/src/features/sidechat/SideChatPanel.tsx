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
    <div className="sideChatDock open" aria-label="Quick ask">
      <section className="sideChatPanel">
        <header className="sideChatHeader">
          <div>
            <strong>Quick ask</strong>
            <p className="muted">Off-thread questions — main goal stays untouched.</p>
          </div>
          <button type="button" className="iconButton" title="Close (Ctrl+;)" aria-label="Close quick ask" onClick={onClose}>
            <X size={16} />
          </button>
        </header>
        <div className="sideChatMessages" ref={scrollRef}>
          {items.length === 0 && !waiting && (
            <p className="muted sideChatEmpty">Ask about the workspace, runtime status, or planning — without starting a new turn.</p>
          )}
          {items.map((item) => (
            <div key={item.id} className={`sideChatBubble sideChatBubble-${item.kind}`}>
              {item.kind === "assistant" && (item.text.includes("## ") || item.text.includes("```")) ? (
                <MarkdownBody text={item.text} />
              ) : (
                <p>{item.text}</p>
              )}
            </div>
          ))}
          {waiting && (
            <div className="sideChatBubble sideChatBubble-pending">
              <p className="muted">Thinking…</p>
            </div>
          )}
        </div>
        <form className="sideChatComposer" onSubmit={(event) => void submit(event)}>
          <textarea
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Ask a quick question…"
            rows={2}
            disabled={sending}
          />
          <button type="submit" disabled={sending || !draft.trim()}>
            Send
          </button>
        </form>
      </section>
    </div>
  );
}

export function SideChatToggle({
  open,
  onToggle,
}: {
  open: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      className={open ? "sideChatHeaderButton active" : "sideChatHeaderButton"}
      title="Quick ask (Ctrl+;)"
      aria-label="Toggle quick ask"
      aria-pressed={open}
      onClick={onToggle}
    >
      <MessageCircle size={16} />
      <span>Ask</span>
    </button>
  );
}
