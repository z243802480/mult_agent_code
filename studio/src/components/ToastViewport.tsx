import React, { useEffect, useState } from "react";
import { CheckCircle2, Info, X, XCircle } from "lucide-react";
import { dismissToast, useToasts, type Toast } from "./toast";

const TONE_ICON = {
  success: CheckCircle2,
  error: XCircle,
  info: Info,
} as const;

function ToastItem({ item }: { item: Toast }) {
  const [exiting, setExiting] = useState(false);
  const [paused, setPaused] = useState(false);
  const Icon = TONE_ICON[item.tone];

  // Auto-dismiss after the lifetime; hovering pauses the countdown (Sonner behavior).
  useEffect(() => {
    if (paused) return;
    const timer = window.setTimeout(() => setExiting(true), item.duration);
    return () => window.clearTimeout(timer);
  }, [item.duration, paused]);

  // Once exiting, let the exit animation play before removing from the store.
  useEffect(() => {
    if (!exiting) return;
    const timer = window.setTimeout(() => dismissToast(item.id), 200);
    return () => window.clearTimeout(timer);
  }, [exiting, item.id]);

  return (
    <div
      className={`toast ${item.tone} ${exiting ? "exiting" : ""}`}
      role="status"
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
    >
      <Icon size={15} className="toastIcon" />
      <span className="toastMessage">{item.message}</span>
      {item.action && (
        <button
          type="button"
          className="toastAction"
          onClick={() => {
            item.action!.onClick();
            setExiting(true);
          }}
        >
          {item.action.label}
        </button>
      )}
      <button
        type="button"
        className="toastClose"
        aria-label="关闭"
        onClick={() => setExiting(true)}
      >
        <X size={13} />
      </button>
    </div>
  );
}

export function ToastViewport() {
  const toasts = useToasts();
  if (!toasts.length) return null;
  return (
    <div className="toastViewport" aria-live="polite">
      {toasts.map((item) => (
        <ToastItem key={item.id} item={item} />
      ))}
    </div>
  );
}
